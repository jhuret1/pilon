# Background loop: implementation contract

This iteration adds a local, reproducible background workflow while preserving the
existing `pilon discover` and `pilon demo` entry points. Online search continues to
serve only a published model snapshot. Benchmark never answers a customer query.

## Shared Python shapes

Sources retain the existing feed: `id`, `category`, `role` (`demand`, `external`,
`catalog`), `source`, `text`; catalog also has `product_id`; demand has `date` and
optional event `count`. Optional `asset_type` is `text`, `document`, or `image`.
An image requires an explicit extraction adapter; an image filename is not proof.

Model: existing `category`, `existing_facets`, `aliases`, observation window; optional
`version`, `facets` (list of `{key,label,definition,values}`), `assignments` (list of
`{fact_key,product_id,value,evidence}`). Unknown source fields must survive in stored
input snapshots. None of the pure stage functions mutates its inputs.

Candidate: `{key,label,definition,aliases,demand_events,demand_records,gap_type,status}`.
`gap_type`: `schema_gap`, `coverage_gap`, `retrieval_gap`, or `unresolved_intent`.
`status` initially `needs_extraction`. Demand evidence uses record_id/source/quote/
start/end. It is not product evidence. Optional `embedding` is an explicitly supplied
vector. A candidate must survive when there is no matching product source.

Extraction: `extract(candidate, records, model=None, *, top_k=50, exhaustive=False,
embedding_provider=None, extractor=None) -> dict` in `pilon.loop.extraction`.
Output includes `candidate_key`, `status`, `assignments`, `conflicts`, `unknown_products`,
`routing`, `metrics`. Assignment: `{product_id,value,evidence:[{record_id,source,quote,
start,end,asset_type}]}`. Source quotations must be checked against unchanged input
text. `routing` records selected/unselected/unsupported assets and selection reasons.
`metrics` distinguishes retrieval from extraction, counts and measured elapsed time;
no invented savings, recall or semantic-verification claim. A skipped asset is not
evidence of absence. Explicit negative values remain separate from missing evidence.
Optional vectors may route candidates; the default lexical adapter is labeled as such.
TDA/ANN improvements require an actual benchmark; do not claim they run by default.
When explicit vectors declare an `embedding_contract`, candidate and source must
declare the same model, dimension and other contract fields. The low-level Python
callback also accepts bare vectors for compatibility, labeled `unspecified_by_caller`;
their semantic-space compatibility cannot be verified. Use declared contracts in feeds.

Projection in `pilon.loop.projection`:
`build_projection(model, candidates, extractions) -> dict` with `base_hash`,
`projection_id`, `schema_changes`, `assignment_changes`, `blocked`, `projected_model`,
`summary`. Pure, deterministic, immutable. Only exact-source-supported assignments
may enter a proposed model; conflicts and unknowns remain visible. No live model is
changed. Local publication/rollback use separate explicit functions with atomic writes,
base-hash concurrency checks, persisted audit records and immutable snapshots. Agent
implementing projection documents its exact publish/rollback API for integration.

Main integration owns `pilon.loop.benchmark`, queue/store and worker orchestration,
CLI, package/version config, and end-to-end integration tests. Persistent jobs store
frozen model+source inputs. A worker runs benchmark → extraction → projection; it
never publishes automatically. SQLite leases/checkpoints permit restart without
recomputing completed stages. Subsequent snapshots can introduce new assets for
previously unresolved facts. No paid external requests run in tests or demonstrations.

UI adapter in `pilon.loop.report`: `render_loop(report) -> str` self-contained HTML.
Report fields: `schema_version`, `id`, `status`, `model`, `candidates`, `extractions`,
`projection`, `metrics`, `events`, `synthetic`. A UI HTTP adapter can remain read-only.
The projection is an actual before/after schema and assignment diff, not only a list
of product IDs. Every inferred or proposed result keeps its review status visible.

Implemented commands: `pilon loop demo`, `pilon loop enqueue --model ... --signals ...`,
`pilon loop work --once`, `pilon loop report JOB_ID --html ...`, `pilon loop serve`,
and explicit `pilon loop publish` / `pilon loop rollback` for a local model snapshot.

`loop watch` monitors local atomic exports; `loop revisit JOB_ID --signals ...`
reuses retained requests and adds immutable records. `--geometry` on enqueue/watch
enables a separate diagnostic checkpoint over supplied compatible vectors; it
does not change extraction decisions. See [local geometry](local-geometry.md).
