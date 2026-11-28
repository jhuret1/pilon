from copy import deepcopy
from hashlib import sha256
import json
import math
import random

import pytest

from pilon.loop import geometry
from pilon.loop.geometry import analyze_geometry


CONTRACT = {"model": "synthetic-directions@1", "dimensions": 2, "preprocessing": "none"}


def candidate(vector=(1.0, 0.0)):
    return {"key": "synthetic-intent", "embedding": list(vector),
            "embedding_contract": deepcopy(CONTRACT), "status": "needs_extraction"}


def record(point_id, vector=(1.0, 0.0)):
    return {"id": point_id, "embedding": list(vector), "embedding_contract": deepcopy(CONTRACT)}


def groups():
    return [record("a0", (1, 0)), record("a1", (10, 1)),
            record("b0", (0, 1)), record("b1", (1, 10))]


def threshold_at(report, radius):
    return next(item for item in report["thresholds"] if item["radius"] == radius)


def test_known_two_groups_neighborhood_medoid_and_persistence():
    result = analyze_geometry(candidate(), groups())
    assert result["status"] == "available"
    assert result["scope"]["landmark_ids"] == ["a0", "a1", "b0", "b1"]
    assert not result["scope"]["candidate_in_topology"]
    assert [item["id"] for item in result["neighborhood"]["target_neighbors"]] == ["a0", "a1", "b1", "b0"]
    assert result["representative"]["id"] == "a1"
    points = {point["id"]: point for point in result["points"]}
    within = 1 - 10 / math.sqrt(101)
    between = 1 - 20 / 101
    assert points["a0"]["distance_to_target"] == 0
    assert points["b0"]["distance_to_target"] == 1
    assert points["a0"]["distance_to_representative"] == pytest.approx(within)
    assert points["b1"]["distance_to_representative"] == pytest.approx(between)
    assert points["a1"]["distance_to_representative"] == 0
    assert [point["neighbors"][0]["id"] for point in result["points"]] == ["a1", "a0", "b1", "b0"]
    assert [merge["radius"] for merge in result["persistence"]["merges"]] == pytest.approx([within, within, between])
    assert [merge["components_after"] for merge in result["persistence"]["merges"]] == [3, 2, 1]
    bars = result["persistence"]["bars"]
    assert len(bars) == 4
    assert [bar["component_id"] for bar in bars if bar["essential"]] == ["a0"]
    assert next(bar for bar in bars if bar["essential"])["death"] is None
    assert sorted(bar["death"] for bar in bars if not bar["essential"]) == pytest.approx([within, within, between])
    middle = threshold_at(result, 0.1)
    assert middle["component_count"] == 2
    assert [component["member_ids"] for component in middle["components"]] == [["a0", "a1"], ["b0", "b1"]]
    assert middle["component_entropy_bits"] == 1
    assert middle["normalized_component_entropy"] == 0.5
    assert middle["effective_component_count"] == 2
    assert threshold_at(result, 0)["component_entropy_bits"] == 2
    assert threshold_at(result, 1)["component_entropy_bits"] == 0
    assert result["threshold_diagnostics"]["fully_connected_radius"] == pytest.approx(between)
    gap = result["threshold_diagnostics"]["largest_merge_gap"]
    assert gap["lower"] == pytest.approx(within)
    assert gap["upper"] == pytest.approx(between)
    assert threshold_at(result, gap["midpoint_radius"])["component_count"] == 2
    # Equal-scale merges are simultaneous in the radius filtration.
    assert threshold_at(result, result["persistence"]["merges"][0]["radius"])["component_count"] == 2


@pytest.mark.parametrize("changed", [
    {"model": "other-model@1"}, {"dimensions": 3}, {"preprocessing": "different"},
    {"revision": "new"}, {"model": "synthetic-directions@2"},
])
def test_contract_mismatches_are_visible_and_never_compared(changed):
    bad = record("different")
    bad["embedding_contract"].update(changed)
    result = analyze_geometry(candidate(), [bad, record("compatible")])
    assert result["scope"]["landmark_ids"] == ["compatible"]
    assert result["scope"]["excluded_records"] == [
        {"id": "different", "reason": "embedding_contract_mismatch", "occurrences": 1}]
    assert result["metrics"]["pairwise_distance_evaluations"] == 0


@pytest.mark.parametrize("contract,reason", [
    (None, "missing_embedding_contract"), ("model@1", "invalid_embedding_contract"),
    ({}, "invalid_embedding_contract"), ({"model": " ", "dimensions": 2}, "invalid_embedding_contract"),
    ({"model": "m", "dimensions": True}, "invalid_embedding_contract"),
    ({"model": "m", "dimensions": 2.0}, "invalid_embedding_contract"),
    ({"model": "m", "dimensions": 0}, "invalid_embedding_contract"),
    ({"model": "m", "dimensions": 8193}, "dimension_limit_exceeded"),
    ({"model": "m", "dimensions": 2, "config": float("nan")}, "invalid_embedding_contract"),
    ({"model": "m", "dimensions": 2, "config": {1: "value"}}, "invalid_embedding_contract"),
])
def test_invalid_or_missing_contract_has_explicit_status(contract, reason):
    target = candidate()
    target["embedding_contract"] = contract
    result = analyze_geometry(target, [record("r")])
    assert result["status"] == "not_available"
    assert result["reason"] == "candidate_" + reason
    assert result["scope"]["uninspected_record_ids"] == ["r"]
    assert result["scope"]["eligible_record_count"] is None
    assert result["metrics"]["record_embeddings_inspected"] == 0
    assert result["points"] == []
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("vector,reason", [
    (None, "missing_embedding"), ([], "dimension_mismatch"), ([1], "dimension_mismatch"),
    ([1, 2, 3], "dimension_mismatch"), ("10", "invalid_vector"),
    ([True, 0], "invalid_vector"), (["1", 0], "invalid_vector"),
    ([float("nan"), 0], "non_finite_vector"), ([float("inf"), 0], "non_finite_vector"),
    ([-float("inf"), 0], "non_finite_vector"), ([10 ** 400, 0], "non_finite_vector"),
    ([0, -0.0], "zero_vector"),
])
def test_invalid_vectors_are_reported_without_nan_or_distance_computation(vector, reason):
    bad = record("bad")
    bad["embedding"] = vector
    result = analyze_geometry(candidate(), [bad])
    assert result["status"] == "not_available"
    assert result["reason"] == "no_compatible_record_embeddings"
    assert result["scope"]["excluded_records"] == [{"id": "bad", "reason": reason, "occurrences": 1}]
    assert result["metrics"]["target_distance_evaluations"] == 0
    assert result["persistence"] is None
    json.dumps(result, allow_nan=False)
    target = candidate()
    target["embedding"] = vector
    result = analyze_geometry(target, [record("good")])
    assert result["reason"] == "candidate_" + reason
    assert result["status"] == "not_available"


def test_no_embeddings_is_not_available_and_does_not_change_candidate_status():
    target = {"key": "unresolved", "status": "needs_extraction"}
    assert analyze_geometry(target, [])["status"] == "not_available"
    assert target["status"] == "needs_extraction"
    assert analyze_geometry(candidate(), [])["reason"] == "no_compatible_record_embeddings"
    result = analyze_geometry(candidate(), [{"id": "no-vector"}])
    assert result["scope"]["excluded_records"][0]["reason"] == "missing_embedding"
    row = record("no-contract")
    del row["embedding_contract"]
    assert analyze_geometry(candidate(), [row])["scope"]["excluded_records"][0]["reason"] == "missing_embedding_contract"


def test_duplicate_vectors_are_retained_zero_vectors_and_repeated_ids_are_visible():
    rows = [record("a", (1, 1)), record("b", (2, 2)), record("zero", (0, 0)),
            record("repeat", (1, 0)), record("repeat", (0, 1)),
            record("same-id"), record("same-id"), {"embedding": [1, 0]}]
    result = analyze_geometry(candidate(), rows)
    assert result["scope"]["landmark_ids"] == ["a", "b"]
    assert result["scope"]["unidentified_record_count"] == 1
    assert {item["id"]: item["reason"] for item in result["scope"]["excluded_records"]} == {
        None: "missing_or_invalid_id", "repeat": "duplicate_id", "same-id": "duplicate_id", "zero": "zero_vector"}
    assert result["scope"]["input_record_count"] == 8
    assert result["persistence"]["merges"][0]["radius"] == 0
    assert threshold_at(result, 0)["component_count"] == 1
    assert threshold_at(result, 0)["component_entropy_bits"] == 0
    assert result["representative"]["id"] == "a"
    assert all(point["distance_to_representative"] == 0 for point in result["points"])
    assert result["threshold_diagnostics"]["largest_merge_gap"] is None


def test_unequal_components_entropy_is_size_weighted():
    rows = [record("a"), record("b"), record("c"), record("d", (-1, 0))]
    result = analyze_geometry(candidate(), rows)
    at_zero = threshold_at(result, 0)
    expected = -0.75 * math.log2(0.75) - 0.25 * math.log2(0.25)
    assert at_zero["component_entropy_bits"] == pytest.approx(expected)
    assert at_zero["normalized_component_entropy"] == pytest.approx(expected / 2)
    assert at_zero["effective_component_count"] == pytest.approx(2 ** expected)
    assert at_zero["component_count"] == 2


def test_input_permutation_contract_key_order_and_iterators_are_deterministic():
    rows = [record(f"r-{i:03}", (1, i - 30)) for i in range(60)]
    rows += [record("duplicate", (1, 0)), record("duplicate", (0, 1)), record("zero", (0, 0)), {}]
    expected = analyze_geometry(candidate(), rows, max_landmarks=17)
    encoded = json.dumps(expected, allow_nan=False)
    rng = random.Random(42)
    for _ in range(8):
        rng.shuffle(rows)
        for row in rows:
            if "embedding_contract" in row:
                row["embedding_contract"] = dict(reversed(list(row["embedding_contract"].items())))
        result = analyze_geometry(candidate(), iter(rows), max_landmarks=17)
        assert json.dumps(result, allow_nan=False) == encoded
    expected_ids = sorted(sorted([f"r-{i:03}" for i in range(60)],
                                key=lambda item: (sha256(item.encode()).digest(), item))[:17])
    assert expected["scope"]["landmark_ids"] == expected_ids
    assert expected["scope"]["sampled"]
    assert len(expected["scope"]["unsampled_record_ids"]) == 43


@pytest.mark.parametrize("limit,expected_count", [(1, 1), (7, 7), (128, 128), (9999, 256)])
def test_pairwise_work_is_bounded_and_all_input_ids_are_accounted_for(monkeypatch, limit, expected_count):
    rows = [record(f"r-{i:04}", (1, i - 300)) for i in range(600)]
    calls = 0
    original = geometry._cosine_distance

    def measured(left, right):
        nonlocal calls
        calls += 1
        return original(left, right)

    monkeypatch.setattr(geometry, "_cosine_distance", measured)
    result = analyze_geometry(candidate(), rows, max_landmarks=limit)
    assert result["scope"]["landmark_count"] == expected_count
    assert result["scope"]["eligible_record_count"] == 600
    assert len(result["scope"]["identified_record_ids"]) == 600
    assert set(result["scope"]["landmark_ids"]) | set(result["scope"]["unsampled_record_ids"]) == {row["id"] for row in rows}
    assert calls == expected_count + expected_count * (expected_count - 1) // 2
    assert result["metrics"]["pairwise_distance_evaluations"] <= 32640
    assert result["metrics"]["mst_edges"] == expected_count - 1
    assert len(result["thresholds"]) <= expected_count + len(geometry.REFERENCE_RADII)
    assert len(result["neighborhood"]["target_neighbors"]) == min(10, expected_count)
    assert all(len(point["neighbors"]) == min(10, expected_count - 1) for point in result["points"])
    assert result["metrics"]["embedding_calls"] == result["metrics"]["external_calls"] == 0
    json.dumps(result, allow_nan=False)


def test_default_landmark_limit():
    rows = [record(f"r-{i}", (1, i)) for i in range(200)]
    result = analyze_geometry(candidate(), rows)
    assert result["scope"]["landmark_count"] == 128
    assert result["scope"]["sampling"]["requested_max_landmarks"] == 128


@pytest.mark.parametrize("limit", [0, -1, True, False, 1.5, "128", None])
def test_invalid_limit_is_a_caller_error(limit):
    with pytest.raises(ValueError, match="positive integer"):
        analyze_geometry(candidate(), [], max_landmarks=limit)


def test_extreme_finite_vectors_and_antipodal_distance():
    target = candidate((1e308, 1e308))
    rows = [record("huge", (1e308, 1e308)), record("tiny", (5e-324, 5e-324)),
            record("opposite", (-1e308, -1e308))]
    result = analyze_geometry(target, rows)
    assert result["status"] == "available"
    points = {point["id"]: point for point in result["points"]}
    assert points["huge"]["distance_to_target"] == points["tiny"]["distance_to_target"] == 0
    assert points["opposite"]["distance_to_target"] == pytest.approx(2)
    for point in points.values():
        assert 0 <= point["distance_to_target"] <= 2
        assert 0 <= point["distance_to_representative"] <= 2
    json.dumps(result, allow_nan=False)


def test_singleton_has_one_essential_component_and_observed_medoid():
    result = analyze_geometry(candidate(), [record("only", (0, 1))])
    assert result["representative"]["id"] == "only"
    assert result["representative"]["mean_distance_to_landmarks"] == 0
    assert result["representative"]["distance_to_target"] == 1
    assert result["points"][0]["neighbors"] == []
    assert result["persistence"]["merges"] == []
    assert result["persistence"]["bars"] == [{"component_id": "only", "birth": 0,
                                              "death": None, "essential": True}]
    assert all(item["component_count"] == 1 and item["normalized_component_entropy"] == 0
               and item["effective_component_count"] == 1 for item in result["thresholds"])


def test_mst_threshold_components_match_independent_complete_graph_traversal():
    rng = random.Random(13)
    rows = [record(f"point-{i:02}", (rng.uniform(-1, 1), rng.uniform(-1, 1))) for i in range(15)]
    result = analyze_geometry(candidate(), rows)
    vectors = {row["id"]: row["embedding"] for row in rows}

    def distance(first, second):
        left, right = vectors[first], vectors[second]
        return 1 - sum(a * b for a, b in zip(left, right)) / (math.hypot(*left) * math.hypot(*right))

    counts = []
    for entry in result["thresholds"]:
        remaining = set(vectors)
        expected = []
        while remaining:
            start = min(remaining)
            remaining.remove(start)
            group, frontier = {start}, [start]
            while frontier:
                point = frontier.pop()
                neighbors = {other for other in remaining if distance(point, other) <= entry["radius"] + 1e-12}
                remaining -= neighbors
                group |= neighbors
                frontier.extend(neighbors)
            expected.append(sorted(group))
        assert sorted(component["member_ids"] for component in entry["components"]) == sorted(expected)
        counts.append(entry["component_count"])
    assert counts == sorted(counts, reverse=True)
    assert counts[-1] == 1


def test_inputs_and_returned_contract_are_independent_and_output_contains_no_source_text():
    target, rows = candidate(), groups()
    target["embedding_contract"]["configuration"] = {"revision": [1, 2]}
    for row in rows:
        row["embedding_contract"] = deepcopy(target["embedding_contract"])
        row["text"] = "Synthetic source text: never evidence from geometry."
        row["product_id"] = "synthetic-product"
    before = deepcopy((target, rows))
    result = analyze_geometry(target, rows)
    assert (target, rows) == before
    assert "Synthetic source text" not in json.dumps(result)
    assert not {"assignments", "evidence", "value", "probability", "routing"} & set(result)
    result["embedding_contract"]["configuration"]["revision"].append(3)
    assert (target, rows) == before
