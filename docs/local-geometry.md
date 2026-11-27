# Local embedding geometry inspection

`pilon.loop.geometry.analyze_geometry(candidate, records, max_landmarks=128)` is a
pure, deterministic, standard-library diagnostic for explicitly supplied vectors.
It makes no embedding, network, model, or paid calls. It does not change extraction
routing, candidate status, evidence, product values, or publication decisions.
An integration can attach the returned dictionary to a report for inspection.

```python
from pilon.loop.geometry import analyze_geometry

contract = {
    "model": "synthetic-directions@1",
    "dimensions": 2,
    "preprocessing": "none",
}
candidate = {
    "key": "example-intent",
    "embedding": [1.0, 0.0],
    "embedding_contract": contract,
}
records = [
    {"id": "east", "embedding": [1.0, 0.0], "embedding_contract": contract},
    {"id": "near-east", "embedding": [10.0, 1.0], "embedding_contract": contract},
    {"id": "north", "embedding": [0.0, 1.0], "embedding_contract": contract},
    {"id": "near-north", "embedding": [1.0, 10.0], "embedding_contract": contract},
]
diagnostic = analyze_geometry(candidate, records)
assert diagnostic["status"] == "available"
# At radius 0.1, this synthetic sample has two equally sized components.
at_radius = next(t for t in diagnostic["thresholds"] if t["radius"] == 0.1)
assert at_radius["component_count"] == 2
assert at_radius["component_entropy_bits"] == 1.0
```

## Input and model contract

`candidate` is a mapping; `records` is a **finite iterable** of record mappings.
Only `candidate.key`, record `id`, `embedding`, and `embedding_contract` are used.
Record IDs must be nonempty strings. Roles, products, source text, demand volume,
and proposed facts are not interpreted or weighted.

Every embedding must have an explicit `embedding_contract` JSON object with:

- `model`: a nonempty model identity string. Include a revision in the identity or
  in an additional field when revisions can differ.
- `dimensions`: an integer from 1 through 8192, excluding booleans.
- Optional fields such as `revision`, `preprocessing`, `pooling`, or `task`. Every
  field participates in exact canonical JSON matching with the candidate contract.
  Object key order is irrelevant; missing fields, value types, and array order
  matter. Contract values must be finite JSON values with string object keys.

Contract matching checks declarations. It cannot prove the vectors actually came
from that model, that a model name identifies an immutable version, or that an
asymmetric query/document encoder produces comparable vectors. Callers must supply
an accurate shared comparison contract; dimensions alone are insufficient.

Vectors must be lists or tuples of finite Python numbers (`int`/`float`, excluding
booleans), with exactly the declared dimensionality. Zero vectors have undefined
cosine distance and are excluded. Scaling before normalization handles large and
subnormal finite numbers without overflowing the norm. Numeric strings, non-finite
values, and oversized dimensions are rejected for this diagnostic.

Distinct IDs with identical directions remain distinct observations and merge at
radius zero. They therefore affect component-size weights. Repeated occurrences
of the **same ID** are all excluded as ambiguous, even if their vectors agree;
the caller can deduplicate upstream when appropriate. No input-order winner is
chosen. Invalid or missing IDs are counted together with `id: null` because no
trustworthy identity is available.

## Availability and sample scope

`status` is `available` when the candidate and at least one record have usable,
compatible, nonzero embeddings. Otherwise it is `not_available`:

- An unusable candidate produces `reason: "candidate_<validation_reason>"`.
  Record vectors are not inspected; `scope.uninspected_record_ids` identifies
  them, and `eligible_record_count` is `null` rather than an inferred zero.
- A usable candidate with no usable record produces
  `reason: "no_compatible_record_embeddings"`.
- Unavailable results have empty `points` and `thresholds`, and `null`
  `representative`, `neighborhood`, `persistence`, and `threshold_diagnostics`.

Validation reasons include `missing_embedding`, `missing_embedding_contract`,
`invalid_embedding_contract`, `embedding_contract_mismatch`, `invalid_vector`,
`dimension_mismatch`, `dimension_limit_exceeded`, `non_finite_vector`, and
`zero_vector`. A non-mapping candidate or a non-positive/non-integer
`max_landmarks` is a caller error and raises `ValueError`.

The default landmark limit is 128; requests above 256 are capped at 256.
All uniquely identified records are validated before sampling. Eligible records
are ranked by SHA-256 of their UTF-8 ID (using `surrogatepass` for unusual Python
strings), then by ID; the smallest hashes are retained. Selection does not depend
on the target vector, input order, Python's randomized hash, or a random seed.
The final point order is lexical ID order. Changes to IDs or to the eligible pool
can change the sample; permutations of the same input do not.

`scope` records input and eligible counts, all identifiable input IDs, selected
`landmark_ids`, `unsampled_record_ids`, and `excluded_records` with reasons and
occurrence counts. `sampled` means some valid compatible records were omitted by
the landmark limit. Requested/effective/hard limits and the dimension limit are
included under `scope.sampling`. Every geometric point appears in `points` with
its original record ID. No record text or raw vector is copied into the report.

These are neighborhoods **within the landmark sample**, not guaranteed nearest
neighbors in the whole corpus. The candidate is only a query: it is not a vertex,
cannot bridge components, and cannot become the representative medoid. Missing,
invalid, incompatible, unsampled, or distant records are never evidence of absence.
An unresolved candidate survives regardless of geometry availability.

## Distances, neighbors, and representative

Cosine dissimilarity is `d(a,b) = 1 - dot(a/||a||, b/||b||)`, clamped to `[0,2]`
for floating-point roundoff. It need not satisfy the triangle inequality. No
calibrated probability, semantic equivalence, or factual verification follows from
a distance. Normalized-identical vectors have exactly zero distance.

`neighborhood.target_neighbors` lists the closest `min(10, L)` sampled records.
Each point also lists its closest `min(10, L-1)` other sampled records in
`points[].neighbors`. These are directed kNN lists with distance then ID ordering.
The complete distance graph, rather than a truncated kNN graph, drives persistence.

The `representative` is the observed landmark minimizing the sum of distances to
all `L` landmarks, with lexical ID tie-breaking. Its `mean_distance_to_landmarks`
divides that sum by `L`, including the zero self-distance. It is not a centroid or
a newly invented vector. Every point reports both `distance_to_target` and
`distance_to_representative`; the representative also reports its target distance.
A global medoid can obscure multiple groups and is not their semantic definition.

## Zero-dimensional persistence and radius diagnostics

For radius `r`, consider the undirected graph on all landmarks with edges where
`d <= r`. Kruskal's minimum spanning tree (MST) records exactly the merge scales
of this graph's connected components. This is zero-dimensional graph persistence;
it computes no holes, higher-dimensional topology, density modes, or semantic
classes. Its component calculation does not require a triangle-inequality metric.

All vertices are born at radius zero. `persistence.merges` contains the `L-1` MST
edges, their original endpoint IDs, merge radius, surviving/absorbed component
IDs, and component count after each merge. At equal distances the endpoint IDs
break ties. The smallest original ID survives each union; this is deterministic
bookkeeping, not a stronger or more important observation.

`persistence.bars` includes one bar per landmark. Each absorbed component dies at
its merge radius. The one surviving bar has `essential: true` and `death: null`
instead of a non-JSON infinity. Duplicate vectors produce zero-length bars.
Equal-scale merges are simultaneous for threshold results, although the merge
list shows a deterministic sequential ordering.

`thresholds` evaluates fixed radii `0, .05, .1, .2, .5, 1, 1.5, 2`, every distinct
MST merge scale, and (when present) the midpoint of the largest gap between
consecutive distinct merge scales. Each row reports the exact sampled connected
components, original member IDs, sizes, and:

- `component_entropy_bits`: `H = -sum(p_i * log2(p_i))`, where
  `p_i = size(component_i) / L`.
- `normalized_component_entropy`: `H / log2(L)`, or zero for `L=1`.
  The maximum is one when all landmarks are separate singleton components.
- `effective_component_count`: `2**H`, between one and `L`.

These values describe the **distribution of sampled records across connected
components**. Calling components "modes" is only a geometric proxy: entropy is
not uncertainty about a fact, a value distribution, an accuracy estimate, a
posterior probability, or a count of established semantic or density modes.
Duplicates, sampling, model choice, and radii can substantially change it.

`threshold_diagnostics` identifies the radius at which all sampled landmarks
connect, the zero-radius component count, and the largest merge-scale gap with
its midpoint. The gap is absent when fewer than two distinct merge scales exist.
Equal gaps choose the earliest interval. No gap before the first merge or after
the last merge is invented. Fixed radii and gap midpoints are inspection aids;
they are neither learned decision rules nor calibrated acceptance thresholds.

## Cost and comparison with retrieval

Let `N` be the input record count, `D <= 8192` the supplied dimension, and
`L <= 256` the selected landmark count. Input enumeration and validation still
scale with `N`: roughly `O(N*D + N*log(N))`, including sorting the ID ledger.
All input row references and the ID/reason ledger use `O(N)` additional space.
The sample retains at most `L` normalized vectors (plus a current working vector),
using `O(L*D)` space. Infinite iterables are not supported; the landmark cap does
not bound input loading, metadata size, or validation of an arbitrarily large feed.

Geometry evaluates exactly `L` target distances and `L*(L-1)/2` pairwise distances
(at most 32,640 pairs). The matrix/MST work is
`O(L*L*D + L*L*log(L))`, with `O(L*L)` matrix/edge space. Threshold membership
output also uses `O(L*L)` space, at no more than `L+8` radii. Counters in `metrics`
expose actual distance work; the diagnostic includes no elapsed-time fields, so
identical inputs produce identical reports. The cap is a complexity bound, not
a latency guarantee; large dimensions can still be expensive in pure Python.

Simple cosine retrieval needs only target-to-record distances and a top-k ranking;
within the same sample that requires `O(L*D + L*log(L))` work and is the baseline
returned in `neighborhood.target_neighbors`. Full-corpus retrieval can find useful
records absent from this sample. The extra pairwise work here adds an inspectable
view of redundancy, separation, and threshold sensitivity. It does **not** establish
that persistence/TDA improves retrieval, extraction, recall, accuracy, or cost.
Such claims require a separate labeled benchmark against simple retrieval, with
the same corpus, model, and budget. Neither approach alone verifies a source fact.

The focused synthetic tests cover known groups, independent complete-graph
connectivity, contracts, duplicates, zero/non-finite/extreme vectors, deterministic
permutations, immutable inputs, singleton behavior, and the hard work bound:

```text
python -m pytest -q tests/test_loop_geometry.py
```
