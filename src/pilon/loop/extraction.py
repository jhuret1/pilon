"""Offline, source-grounded extraction of one proposed fact.

``extract`` returns this JSON-compatible shape (no input is mutated)::

    candidate_key: str
    status: "needs_review" | "needs_extraction"
    assignments: [{product_id, value: str, evidence: [Evidence]}]
    conflicts: [{product_id, competing_values: {value: [Evidence]}}]
    unknown_products: [str]       # no claim; conflicts are listed separately
    unanalysed_products: [str]    # includes partially analysed products
    source_records: [dict]       # full, unchanged selected catalog records
    semantic_validation: "not_performed"
    routing: {method, top_k, exhaustive, truncated, selected, unselected,
              unsupported, excluded}
    metrics: {retrieval: {..., elapsed_seconds}, extraction: {..., elapsed_seconds},
              elapsed_seconds}

Evidence is ``{record_id, product_id, source, quote, start, end, asset_type,
grounding_status: "exact_source_verified", extraction_method}``. Offsets are
Python character offsets into the original text, with an exclusive end. Grounding
verifies the quotation, not the semantic interpretation of an upstream annotation.
Values preserve negation, punctuation and case; distinct supplied values conflict.

Routing entries contain ``record_id, product_id, source, asset_type, reason,
analysis_status``. Selected/unselected entries additionally include ``method,
score, matched_aliases``. Unselected and unsupported assets are *unanalysed*,
never evidence that the fact is absent. Only catalog records in the model's (or
candidate's) category supply product evidence. Without either category, a single
catalog category may be inferred; ambiguous catalog categories are rejected.
The product inventory also includes product IDs in existing model assignments.

Retrieval metrics are ``input_records`` (deduplicated), ``catalog_assets``,
``supported_assets``, ``scored_assets``, ``matched_assets`` (routing eligibility,
not semantic verification), ``selected_assets``, ``unselected_assets``,
``unsupported_assets``, ``excluded_assets``, ``budget_skipped_assets``,
``truncated`` (bool), ``embedding_calls``, and ``elapsed_seconds``. Extraction
metrics are ``analyzed_assets``, ``extracted_claims``, ``matching_claims``,
``evidence_count`` (deduplicated), ``assigned_products``, ``conflicted_products``,
``unknown_products`` (count), and ``elapsed_seconds``. Other counts are integers;
elapsed seconds are measured floats. Determinism excludes elapsed-time metrics.

``embedding_provider(text)`` may return a finite, nonzero numeric vector (or None
to use lexical fallback). Explicit ``embedding`` fields take precedence. Cosine
results rank first, followed by lexical-only matches; ties use record IDs.
``exhaustive=True`` bypasses retrieval and its callbacks and analyses every
supported catalog asset, ignoring top_k. The default has no external dependencies.

``extractor(candidate, record)`` replaces the default extraction adapter and sees
deep copies. It returns an iterable of existing ``Spec`` objects, original feed
annotations (``char_interval``, ``extraction_text``, ``attributes``), or flat
``{label, value, start, end, quote}`` annotations. An optional annotation
``product_id``/``record_id`` must agree with its source. Invalid selected
annotations fail closed with ValueError. Default text/document extraction reuses
``labeled_specs`` or supplied ``extractions``. Images and other modalities require
an explicit extractor; even then every claim needs a quote in the original text.
Source records preserve optional fields as supplied, including omitted asset_type
(which defaults to "text" in evidence and routing).
"""

from collections import defaultdict
from copy import deepcopy
import math
import json
import re
from time import perf_counter
import unicodedata

from ..facets.engine import Spec, labeled_specs


def _name(value):
    return " ".join(re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", value).casefold()))


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Expected non-empty text for {field}")
    return value


def _names(values, field):
    if not isinstance(values, list):
        raise ValueError(f"{field} must be a list of names")
    result = {_name(_text(value, field)) for value in values}
    if "" in result:
        raise ValueError(f"Empty normalized name in {field}")
    return result


def _aliases(candidate, model):
    names = _names([candidate["key"], candidate.get("label", candidate["key"])], "candidate")
    names.update(_names(candidate.get("aliases", []), "candidate aliases"))
    aliases = model.get("aliases", {})
    if not isinstance(aliases, dict):
        raise ValueError("model aliases must map names to lists of phrases")
    groups = [_names([key], "model alias key") | _names(values, "model aliases")
              for key, values in aliases.items()]
    # A candidate may itself use a translated alias rather than the canonical key.
    while True:
        expanded = names.union(*(group for group in groups if group & names))
        if expanded == names:
            return sorted(names)
        names = expanded


def _records(records):
    seen = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Each source record must be an object")
        for field in ("id", "category", "role", "source"):
            _text(record.get(field), field)
        if record["role"] not in {"catalog", "demand", "external"}:
            raise ValueError(f"Unknown role in {record['id']}")
        if not isinstance(record.get("text"), str):
            raise ValueError(f"Expected text in {record['id']} (empty text is allowed)")
        if record["role"] == "catalog":
            _text(record.get("product_id"), "product_id")
        _text(record.get("asset_type", "text"), "asset_type")
        if record["id"] in seen:
            if seen[record["id"]] != record:
                raise ValueError(f"Conflicting records for {record['id']}")
            continue
        seen[record["id"]] = deepcopy(record)
    return sorted(seen.values(), key=lambda row: row["id"])


def _vector(value, field):
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError(f"{field} must be a non-empty numeric vector")
    if any(type(number) not in (int, float) for number in value):
        raise ValueError(f"{field} must contain finite numbers, not booleans")
    try:
        vector = [float(number) for number in value]
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must contain finite numbers") from exc
    if not all(math.isfinite(number) for number in vector):
        raise ValueError(f"{field} must contain finite numbers")
    scale = max(abs(number) for number in vector)
    if not scale:
        raise ValueError(f"{field} must be a nonzero vector")
    # Scale first: both huge finite numbers and subnormal vectors remain usable.
    scaled = [number / scale for number in vector]
    norm = math.sqrt(math.fsum(number * number for number in scaled))
    return [number / norm for number in scaled]


def _cosine(left, right):
    if len(left) != len(right):
        raise ValueError("Candidate and source embedding dimensions must match")
    return max(-1.0, min(1.0, math.fsum(a * b for a, b in zip(left, right))))


def _compatible_space(candidate, row, dimensions):
    """Declared embedding spaces must match; omitted contracts are explicitly unverified."""
    left,right=candidate.get('embedding_contract'),row.get('embedding_contract')
    if left is None and right is None:
        return 'unspecified_by_caller'
    for contract in (left,right):
        if (not isinstance(contract,dict) or not isinstance(contract.get('model'),str)
                or not contract['model'].strip() or type(contract.get('dimensions')) is not int
                or contract['dimensions']!=dimensions):
            raise ValueError('Missing or invalid embedding contract')
        json.dumps(contract,allow_nan=False)
    if left!=right:
        raise ValueError('Candidate and source embedding contracts must match')
    return 'matched'


def _routing_entry(row, reason, analysis_status="unanalysed", **extra):
    return dict(record_id=row["id"], product_id=row.get("product_id"),
                source=row["source"], asset_type=row.get("asset_type", "text"),
                reason=reason, analysis_status=analysis_status, **extra)


def _lexical_matches(row, aliases):
    text = " " + _name(row["text"]) + " "
    # Supplied annotation labels are routing metadata, not validated evidence.
    # Offsets and quotes are checked only if this asset is actually selected.
    labels = set()
    annotations = row.get("extractions", [])
    if isinstance(annotations, list):
        for annotation in annotations:
            if not isinstance(annotation, dict):
                continue
            attrs = annotation.get("attributes", annotation)
            if isinstance(attrs, dict) and isinstance(attrs.get("label"), str):
                labels.add(_name(attrs["label"]))
    return [alias for alias in aliases if " " + alias + " " in text or alias in labels]


def _annotation(annotation, row):
    text = row["text"]
    if isinstance(annotation, Spec):
        label, value, start, end = annotation.label, annotation.value, annotation.start, annotation.end
        quote = text[start:end] if type(start) is int and type(end) is int else None
    elif isinstance(annotation, dict):
        for field, expected in (("product_id", row["product_id"]), ("record_id", row["id"]),
                                ("source", row["source"])):
            if field in annotation and annotation[field] != expected:
                raise ValueError(f"Wrong {field} in annotation for {row['id']}")
        if "char_interval" in annotation or "attributes" in annotation:
            span, attrs = annotation.get("char_interval"), annotation.get("attributes")
            if not isinstance(span, dict) or not isinstance(attrs, dict):
                raise ValueError(f"Expected char_interval and attributes in {row['id']}")
            start, end = span.get("start_pos"), span.get("end_pos")
            label, value = attrs.get("label"), attrs.get("value")
            quote = annotation.get("extraction_text")
        else:
            start, end = annotation.get("start"), annotation.get("end")
            label, value, quote = annotation.get("label"), annotation.get("value"), annotation.get("quote")
    else:
        raise ValueError(f"Invalid extraction in {row['id']}")
    if (type(start) is not int or type(end) is not int or
            not 0 <= start < end <= len(text) or not isinstance(quote, str) or
            text[start:end] != quote):
        raise ValueError(f"Unverified source quotation in {row['id']}")
    _text(label, "label")
    _text(value, "value")
    if not _name(label):
        raise ValueError(f"Empty normalized label in {row['id']}")
    return Spec(label, value.strip(), start, end)


def _extract_specs(candidate, row, extractor):
    if extractor is not None:
        annotations = extractor(deepcopy(candidate), deepcopy(row))
        method = "extractor_callback"
    elif "extractions" in row:
        annotations = row["extractions"]
        if not isinstance(annotations, list):
            raise ValueError(f"Expected extractions array in {row['id']}")
        method = "supplied_annotation"
    else:
        annotations = labeled_specs(row["text"])
        method = "labeled_specs"
    if annotations is None or isinstance(annotations, (str, bytes, dict)):
        raise ValueError(f"Expected an iterable of extractions in {row['id']}")
    try:
        iterator = iter(annotations)
    except TypeError as exc:
        raise ValueError(f"Expected an iterable of extractions in {row['id']}") from exc
    for annotation in iterator:
        yield _annotation(annotation, row), method


def extract(candidate, records, model=None, *, top_k=50, exhaustive=False,
            embedding_provider=None, extractor=None):
    """Extract a candidate with measured retrieval/extraction and exact provenance.

    ``top_k`` is a nonnegative asset budget, not a product limit. Zero performs
    no extraction. Exhaustive mode ignores this budget. No content is truncated.
    Missing evidence retains the candidate and leaves products unknown.
    """
    started = perf_counter()
    if not isinstance(candidate, dict):
        raise ValueError("Expected a candidate object")
    key = _text(candidate.get("key"), "candidate key")
    if model is None:
        model = {}
    if not isinstance(model, dict):
        raise ValueError("Expected a model object")
    if type(top_k) is not int or top_k < 0:
        raise ValueError("top_k must be a nonnegative integer")
    if type(exhaustive) is not bool:
        raise ValueError("exhaustive must be a boolean")
    for name, callback in (("embedding_provider", embedding_provider), ("extractor", extractor)):
        if callback is not None and not callable(callback):
            raise ValueError(f"{name} must be callable")
    aliases = _aliases(candidate, model)
    rows = _records(records)
    category = model.get("category", candidate.get("category"))
    if category is not None:
        _text(category, "category")
        if "category" in candidate and candidate["category"] != category:
            raise ValueError("Candidate and model category must match")
    else:
        categories = {row["category"] for row in rows if row["role"] == "catalog"}
        if len(categories) > 1:
            raise ValueError("A category is required for multiple catalog categories")
        category = next(iter(categories), None)
    catalog = [row for row in rows if row["role"] == "catalog" and row["category"] == category]
    products = {row["product_id"] for row in catalog}
    model_assignments = model.get("assignments", [])
    if not isinstance(model_assignments, list):
        raise ValueError("model assignments must be a list")
    for assignment in model_assignments:
        if not isinstance(assignment, dict):
            raise ValueError("Each model assignment must be an object")
        products.add(_text(assignment.get("product_id"), "assignment product_id"))
    supported, unsupported, excluded = [], [], []
    for row in rows:
        if row["role"] != "catalog" or row["category"] != category:
            reason = "not_catalog" if row["role"] != "catalog" else "outside_category"
            excluded.append(_routing_entry(row, reason))
            continue
        asset_type = row.get("asset_type", "text")
        if extractor is None and asset_type not in {"text", "document"}:
            unsupported.append(_routing_entry(row, "explicit_extractor_required"))
        elif extractor is None and asset_type == "document" and not row["text"].strip():
            unsupported.append(_routing_entry(row, "document_text_unavailable"))
        else:
            supported.append(row)

    embedding_calls = 0

    def embedding(item, text, field):
        nonlocal embedding_calls
        value = item.get("embedding")
        if value is None and embedding_provider is not None:
            embedding_calls += 1
            value = embedding_provider(text)
        return _vector(value, field)

    ranked, unselected = [], []
    methods = set()
    if exhaustive:
        for row in supported:
            ranked.append((0, 0, row, _routing_entry(row, "exhaustive", method="exhaustive",
                                                   score=None, matched_aliases=[])))
        method = "exhaustive"
    else:
        query = "\n".join([candidate.get("label", key), str(candidate.get("definition", "")), *aliases])
        query_vector = embedding(candidate, query, "candidate embedding") if supported else None
        for row in supported:
            matches = _lexical_matches(row, aliases)
            vector = embedding(row, row["text"], f"embedding in {row['id']}")
            if query_vector is not None and vector is not None:
                score = _cosine(query_vector, vector)
                contract_status = _compatible_space(candidate,row,len(query_vector))
                entry = _routing_entry(row, "cosine_rank", method="cosine", score=score,
                                       matched_aliases=matches,embedding_contract_status=contract_status)
                ranked.append((0, -score, row, entry))
                methods.add("cosine")
            else:
                score = len(matches) / len(aliases)
                entry = _routing_entry(row, "lexical_match" if matches else "no_lexical_match",
                                       method="lexical", score=score, matched_aliases=matches)
                methods.add("lexical")
                if matches:
                    ranked.append((1, -score, row, entry))
                else:
                    unselected.append(entry)
        method = "cosine_then_lexical" if len(methods) > 1 else next(iter(methods), "lexical")
    ranked.sort(key=lambda item: (item[0], item[1], item[2]["id"]))
    selected = ranked if exhaustive else ranked[:top_k]
    budget_skipped = [] if exhaustive else ranked[top_k:]
    for _, _, _, entry in budget_skipped:
        unselected.append(dict(entry, reason="budget_limit"))
    unselected.sort(key=lambda entry: entry["record_id"])
    routing = dict(method=method, top_k=top_k, exhaustive=exhaustive, truncated=bool(budget_skipped),
                   selected=[], unselected=unselected, unsupported=unsupported, excluded=excluded)
    retrieval_seconds = perf_counter() - started

    extraction_started = perf_counter()
    claims = defaultdict(lambda: defaultdict(list))
    extracted_claims = matching_claims = 0
    for _, _, row, entry in selected:
        for spec, extraction_method in _extract_specs(candidate, row, extractor):
            extracted_claims += 1
            if _name(spec.label) not in aliases:
                continue
            matching_claims += 1
            proof = dict(record_id=row["id"], product_id=row["product_id"], source=row["source"],
                         quote=row["text"][spec.start:spec.end], start=spec.start, end=spec.end,
                         asset_type=row.get("asset_type", "text"),
                         grounding_status="exact_source_verified", extraction_method=extraction_method)
            evidence = claims[row["product_id"]][spec.value]
            if proof not in evidence:
                evidence.append(proof)
        routing["selected"].append(dict(entry, analysis_status="analysed"))
    assignments, conflicts = [], []
    for product, values in sorted(claims.items()):
        ordered = {value: sorted(evidence, key=lambda proof: (proof["record_id"], proof["start"], proof["end"]))
                   for value, evidence in sorted(values.items())}
        if len(ordered) == 1:
            value, evidence = next(iter(ordered.items()))
            assignments.append(dict(product_id=product, value=value, evidence=evidence))
        else:
            conflicts.append(dict(product_id=product, competing_values=ordered))
    unknown = sorted(products.difference(claims))
    unanalysed = sorted({entry["product_id"] for entry in unselected + unsupported}
                       | products.difference(row["product_id"] for row in catalog))
    extraction_seconds = perf_counter() - extraction_started
    return dict(
        candidate_key=key, status="needs_review" if claims else "needs_extraction",
        assignments=assignments, conflicts=conflicts, unknown_products=unknown,
        unanalysed_products=unanalysed,
        source_records=[deepcopy(row) for _, _, row, _ in selected],
        semantic_validation="not_performed", routing=routing,
        metrics=dict(
            retrieval=dict(input_records=len(rows), catalog_assets=len(catalog),
                           supported_assets=len(supported), scored_assets=0 if exhaustive else len(supported),
                           matched_assets=len(ranked), selected_assets=len(selected),
                           unselected_assets=len(unselected), unsupported_assets=len(unsupported),
                           excluded_assets=len(excluded), budget_skipped_assets=len(budget_skipped),
                           truncated=bool(budget_skipped), embedding_calls=embedding_calls,
                           elapsed_seconds=retrieval_seconds),
            extraction=dict(analyzed_assets=len(selected), extracted_claims=extracted_claims,
                            matching_claims=matching_claims,
                            evidence_count=sum(len(evidence) for values in claims.values() for evidence in values.values()),
                            assigned_products=len(assignments), conflicted_products=len(conflicts),
                            unknown_products=len(unknown), elapsed_seconds=extraction_seconds),
            elapsed_seconds=perf_counter() - started))
