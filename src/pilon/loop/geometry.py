"""Bounded, deterministic inspection of explicitly supplied embedding vectors.

This module does not retrieve evidence, infer values, or control extraction.
Its component filtration is zero-dimensional graph persistence, computed by MST.
"""

from collections import Counter
from collections.abc import Mapping
from hashlib import sha256
from heapq import nsmallest
import json
import math


MAX_LANDMARKS = 256
MAX_DIMENSIONS = 8192
NEIGHBORS = 10
REFERENCE_RADII = (0.0, 0.05, 0.1, 0.2, 0.5, 1.0, 1.5, 2.0)

_LIMITATIONS = (
    "Local inspection only: distances do not verify facts or assign product values.",
    "Similarity, component sizes and entropy are not calibrated probabilities.",
    "Excluded, unsampled or distant records are not evidence of absence; extraction is unchanged.",
    "Results describe only the supplied compatible landmark sample, not corpus-wide recall.",
    "Connected components are geometric mode proxies, not established semantic or density modes.",
    "No accuracy improvement over simple retrieval has been established by this diagnostic.",
)


def _json_value(value):
    """Restrict contracts to finite JSON values, including string object keys."""
    if type(value) in (str, int, bool, type(None)):
        return True
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is list:
        return all(_json_value(item) for item in value)
    if type(value) is dict:
        return all(type(key) is str and _json_value(item) for key, item in value.items())
    return False


def _contract(value):
    if value is None:
        return None, "missing_embedding_contract"
    if not isinstance(value, dict):
        return None, "invalid_embedding_contract"
    if not isinstance(value.get("model"), str) or not value["model"].strip():
        return None, "invalid_embedding_contract"
    dimensions = value.get("dimensions")
    if type(dimensions) is not int or dimensions < 1:
        return None, "invalid_embedding_contract"
    if dimensions > MAX_DIMENSIONS:
        return None, "dimension_limit_exceeded"
    try:
        if not _json_value(value):
            return None, "invalid_embedding_contract"
        return json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":")), None
    except (TypeError, ValueError, RecursionError):
        return None, "invalid_embedding_contract"


def _embedding(row, expected_contract=None):
    raw = row.get("embedding")
    if raw is None:
        return None, None, "missing_embedding"
    contract, reason = _contract(row.get("embedding_contract"))
    if reason:
        return None, None, reason
    if expected_contract is not None and contract != expected_contract:
        return None, contract, "embedding_contract_mismatch"
    if not isinstance(raw, (list, tuple)):
        return None, contract, "invalid_vector"
    if len(raw) != row["embedding_contract"]["dimensions"]:
        return None, contract, "dimension_mismatch"
    vector = []
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return None, contract, "invalid_vector"
        try:
            number = float(item)
        except (ValueError, OverflowError):
            return None, contract, "non_finite_vector"
        if not math.isfinite(number):
            return None, contract, "non_finite_vector"
        vector.append(number)
    scale = max(abs(number) for number in vector)
    if scale == 0:
        return None, contract, "zero_vector"
    # Scaling first avoids overflow for huge finite inputs and underflow for tiny ones.
    scaled = [number / scale for number in vector]
    norm = math.sqrt(math.fsum(number * number for number in scaled))
    return tuple(number / norm for number in scaled), contract, None


def _cosine_distance(left, right):
    if left == right:
        return 0.0
    similarity = math.fsum(a * b for a, b in zip(left, right))
    return max(0.0, min(2.0, 1.0 - similarity))


def _record_id(row):
    value = row.get("id") if isinstance(row, Mapping) else None
    return value if isinstance(value, str) and value.strip() else None


class _Components:
    def __init__(self, size):
        self.parents = list(range(size))

    def root(self, node):
        while self.parents[node] != node:
            self.parents[node] = self.parents[self.parents[node]]
            node = self.parents[node]
        return node

    def merge(self, left, right):
        left, right = sorted((self.root(left), self.root(right)))
        if left == right:
            return None
        # Indices follow sorted record IDs, so component identities are reproducible.
        self.parents[right] = left
        return left, right


def _mst(distances):
    size = len(distances)
    edges = sorted((distances[left][right], left, right)
                   for left in range(size) for right in range(left + 1, size))
    components = _Components(size)
    tree = []
    for radius, left, right in edges:
        if components.merge(left, right) is not None:
            tree.append((radius, left, right))
            if len(tree) == size - 1:
                break
    return tree


def _persistence(ids, tree):
    components = _Components(len(ids))
    deaths = {point_id: None for point_id in ids}
    merges = []
    for radius, left, right in tree:
        survivor, absorbed = components.merge(left, right)
        deaths[ids[absorbed]] = radius
        merges.append({
            "left_id": ids[left], "right_id": ids[right], "radius": radius,
            "surviving_component_id": ids[survivor], "merged_component_id": ids[absorbed],
            "components_after": len(ids) - len(merges) - 1,
        })
    return {
        "method": "zero_dimensional_mst",
        "birth_radius": 0.0,
        "merges": merges,
        "bars": [{"component_id": point_id, "birth": 0.0, "death": deaths[point_id],
                  "essential": deaths[point_id] is None} for point_id in ids],
        "essential_death_encoding": "null denotes the one component that persists",
    }


def _largest_gap(tree):
    scales = sorted({radius for radius, _, _ in tree})
    if len(scales) < 2:
        return None
    lower, upper = max(zip(scales, scales[1:]), key=lambda pair: pair[1] - pair[0])
    return {"lower": lower, "upper": upper, "width": upper - lower,
            "midpoint_radius": lower + (upper - lower) / 2}


def _thresholds(ids, tree, gap):
    radii = set(REFERENCE_RADII)
    radii.update(radius for radius, _, _ in tree)
    if gap:
        radii.add(gap["midpoint_radius"])
    components = _Components(len(ids))
    position = 0
    thresholds = []
    for radius in sorted(radii):
        while position < len(tree) and tree[position][0] <= radius:
            _, left, right = tree[position]
            components.merge(left, right)
            position += 1
        groups = {}
        for index, point_id in enumerate(ids):
            groups.setdefault(components.root(index), []).append(point_id)
        members = list(groups.values())
        proportions = [len(group) / len(ids) for group in members]
        entropy = -math.fsum(p * math.log2(p) for p in proportions)
        thresholds.append({
            "radius": radius,
            "component_count": len(members),
            "components": [{"id": group[0], "size": len(group), "member_ids": group}
                           for group in members],
            "component_entropy_bits": max(0.0, entropy),
            "normalized_component_entropy": min(1.0, max(0.0, entropy / math.log2(len(ids))))
            if len(ids) > 1 else 0.0,
            "effective_component_count": min(float(len(ids)), 2.0 ** entropy),
        })
    return thresholds


def analyze_geometry(candidate, records, max_landmarks=128) -> dict:
    """Inspect finite supplied records without mutation, external calls or routing.

    Contracts require ``model`` and ``dimensions``; all contract fields must match.
    IDs must be nonempty strings. Repeated IDs are ambiguous and excluded in full;
    distinct IDs with identical nonzero vectors remain separate observations.
    See docs/local-geometry.md for the report schema, limits and interpretation.
    """
    if not isinstance(candidate, Mapping):
        raise ValueError("candidate must be a mapping")
    if type(max_landmarks) is not int or max_landmarks < 1:
        raise ValueError("max_landmarks must be a positive integer")
    limit = min(max_landmarks, MAX_LANDMARKS)
    rows = list(records)
    counts = Counter(_record_id(row) for row in rows)
    unidentified = counts.pop(None, 0)
    excluded = [{"id": point_id, "reason": "duplicate_id", "occurrences": count}
                for point_id, count in sorted(counts.items()) if count > 1]
    if unidentified:
        excluded.append({"id": None, "reason": "missing_or_invalid_id", "occurrences": unidentified})
    scope = {
        "input_record_count": len(rows),
        "identified_record_ids": sorted(counts),
        "unidentified_record_count": unidentified,
        "eligible_record_count": None,
        "landmark_count": 0,
        "landmark_ids": [],
        "unsampled_record_ids": [],
        "uninspected_record_ids": sorted(point_id for point_id in counts if counts[point_id] == 1),
        "excluded_records": excluded,
        "sampled": False,
        "candidate_in_topology": False,
        "sampling": {"method": "smallest_sha256_record_id_then_id",
                     "requested_max_landmarks": max_landmarks,
                     "effective_max_landmarks": limit,
                     "hard_max_landmarks": MAX_LANDMARKS,
                     "max_dimensions": MAX_DIMENSIONS},
    }
    report = {
        "schema_version": 1,
        "candidate_key": candidate.get("key") if isinstance(candidate.get("key"), str) else None,
        "status": "not_available",
        "reason": None,
        "purpose": "local_inspection_only",
        "embedding_contract": None,
        "distance_metric": "cosine_distance",
        "scope": scope,
        "points": [],
        "representative": None,
        "neighborhood": None,
        "persistence": None,
        "thresholds": [],
        "threshold_diagnostics": None,
        "definitions": {
            "distance": "1 - dot(unit(a), unit(b)), clamped to [0, 2]; zero vectors are undefined",
            "medoid": "observed landmark minimizing sum of distances to all landmarks; ID breaks ties",
            "components": "landmark graph with an edge whenever cosine distance <= radius",
            "component_entropy_bits": "H = -sum(p_i * log2(p_i)), p_i = component size / landmark count",
            "normalized_component_entropy": "H / log2(landmark count), or 0 for one landmark",
            "effective_component_count": "2 ** H; a size-distribution diagnostic, not a semantic mode count",
        },
        "metrics": {"record_embeddings_inspected": 0, "target_distance_evaluations": 0,
                    "pairwise_distance_evaluations": 0, "mst_edges": 0,
                    "embedding_calls": 0, "external_calls": 0},
        "limitations": list(_LIMITATIONS),
    }
    target, contract, reason = _embedding(candidate)
    if reason:
        report["reason"] = "candidate_" + reason
        return report
    report["embedding_contract"] = json.loads(contract)
    eligible_ids = []

    def eligible_points():
        for row in rows:
            point_id = _record_id(row)
            if point_id is None or counts[point_id] != 1:
                continue
            report["metrics"]["record_embeddings_inspected"] += 1
            vector, _, issue = _embedding(row, contract)
            if issue:
                excluded.append({"id": point_id, "reason": issue, "occurrences": 1})
                continue
            eligible_ids.append(point_id)
            digest = sha256(point_id.encode("utf-8", errors="surrogatepass")).digest()
            yield digest, point_id, vector

    # nsmallest consumes all eligible points but retains at most limit vectors.
    selected = sorted(nsmallest(limit, eligible_points()), key=lambda point: point[1])
    ids = [point_id for _, point_id, _ in selected]
    selected_ids = set(ids)
    scope.update({"eligible_record_count": len(eligible_ids), "landmark_count": len(ids),
                  "landmark_ids": ids, "uninspected_record_ids": [],
                  "unsampled_record_ids": sorted(set(eligible_ids) - selected_ids),
                  "sampled": len(eligible_ids) > len(ids)})
    excluded.sort(key=lambda item: (item["id"] is not None, item["id"] or "", item["reason"]))
    if not ids:
        report["reason"] = "no_compatible_record_embeddings"
        return report

    vectors = [vector for _, _, vector in selected]
    size = len(ids)
    distances = [[0.0] * size for _ in ids]
    target_distances = [_cosine_distance(target, vector) for vector in vectors]
    for left in range(size):
        for right in range(left + 1, size):
            distance = _cosine_distance(vectors[left], vectors[right])
            distances[left][right] = distances[right][left] = distance
    totals = [math.fsum(row) for row in distances]
    medoid = min(range(size), key=lambda index: (totals[index], ids[index]))
    graph_k, target_k = min(NEIGHBORS, size - 1), min(NEIGHBORS, size)
    points = []
    for index, point_id in enumerate(ids):
        neighbors = sorted((distances[index][other], ids[other])
                           for other in range(size) if other != index)[:graph_k]
        points.append({"id": point_id, "distance_to_target": target_distances[index],
                       "distance_to_representative": distances[index][medoid],
                       "neighbors": [{"id": other, "distance": distance} for distance, other in neighbors]})
    target_neighbors = sorted(zip(target_distances, ids))[:target_k]
    tree = _mst(distances)
    gap = _largest_gap(tree)
    thresholds = _thresholds(ids, tree, gap)
    report.update({
        "status": "available",
        "points": points,
        "representative": {"id": ids[medoid], "mean_distance_to_landmarks": totals[medoid] / size,
                           "distance_to_target": target_distances[medoid]},
        "neighborhood": {"target_k": target_k, "graph_k": graph_k,
                         "graph_kind": "directed_knn", "scope": "sampled_landmarks_only",
                         "target_neighbors": [{"id": point_id, "distance": distance}
                                              for distance, point_id in target_neighbors]},
        "persistence": _persistence(ids, tree),
        "thresholds": thresholds,
        "threshold_diagnostics": {
            "reference_radii": list(REFERENCE_RADII),
            "includes_all_merge_scales": True,
            "zero_radius_component_count": thresholds[0]["component_count"],
            "fully_connected_radius": tree[-1][0] if tree else 0.0,
            "largest_merge_gap": gap,
            "gap_interpretation": "gap between consecutive distinct MST merge scales; midpoint is exploratory, not calibrated",
        },
    })
    report["metrics"].update({"target_distance_evaluations": size,
                              "pairwise_distance_evaluations": size * (size - 1) // 2,
                              "mst_edges": len(tree)})
    return report
