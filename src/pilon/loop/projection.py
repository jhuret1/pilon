"""Pure proposals and explicit, offline publication of local model snapshots.

Public API (JSON-compatible dictionaries, no third-party dependencies)::

    snapshot_hash(model) -> str
    build_projection(model, candidates, extractions) -> dict
    initialize_store(directory, model, *, actor="local") -> dict
    read_published(directory) -> dict
    read_history(directory) -> list[dict]
    publish_projection(directory, projection, *, expected_revision,
                       idempotency_key=None, actor="local") -> dict
    rollback_publication(directory, target_revision, *, expected_revision,
                         idempotency_key=None, actor="local") -> dict

State/receipt dictionaries contain ``revision``, ``snapshot_hash``, ``model`` and
``audit_id``. Initialization creates revision 0; each successful change adds one
revision. Replaying a publication returns its original receipt, even following a
rollback. Supply a stable idempotency key when retrying rollback. Stale revisions
or base hashes raise RevisionConflict; invalid proposals raise ProjectionError.

Projection never changes its inputs. Its identifier hashes canonical JSON, with
sorted proposal collections and without extraction timing/routing measurements.
``base_model`` and ``projected_model`` are full, independent before/after copies;
individual schema/assignment changes also have before/after values. Existing
schema, aliases, unknown fields and unresolved assignments are preserved. New
facets require at least one accepted assignment. Blocked entries remain backlog;
explicit publication can publish the valid subset. An empty diff cannot publish.

Evidence must carry ``grounding_status='exact_source_verified'``. Every citation
is independently checked against an extraction's unchanged ``source_records``:
catalog role, category, source, product, asset type and exact Unicode offsets.
Demand and external sources cannot assign catalog facts. A marker alone is never
proof, and exact-source verification is not a claim of semantic entailment.
Image evidence also requires ``extraction_method='extractor_callback'``.

Publication rebuilds the proposal from its embedded validation inputs. A local
process lock serializes writers; snapshots and hash-addressed audit records are
written before an atomic HEAD replacement, the sole commit point. Unreferenced
files left by interrupted writes are harmless and excluded from history. Existing
snapshots/audits are never rewritten. Rollback appends an audit record and restores
an old snapshot; it never erases history. Only local files are written: no KG/PIM
requests, credential access, or implicit publishing occurs here.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import unicodedata


class ProjectionError(ValueError):
    """A proposal or persisted artifact failed validation."""


class RevisionConflict(ProjectionError):
    """The caller's revision or proposal base no longer matches publication."""


class PublicationBusyError(ProjectionError):
    """Another process holds the local publication lock; retry later."""


def _canonical(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProjectionError("Expected finite JSON-compatible data") from exc


def _copy(value):
    return json.loads(_canonical(value))


def snapshot_hash(model):
    """SHA-256 of UTF-8 canonical JSON (sorted keys, compact, finite numbers)."""
    return hashlib.sha256(_canonical(model)).hexdigest()


def _sorted_unique(items):
    return [json.loads(item) for item in sorted({_canonical(item) for item in items})]


def _name(value):
    if not isinstance(value, str):
        return ""
    return "_".join(re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", value).casefold()))


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _model(model):
    result = _copy(model)
    if not isinstance(result, dict) or not _text(result.get("category")):
        raise ProjectionError("Model requires a category")
    for field in ("existing_facets", "facets", "assignments"):
        if field in result and not isinstance(result[field], list):
            raise ProjectionError(f"Model {field} must be an array")
    if any(not _text(key) for key in result.get("existing_facets", [])):
        raise ProjectionError("Model existing_facets must contain names")
    if any(not isinstance(facet, dict) or not _name(facet.get("key"))
           or not isinstance(facet.get("values", []), list)
           for facet in result.get("facets", [])):
        raise ProjectionError("Model facets require keys and value arrays")
    if any(not isinstance(item, dict) or not _text(item.get("fact_key"))
           or not _text(item.get("product_id")) or "value" not in item
           for item in result.get("assignments", [])):
        raise ProjectionError("Model assignments require fact_key, product_id and value")
    return result


def _validation_inputs(candidates, extractions):
    candidates = _sorted_unique(list(candidates))
    extracts = []
    # Measurements are not evidence and do not affect a proposal's identity.
    fields = ("candidate_key", "status", "assignments", "conflicts",
              "unknown_products", "source_records", "grounding_status")
    for item in extractions:
        if not isinstance(item, dict):
            raise ProjectionError("Each extraction must be an object")
        item = {key: _copy(item[key]) for key in fields if key in item}
        for field in ("assignments", "conflicts", "unknown_products", "source_records"):
            if field in item:
                if not isinstance(item[field], list):
                    raise ProjectionError(f"Extraction {field} must be an array")
                if field == "assignments":
                    for assignment in item[field]:
                        if isinstance(assignment, dict) and isinstance(assignment.get("evidence"), list):
                            assignment["evidence"] = _sorted_unique(assignment["evidence"])
                item[field] = _sorted_unique(item[field])
        extracts.append(item)
    return {"candidates": candidates, "extractions": _sorted_unique(extracts)}


def _citation_error(proof, product, source_index, demand_ids, category):
    if not isinstance(proof, dict) or proof.get("grounding_status") != "exact_source_verified":
        return "unverified_evidence"
    record_id = proof.get("record_id")
    if not _text(record_id) or record_id in demand_ids:
        return "demand_or_missing_reference"
    records = source_index.get(record_id, [])
    if len(records) != 1:
        return "missing_or_conflicting_source"
    row = records[0]
    if row.get("role") != "catalog":
        return "non_catalog_evidence"
    if row.get("product_id") != product or proof.get("product_id", product) != product:
        return "product_reference_mismatch"
    if row.get("category") != category:
        return "category_mismatch"
    if not _text(row.get("source")) or proof.get("source") != row["source"]:
        return "source_mismatch"
    asset_type = row.get("asset_type", "text")
    if asset_type not in {"text", "document", "image"} or proof.get("asset_type", "text") != asset_type:
        return "asset_type_mismatch"
    if asset_type == "image" and proof.get("extraction_method") != "extractor_callback":
        return "unsupported_image"
    text = row.get("text")
    start, end = proof.get("start"), proof.get("end")
    if (not isinstance(text, str) or type(start) is not int or type(end) is not int
            or not 0 <= start < end <= len(text) or text[start:end] != proof.get("quote")):
        return "invalid_source_span"
    return None


def build_projection(model, candidates, extractions):
    """Return a deterministic, detached proposal; blocked rows never change facts.

    ``validation_inputs`` stores the source material needed to independently
    recheck the entire proposal at publication. It intentionally excludes timing
    metrics. JSON-compatible values (including explicit False) are retained.
    """
    base = _model(model)
    projected = _copy(base)
    inputs = _validation_inputs(candidates, extractions)
    blocked, schema_changes, assignment_changes = [], [], []
    candidates_by_key, extracts_by_key, source_versions = {}, {}, {}
    demand_ids = set()
    for candidate in inputs["candidates"]:
        if not isinstance(candidate, dict) or not _name(candidate.get("key")):
            raise ProjectionError("Each candidate requires a key")
        key = _name(candidate["key"])
        candidates_by_key.setdefault(key, []).append(candidate)
        for proof in candidate.get("demand_records", []):
            if isinstance(proof, dict) and _text(proof.get("record_id", proof.get("id"))):
                demand_ids.add(proof.get("record_id", proof.get("id")))
    for extraction in inputs["extractions"]:
        key = _name(extraction.get("candidate_key"))
        if key not in candidates_by_key:
            blocked.append(dict(candidate_key=key, reason="unknown_candidate", details=extraction))
        extracts_by_key.setdefault(key, []).append(extraction)
        for row in extraction.get("source_records", []):
            if isinstance(row, dict) and _text(row.get("id")):
                source_versions.setdefault(row["id"], set()).add(_canonical(row))

    known = {_name(key) for key in base.get("existing_facets", [])}
    facets = {}
    for index, facet in enumerate(projected.get("facets", [])):
        facets.setdefault(_name(facet["key"]), []).append(index)
    known.update(facets)
    old_assignments = {}
    for index, assignment in enumerate(projected.get("assignments", [])):
        pair = (_name(assignment["fact_key"]), assignment["product_id"])
        old_assignments.setdefault(pair, []).append(index)

    def block(key, reason, product=None, details=None):
        item = dict(candidate_key=key, reason=reason, status="blocked")
        if product is not None:
            item["product_id"] = product
        if details is not None:
            item["details"] = _copy(details)
        blocked.append(item)

    accepted_count = 0
    for key, group in sorted(candidates_by_key.items()):
        candidate = group[0]
        if len(group) != 1:
            block(key, "conflicting_candidates", details=group)
            continue
        if candidate.get("gap_type") == "unresolved_intent":
            block(key, "unresolved_intent", details=candidate)
            continue
        extracts = extracts_by_key.get(key, [])
        if not extracts:
            block(key, "needs_extraction", details=candidate)
            continue
        if len(extracts) != 1:
            block(key, "conflicting_extractions", details=extracts)
            continue
        extraction = extracts[0]
        source_index = {}
        for row in extraction.get("source_records", []):
            if isinstance(row, dict) and _text(row.get("id")):
                # A source ID must identify unchanged content across all stages.
                if len(source_versions[row["id"]]) == 1:
                    source_index.setdefault(row["id"], []).append(row)
        disallowed = set()
        whole_candidate_blocked = False
        for field, reason in (("conflicts", "conflict"), ("unknown_products", "unknown_product")):
            for item in extraction.get(field, []):
                product = item.get("product_id") if isinstance(item, dict) else item
                if not _text(product):
                    product = None
                    whole_candidate_blocked = True
                else:
                    disallowed.add(product)
                block(key, reason, product, item)
        proposals = {}
        for assignment in extraction.get("assignments", []):
            if not isinstance(assignment, dict) or not _text(assignment.get("product_id")):
                block(key, "invalid_assignment", details=assignment)
                continue
            product = assignment["product_id"]
            if whole_candidate_blocked or product in disallowed:
                continue
            if ("value" not in assignment or assignment["value"] is None
                    or (isinstance(assignment["value"], str) and not assignment["value"].strip())):
                block(key, "missing_value", product, assignment)
                continue
            evidence = assignment.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                block(key, "no_evidence", product, assignment)
                continue
            errors = [_citation_error(proof, product, source_index, demand_ids,
                                      base["category"]) for proof in evidence]
            if any(errors):
                block(key, "invalid_evidence", product,
                      dict(assignment=assignment, errors=sorted({error for error in errors if error})))
                continue
            proposals.setdefault(product, []).append(assignment)

        accepted = []
        for product, assignments in sorted(proposals.items()):
            values = _sorted_unique(item["value"] for item in assignments)
            if len(values) != 1:
                block(key, "conflict", product, dict(competing_values=values, assignments=assignments))
                continue
            indices = old_assignments.get((key, product), [])
            if len(indices) > 1:
                block(key, "existing_assignment_conflict", product)
                continue
            before = projected["assignments"][indices[0]] if indices else None
            if before is not None and _canonical(before["value"]) != _canonical(values[0]):
                block(key, "existing_assignment_conflict", product,
                      dict(before=before, proposed=assignments))
                continue
            if len(facets.get(key, [])) > 1:
                block(key, "existing_schema_conflict", product)
                continue
            # An already known value is not re-written merely to accumulate proof.
            # Its existing annotations and publication metadata remain untouched.
            accepted.append((product, values[0]))
            if before is not None:
                continue
            fact_key = projected["facets"][facets[key][0]]["key"] if key in facets else key
            after = dict(fact_key=fact_key, product_id=product, value=values[0],
                         evidence=_sorted_unique(proof for item in assignments for proof in item["evidence"]))
            projected.setdefault("assignments", []).append(after)
            assignment_changes.append(dict(op="add", fact_key=fact_key, product_id=product,
                                           before=None, after=_copy(after), status="proposed"))
        accepted_count += len(accepted)
        if not accepted:
            if not extraction.get("assignments"):
                block(key, "no_evidence", details=dict(extraction_status=extraction.get("status")))
            continue
        values = _sorted_unique(value for _, value in accepted)
        if key not in known:
            after = dict(key=key, label=candidate.get("label") or key,
                         definition=candidate.get("definition") or "", values=values)
            projected.setdefault("facets", []).append(after)
            projected.setdefault("existing_facets", []).append(key)
            schema_changes.append(dict(op="add", key=key, before=None, after=_copy(after), status="proposed"))
            known.add(key)
        elif key in facets:
            index = facets[key][0]
            before = _copy(projected["facets"][index])
            existing_values = {_canonical(value) for value in before.get("values", [])}
            additional = [value for value in values if _canonical(value) not in existing_values]
            if additional:
                projected["facets"][index].setdefault("values", []).extend(additional)
                schema_changes.append(dict(op="update", key=key, before=before,
                                           after=_copy(projected["facets"][index]), status="proposed"))

    blocked = _sorted_unique(blocked)
    result = dict(schema_version=1, base_hash=snapshot_hash(base), base_model=base,
                  schema_changes=schema_changes, assignment_changes=assignment_changes,
                  blocked=blocked, projected_model=projected, validation_inputs=inputs,
                  summary=dict(status="proposed" if schema_changes or assignment_changes else "backlog",
                               candidates=len(candidates_by_key), accepted_assignments=accepted_count,
                               schema_changes=len(schema_changes), assignment_changes=len(assignment_changes),
                               blocked=len(blocked)))
    result["projection_id"] = snapshot_hash(result)
    # Avoid aliases between before/after/diff/validation trees as well as inputs.
    return _copy(result)


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProjectionError(f"Cannot read valid publication artifact: {path.name}") from exc


def _digest(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _read_snapshot(directory, digest):
    if not _digest(digest):
        raise ProjectionError("Invalid snapshot hash")
    model = _read_json(directory / "snapshots" / f"{digest}.json")
    if snapshot_hash(model) != digest:
        raise ProjectionError("Snapshot hash mismatch")
    return _model(model)


def _read_audit(directory, digest):
    if not _digest(digest):
        raise ProjectionError("Invalid audit hash")
    audit = _read_json(directory / "audits" / f"{digest}.json")
    if not isinstance(audit, dict) or audit.get("audit_id") != digest:
        raise ProjectionError("Invalid audit record")
    body = {key: value for key, value in audit.items() if key != "audit_id"}
    if snapshot_hash(body) != digest:
        raise ProjectionError("Audit hash mismatch")
    if type(audit.get("revision")) is not int or audit["revision"] < 0:
        raise ProjectionError("Invalid audit revision")
    return audit


def _head(directory):
    head = _read_json(directory / "HEAD.json")
    if not isinstance(head, dict) or type(head.get("revision")) is not int or head["revision"] < 0:
        raise ProjectionError("Invalid publication head")
    audit = _read_audit(directory, head.get("audit_id"))
    if audit["revision"] != head["revision"] or audit.get("snapshot_hash") != head.get("snapshot_hash"):
        raise ProjectionError("Publication head does not match its audit")
    return head


def _receipt(directory, audit):
    return dict(revision=audit["revision"], snapshot_hash=audit["snapshot_hash"],
                model=_read_snapshot(directory, audit["snapshot_hash"]), audit_id=audit["audit_id"])


def read_published(directory):
    """Read one committed snapshot; an uninitialized store raises ProjectionError."""
    directory = Path(directory)
    return _receipt(directory, _head(directory))


def _history(directory, head):
    history, expected = [], head["revision"]
    digest = head["audit_id"]
    expected_hash = head["snapshot_hash"]
    while digest is not None:
        audit = _read_audit(directory, digest)
        if audit["revision"] != expected or audit["snapshot_hash"] != expected_hash:
            raise ProjectionError("Broken publication audit chain")
        _read_snapshot(directory, audit["snapshot_hash"])
        history.append(audit)
        expected -= 1
        expected_hash = audit.get("base_hash")
        digest = audit.get("previous_audit_id")
        if expected < 0 and digest is not None:
            raise ProjectionError("Cyclic publication audit chain")
    if expected != -1 or history[-1].get("operation") != "initialize":
        raise ProjectionError("Incomplete publication audit chain")
    return list(reversed(history))


def read_history(directory):
    """Return verified committed audits in revision order, ignoring orphan files."""
    directory = Path(directory)
    return _history(directory, _head(directory))


@contextmanager
def _writer(directory):
    directory.mkdir(parents=True, exist_ok=True)
    # OS advisory locks release automatically on process death. The file remains.
    with (directory / ".publication.lock").open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise PublicationBusyError("Publication store is busy; retry later") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _sync_directory(directory):
    if os.name != "nt":
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _atomic_json(path, value, *, immutable=False):
    payload = _canonical(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if immutable and path.exists():
        if path.read_bytes() != payload:
            raise ProjectionError(f"Immutable artifact differs: {path.name}")
        return
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _commit(directory, model, audit):
    digest = snapshot_hash(model)
    audit = dict(audit, snapshot_hash=digest,
                 created_at=datetime.now(timezone.utc).isoformat())
    audit["audit_id"] = snapshot_hash(audit)
    _atomic_json(directory / "snapshots" / f"{digest}.json", model, immutable=True)
    _atomic_json(directory / "audits" / f"{audit['audit_id']}.json", audit, immutable=True)
    head = {key: audit[key] for key in ("revision", "snapshot_hash", "audit_id")}
    _atomic_json(directory / "HEAD.json", dict(schema_version=1, **head))
    return _receipt(directory, audit)


def _actor(actor):
    if not _text(actor):
        raise ProjectionError("Actor must be non-empty text")
    return actor


def initialize_store(directory, model, *, actor="local"):
    """Create revision 0; an existing matching initial/current model is a no-op."""
    model, actor, directory = _model(model), _actor(actor), Path(directory)
    with _writer(directory):
        if (directory / "HEAD.json").exists():
            history = _history(directory, _head(directory))
            if snapshot_hash(model) not in {history[0]["snapshot_hash"], history[-1]["snapshot_hash"]}:
                raise RevisionConflict("Store was initialized with a different model")
            return read_published(directory)
        return _commit(directory, model, dict(schema_version=1, revision=0,
                       operation="initialize", base_hash=None, previous_audit_id=None,
                       actor=actor, idempotency_key=None, request_hash=None))


def _expected_revision(value):
    if type(value) is not int or value < 0:
        raise ProjectionError("expected_revision must be a nonnegative integer")


def _idempotency(key, default):
    if key is None:
        return default
    if not _text(key):
        raise ProjectionError("idempotency_key must be non-empty text")
    return key


def _replay(directory, history, key, request_hash):
    for audit in history:
        if audit.get("idempotency_key") == key:
            if audit.get("request_hash") != request_hash:
                raise ProjectionError("Idempotency key was used for a different request")
            return _receipt(directory, audit)
    return None


def _check_revision(head, expected):
    if head["revision"] != expected:
        raise RevisionConflict(f"Stale revision: expected {expected}, current {head['revision']}")


def publish_projection(directory, projection, *, expected_revision, idempotency_key=None, actor="local"):
    """Explicitly publish a verified proposal using both revision and base-hash CAS.

    Repeated projection IDs are idempotent across the entire committed history.
    Reusing an explicit idempotency key for a different request is an error.
    """
    _expected_revision(expected_revision)
    actor, directory, projection = _actor(actor), Path(directory), _copy(projection)
    try:
        inputs = projection["validation_inputs"]
        rebuilt = build_projection(projection["base_model"], inputs["candidates"], inputs["extractions"])
    except (KeyError, TypeError) as exc:
        raise ProjectionError("Projection lacks its validation inputs") from exc
    if _canonical(projection) != _canonical(rebuilt):
        raise ProjectionError("Projection was modified or fails verification")
    key = _idempotency(idempotency_key, "publish:" + projection["projection_id"])
    request_hash = snapshot_hash(dict(operation="publish", projection_id=projection["projection_id"]))
    with _writer(directory):
        head = _head(directory)
        history = _history(directory, head)
        replay = _replay(directory, history, key, request_hash)
        if replay is not None:
            return replay
        for audit in history:
            if audit.get("operation") == "publish" and audit.get("projection_id") == projection["projection_id"]:
                return _receipt(directory, audit)
        _check_revision(head, expected_revision)
        if projection["base_hash"] != head["snapshot_hash"]:
            raise RevisionConflict("Projection base hash does not match the published model")
        if not projection["schema_changes"] and not projection["assignment_changes"]:
            raise ProjectionError("Projection has no publishable changes")
        return _commit(directory, projection["projected_model"], dict(
            schema_version=1, revision=head["revision"] + 1, operation="publish", actor=actor,
            previous_audit_id=head["audit_id"], base_hash=head["snapshot_hash"],
            projection_id=projection["projection_id"], idempotency_key=key, request_hash=request_hash,
            projection=projection))


def rollback_publication(directory, target_revision, *, expected_revision, idempotency_key=None, actor="local"):
    """Restore an earlier committed revision as a new, audited local revision."""
    _expected_revision(expected_revision)
    if type(target_revision) is not int or target_revision < 0:
        raise ProjectionError("target_revision must be a nonnegative integer")
    directory, actor = Path(directory), _actor(actor)
    key = _idempotency(idempotency_key, f"rollback:{expected_revision}:{target_revision}")
    request_hash = snapshot_hash(dict(operation="rollback", target_revision=target_revision))
    with _writer(directory):
        head = _head(directory)
        history = _history(directory, head)
        replay = _replay(directory, history, key, request_hash)
        if replay is not None:
            return replay
        _check_revision(head, expected_revision)
        if target_revision >= head["revision"]:
            raise ProjectionError("Rollback target must be an earlier committed revision")
        target = history[target_revision]
        model = _read_snapshot(directory, target["snapshot_hash"])
        return _commit(directory, model, dict(
            schema_version=1, revision=head["revision"] + 1, operation="rollback", actor=actor,
            previous_audit_id=head["audit_id"], base_hash=head["snapshot_hash"],
            target_revision=target_revision, target_audit_id=target["audit_id"],
            idempotency_key=key, request_hash=request_hash))
