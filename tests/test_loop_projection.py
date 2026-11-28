"""Projection integrity and local publication, entirely synthetic and offline."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import threading

import pytest

from pilon.loop import projection as api
from pilon.loop.projection import (
    ProjectionError, PublicationBusyError, RevisionConflict, build_projection,
    initialize_store, publish_projection, read_history, read_published,
    rollback_publication, snapshot_hash,
)


@pytest.fixture
def inputs():
    model = dict(category="running-shoes", version="merchant-v1",
                 window_start="2026-09-01", window_end="2026-09-30",
                 existing_facets=["width", "size"], aliases={"toe box": ["room for toes"]},
                 merchant_metadata={"owner": "synthetic", "preserve": [1, 2]})
    candidate = dict(key="toe_box", label="Toe box", definition="Space around the toes",
                     aliases=["room for toes"], demand_events=3,
                     demand_records=[dict(record_id="q1", source="search", quote="toe box", start=0, end=7)],
                     gap_type="schema_gap", status="needs_extraction")
    row = dict(id="s1", product_id="P1", text="Édition été. Toe box: wide",
               role="catalog", category=model["category"], source="merchant", asset_type="text",
               vendor_extension={"retained": True})
    start = row["text"].index("Toe")
    proof = dict(record_id="s1", source="merchant", quote=row["text"][start:],
                 start=start, end=len(row["text"]), asset_type="text",
                 grounding_status="exact_source_verified")
    extraction = dict(candidate_key="toe_box", status="extracted",
                      assignments=[dict(product_id="P1", value="wide", evidence=[proof])],
                      conflicts=[], unknown_products=[], source_records=[row],
                      metrics={"elapsed_seconds": 0.123}, routing={"selected": ["s1"]})
    return model, [candidate], [extraction]


def proposal(inputs):
    return build_projection(*inputs)


def reasons(projection):
    return {row["reason"] for row in projection["blocked"]}


def test_pure_projection_has_full_diffs_and_keeps_original_fields(inputs):
    before = deepcopy(inputs)
    out = proposal(inputs)
    assert inputs == before
    assert out["base_hash"] == snapshot_hash(inputs[0])
    assert out["base_model"] == inputs[0]
    assert out["summary"]["status"] == "proposed"
    change, = out["schema_changes"]
    assert change == dict(op="add", key="toe_box", before=None,
                          after=dict(key="toe_box", label="Toe box", definition="Space around the toes", values=["wide"]),
                          status="proposed")
    assignment, = out["assignment_changes"]
    assert assignment["before"] is None
    assert assignment["after"] == out["projected_model"]["assignments"][0]
    assert out["projected_model"]["existing_facets"] == ["width", "size", "toe_box"]
    for field in ("version", "aliases", "window_start", "window_end", "merchant_metadata"):
        assert out["projected_model"][field] == inputs[0][field]
    assert out["validation_inputs"]["extractions"][0]["source_records"][0]["vendor_extension"] == {"retained": True}
    # All returned trees are detached from inputs and from each other.
    out["projected_model"]["merchant_metadata"]["preserve"].append(3)
    out["assignment_changes"][0]["after"]["value"] = "changed"
    assert out["base_model"] == inputs[0] == before[0]
    assert out["projected_model"]["assignments"][0]["value"] == "wide"


def test_canonical_hash_order_independent_and_nonfinite_rejected():
    assert snapshot_hash({"b": 2, "a": "été"}) == snapshot_hash({"a": "été", "b": 2})
    assert snapshot_hash({"value": False}) != snapshot_hash({"value": 0})
    with pytest.raises(ProjectionError, match="finite"):
        snapshot_hash({"value": float("nan")})


def test_projection_determinism_order_duplicates_and_measurements(inputs):
    model, candidates, extractions = inputs
    second = deepcopy(candidates[0])
    second.update(key="removable_insole", label="Removable insole")
    candidates.append(second)
    extractions[0]["assignments"].append(deepcopy(extractions[0]["assignments"][0]))
    extractions[0]["source_records"].append(deepcopy(extractions[0]["source_records"][0]))
    first = proposal(inputs)
    candidates.reverse()
    extractions[0]["source_records"].reverse()
    extractions[0]["metrics"]["elapsed_seconds"] = 29.9
    extractions[0]["routing"] = {"irrelevant_for_projection": True}
    assert first == proposal(inputs)
    assert len(first["assignment_changes"]) == 1
    assert "needs_extraction" in reasons(first)


def test_no_extraction_or_unresolved_demand_stays_backlog(inputs):
    model, candidates, _ = inputs
    out = build_projection(model, candidates, [])
    assert out["projected_model"] == model
    assert out["schema_changes"] == out["assignment_changes"] == []
    assert reasons(out) == {"needs_extraction"}
    candidates[0]["gap_type"] = "unresolved_intent"
    out = proposal(inputs)
    assert out["projected_model"] == model
    assert reasons(out) == {"unresolved_intent"}


@pytest.mark.parametrize("status", ["no_data", "no_evidence", "needs_extraction"])
def test_no_data_never_adds_empty_facets(inputs, status):
    inputs[2][0].update(status=status, assignments=[], source_records=[])
    out = proposal(inputs)
    assert out["projected_model"] == inputs[0]
    assert reasons(out) == {"no_evidence"}


@pytest.mark.parametrize("field,value,error", [
    ("grounding_status", "claimed", "unverified_evidence"),
    ("quote", "Toe box: tapered", "invalid_source_span"),
    ("start", True, "invalid_source_span"),
    ("end", 999, "invalid_source_span"),
    ("source", "another-merchant", "source_mismatch"),
    ("record_id", "unknown", "missing_or_conflicting_source"),
    ("asset_type", "image", "asset_type_mismatch"),
])
def test_citations_rechecked_even_with_validation_marker(inputs, field, value, error):
    inputs[2][0]["assignments"][0]["evidence"][0][field] = value
    out = proposal(inputs)
    assert out["projected_model"] == inputs[0]
    assert out["assignment_changes"] == []
    assert error in out["blocked"][0]["details"]["errors"]


@pytest.mark.parametrize("role", ["demand", "external"])
def test_non_catalog_sources_cannot_be_product_evidence(inputs, role):
    inputs[2][0]["source_records"][0]["role"] = role
    out = proposal(inputs)
    assert not out["assignment_changes"]
    assert "non_catalog_evidence" in out["blocked"][0]["details"]["errors"]


def test_demand_record_cannot_be_laundered_into_catalog_evidence(inputs):
    inputs[1][0]["demand_records"][0]["record_id"] = "s1"
    out = proposal(inputs)
    assert not out["assignment_changes"]
    assert "demand_or_missing_reference" in out["blocked"][0]["details"]["errors"]


def test_product_and_category_references_must_match(inputs):
    inputs[2][0]["assignments"][0]["product_id"] = "OTHER"
    out = proposal(inputs)
    assert not out["assignment_changes"]
    assert "product_reference_mismatch" in out["blocked"][0]["details"]["errors"]
    inputs[2][0]["assignments"][0]["product_id"] = "P1"
    proof = inputs[2][0]["assignments"][0]["evidence"][0]
    proof["product_id"] = "OTHER"
    assert "product_reference_mismatch" in proposal(inputs)["blocked"][0]["details"]["errors"]
    proof["product_id"] = "P1"
    inputs[2][0]["source_records"][0]["category"] = "another-category"
    assert "category_mismatch" in proposal(inputs)["blocked"][0]["details"]["errors"]


def test_missing_or_ambiguous_source_records_fail_closed(inputs):
    extraction = inputs[2][0]
    altered = deepcopy(extraction["source_records"][0])
    altered["text"] += " now different"
    extraction["source_records"].append(altered)
    assert not proposal(inputs)["assignment_changes"]
    extraction["source_records"] = []
    assert not proposal(inputs)["assignment_changes"]


def test_images_need_an_explicit_adapter_and_verified_text(inputs):
    extraction = inputs[2][0]
    extraction["source_records"][0]["asset_type"] = "image"
    extraction["assignments"][0]["evidence"][0]["asset_type"] = "image"
    assert not proposal(inputs)["assignment_changes"]
    extraction["assignments"][0]["evidence"][0]["extraction_method"] = "extractor_callback"
    assert len(proposal(inputs)["assignment_changes"]) == 1
    extraction["source_records"][0]["text"] = "picture-wide.jpg"
    assert not proposal(inputs)["assignment_changes"]


def test_explicit_negative_is_an_assignment_not_unknown(inputs):
    inputs[2][0]["assignments"][0]["value"] = False
    out = proposal(inputs)
    assert out["projected_model"]["assignments"][0]["value"] is False
    assert out["projected_model"]["facets"][0]["values"] == [False]


def test_conflicts_and_unknowns_are_visible_and_block_products(inputs):
    extraction = inputs[2][0]
    extraction["conflicts"] = [dict(product_id="P1", competing_values=["wide", "tapered"])]
    extraction["unknown_products"] = ["P2"]
    out = proposal(inputs)
    assert out["projected_model"] == inputs[0]
    assert {"conflict", "unknown_product"} <= reasons(out)
    extraction["conflicts"] = []
    extraction["unknown_products"] = ["P1"]
    assert not proposal(inputs)["assignment_changes"]


def test_implicit_conflict_cannot_be_hidden_by_omitting_conflict_list(inputs):
    extraction = inputs[2][0]
    contrary = deepcopy(extraction["assignments"][0])
    contrary["value"] = "tapered"
    extraction["assignments"].append(contrary)
    out = proposal(inputs)
    assert not out["assignment_changes"]
    assert reasons(out) == {"conflict"}


def test_existing_assignment_disagreement_is_blocked_without_overwriting(inputs):
    inputs[0]["existing_facets"].append("toe_box")
    inputs[0]["assignments"] = [dict(fact_key="toe_box", product_id="P1", value="tapered",
                                     evidence=[{"legacy": "preserved"}])]
    out = proposal(inputs)
    assert out["projected_model"] == inputs[0]
    assert reasons(out) == {"existing_assignment_conflict"}


def test_known_schema_preserved_and_valid_values_have_before_after(inputs):
    model = inputs[0]
    model["existing_facets"].append("toe_box")
    facet = dict(key="toe_box", label="Merchant label", definition="Merchant definition",
                 values=["tapered"], merchant_only="preserved")
    model["facets"] = [deepcopy(facet)]
    out = proposal(inputs)
    change, = out["schema_changes"]
    assert change["op"] == "update" and change["before"] == facet
    assert change["after"] == dict(facet, values=["tapered", "wide"])
    assert out["projected_model"]["existing_facets"] == model["existing_facets"]
    # Legacy known names need no invented empty detail objects.
    del model["facets"]
    out = proposal(inputs)
    assert not out["schema_changes"] and "facets" not in out["projected_model"]
    assert len(out["assignment_changes"]) == 1


def test_existing_matching_assignment_is_unchanged(inputs):
    first = proposal(inputs)
    out = build_projection(first["projected_model"], inputs[1], inputs[2])
    assert out["projected_model"] == first["projected_model"]
    assert out["schema_changes"] == out["assignment_changes"] == []


def test_initialize_publish_repeat_and_immutable_history(inputs, tmp_path):
    initial = initialize_store(tmp_path, inputs[0])
    assert initial["revision"] == 0 and initial["model"] == inputs[0]
    assert initialize_store(tmp_path, inputs[0]) == initial
    initial_bytes = {str(p): p.read_bytes() for p in tmp_path.rglob("*.json") if p.name != "HEAD.json"}
    out = proposal(inputs)
    receipt = publish_projection(tmp_path, out, expected_revision=0, idempotency_key="job-1", actor="reviewer")
    assert receipt["revision"] == 1
    assert receipt["model"] == out["projected_model"]
    assert read_published(tmp_path) == receipt
    assert initialize_store(tmp_path, receipt["model"]) == receipt
    assert publish_projection(tmp_path, out, expected_revision=0, idempotency_key="job-1") == receipt
    assert publish_projection(tmp_path, out, expected_revision=1) == receipt
    assert len(read_history(tmp_path)) == 2
    assert all(Path(name).read_bytes() == value for name, value in initial_bytes.items())
    with pytest.raises(RevisionConflict, match="initialized"):
        initialize_store(tmp_path, dict(inputs[0], version="other"))


def test_stale_revision_and_stale_base_are_independent_checks(inputs, tmp_path):
    initialize_store(tmp_path, inputs[0])
    first = proposal(inputs)
    publish_projection(tmp_path, first, expected_revision=0)
    second_inputs = deepcopy(inputs)
    second_inputs[1][0]["definition"] = "Another valid proposal from the old base"
    stale = proposal(second_inputs)
    with pytest.raises(RevisionConflict, match="revision"):
        publish_projection(tmp_path, stale, expected_revision=0)
    with pytest.raises(RevisionConflict, match="base hash"):
        publish_projection(tmp_path, stale, expected_revision=1)
    assert len(read_history(tmp_path)) == 2


def test_idempotency_key_reuse_for_different_action_is_rejected(inputs, tmp_path):
    initialize_store(tmp_path, inputs[0])
    publish_projection(tmp_path, proposal(inputs), expected_revision=0, idempotency_key="one")
    inputs[1][0]["definition"] = "Different projection"
    with pytest.raises(ProjectionError, match="different request"):
        publish_projection(tmp_path, proposal(inputs), expected_revision=1, idempotency_key="one")
    with pytest.raises(ProjectionError, match="different request"):
        rollback_publication(tmp_path, 0, expected_revision=1, idempotency_key="one")


def test_rollback_restores_exact_legacy_snapshot_and_keeps_audit(inputs, tmp_path):
    initial = initialize_store(tmp_path, inputs[0])
    out = proposal(inputs)
    published = publish_projection(tmp_path, out, expected_revision=0)
    original_files = {str(p): p.read_bytes() for p in tmp_path.rglob("*.json") if p.name != "HEAD.json"}
    restored = rollback_publication(tmp_path, 0, expected_revision=1, idempotency_key="undo-job")
    assert restored["revision"] == 2
    assert restored["model"] == inputs[0]
    assert restored["snapshot_hash"] == initial["snapshot_hash"]
    assert restored["audit_id"] != initial["audit_id"]
    assert [a["operation"] for a in read_history(tmp_path)] == ["initialize", "publish", "rollback"]
    assert rollback_publication(tmp_path, 0, expected_revision=1, idempotency_key="undo-job") == restored
    assert publish_projection(tmp_path, out, expected_revision=0) == published
    assert read_published(tmp_path) == restored
    assert all(Path(name).read_bytes() == value for name, value in original_files.items())
    # ABA: returning to the same model hash does not make an old revision valid.
    inputs[1][0]["definition"] = "Fresh proposal, stale revision"
    with pytest.raises(RevisionConflict, match="revision"):
        publish_projection(tmp_path, proposal(inputs), expected_revision=0)


def test_invalid_rollback_is_read_only(inputs, tmp_path):
    initialize_store(tmp_path, inputs[0])
    publish_projection(tmp_path, proposal(inputs), expected_revision=0)
    for target in (-1, 1, 10, True):
        with pytest.raises(ProjectionError):
            rollback_publication(tmp_path, target, expected_revision=1)
    with pytest.raises(RevisionConflict):
        rollback_publication(tmp_path, 0, expected_revision=0)
    assert len(read_history(tmp_path)) == 2


def test_publish_rebuilds_proposal_and_rejects_rehashed_tampering(inputs, tmp_path):
    initialize_store(tmp_path, inputs[0])
    out = proposal(inputs)
    out["projected_model"]["assignments"][0]["product_id"] = "OTHER"
    out["projection_id"] = snapshot_hash({k: v for k, v in out.items() if k != "projection_id"})
    with pytest.raises(ProjectionError, match="modified"):
        publish_projection(tmp_path, out, expected_revision=0)
    assert read_published(tmp_path)["model"] == inputs[0]


def test_only_valid_subset_publishes_empty_projection_rejected(inputs, tmp_path):
    initialize_store(tmp_path, inputs[0])
    inputs[2][0]["unknown_products"] = ["P2"]
    out = proposal(inputs)
    receipt = publish_projection(tmp_path, out, expected_revision=0)
    assert [item["product_id"] for item in receipt["model"]["assignments"]] == ["P1"]
    assert read_history(tmp_path)[-1]["projection"]["blocked"] == out["blocked"]
    empty = build_projection(receipt["model"], inputs[1], [])
    with pytest.raises(ProjectionError, match="no publishable"):
        publish_projection(tmp_path, empty, expected_revision=1)


def test_interrupted_publication_leaves_head_and_history_intact(inputs, tmp_path, monkeypatch):
    initial = initialize_store(tmp_path, inputs[0])
    replace = api.os.replace
    def fail_head(source, target):
        if Path(target).name == "HEAD.json":
            raise OSError("simulated interruption before commit")
        return replace(source, target)
    monkeypatch.setattr(api.os, "replace", fail_head)
    with pytest.raises(OSError, match="simulated interruption"):
        publish_projection(tmp_path, proposal(inputs), expected_revision=0)
    assert read_published(tmp_path) == initial
    assert len(read_history(tmp_path)) == 1
    assert not list(tmp_path.rglob("*.tmp"))
    monkeypatch.setattr(api.os, "replace", replace)
    assert publish_projection(tmp_path, proposal(inputs), expected_revision=0)["revision"] == 1
    assert len(read_history(tmp_path)) == 2


def test_snapshot_and_audit_corruption_detected(inputs, tmp_path):
    initial = initialize_store(tmp_path, inputs[0])
    snapshot = tmp_path / "snapshots" / (initial["snapshot_hash"] + ".json")
    original = snapshot.read_bytes()
    snapshot.write_text(json.dumps(dict(inputs[0], version="tampered")), encoding="utf-8")
    with pytest.raises(ProjectionError, match="Snapshot hash"):
        read_published(tmp_path)
    snapshot.write_bytes(original)
    audit = tmp_path / "audits" / (initial["audit_id"] + ".json")
    data = json.loads(audit.read_text(encoding="utf-8"))
    data["actor"] = "tampered"
    audit.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ProjectionError, match="Audit hash"):
        read_history(tmp_path)


def test_concurrent_writers_cannot_both_publish_the_same_base(inputs, tmp_path):
    initialize_store(tmp_path, inputs[0])
    first = proposal(inputs)
    inputs[1][0]["definition"] = "Competing change"
    second = proposal(inputs)
    barrier = threading.Barrier(2)
    def publish(out):
        barrier.wait(timeout=5)
        try:
            return publish_projection(tmp_path, out, expected_revision=0)
        except (RevisionConflict, PublicationBusyError) as exc:
            return exc
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(publish, [first, second]))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert len(read_history(tmp_path)) == 2
    assert read_published(tmp_path)["revision"] == 1


def test_legacy_discovery_inputs_are_unchanged_and_still_accepted(inputs):
    from pilon.facets import explore
    from pilon.facets.commands import EXAMPLE
    from pilon.facets.io import read_signals
    model = json.loads((EXAMPLE / "model.json").read_text(encoding="utf-8"))
    records = list(read_signals(EXAMPLE / "signals.jsonl"))
    original = explore(model, records)
    snapshot = deepcopy(model)
    build_projection(model, inputs[1], inputs[2])
    assert model == snapshot
    assert explore(model, records) == original


def test_real_extractor_to_projection_contract_and_image_adapter(inputs):
    from pilon.facets import Spec
    from pilon.loop.extraction import extract
    model, candidates, extractions = inputs
    records = deepcopy(extractions[0]["source_records"])
    records[0]["text"] = "Édition été.\nToe box: wide"
    extraction = extract(candidates[0], records, model)
    out = build_projection(model, candidates, [extraction])
    assert len(out["assignment_changes"]) == 1
    assert not out["blocked"]
    records[0]["asset_type"] = "image"
    def adapter(candidate, row):
        return [Spec("Toe box", "wide", row["text"].index("Toe"), len(row["text"]))]
    extraction = extract(candidates[0], records, model, extractor=adapter)
    assert len(build_projection(model, candidates, [extraction])["assignment_changes"]) == 1


def test_inconsistent_source_records_across_extractions_are_blocked(inputs):
    candidate = deepcopy(inputs[1][0])
    candidate.update(key="different_fact", label="Different fact")
    inputs[1].append(candidate)
    extraction = deepcopy(inputs[2][0])
    extraction["candidate_key"] = "different_fact"
    extraction["source_records"][0]["text"] += " altered"
    inputs[2].append(extraction)
    out = proposal(inputs)
    assert not out["assignment_changes"]
    assert reasons(out) == {"invalid_evidence"}
