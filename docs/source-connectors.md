# Source connectors: requests in, product evidence out

PILON currently imports CSV, JSONL, stdin and Python iterables. There are no
built-in authenticated search, CRM, PIM or CMS provider connections in the verified
`07b3f3f` baseline. Source names below identify export origins, not installed
integrations. The [background-loop contract](background-loop-contract.md) defines
the new worker boundary; [Product plan](product-plan.md) defines acceptance gates.

## Two source streams, two responsibilities

| Stream | First useful export | Purpose and constraint |
| --- | --- | --- |
| Search demand | Query text, category, date, event count; later add filters, result IDs/count and serving model/index version. | Discover requested properties and prioritize by events. Search telemetry supports retrieval diagnosis; a query alone does not. |
| CRM/support feedback | Redacted customer question or explicit feature request, category and occurrence date; onsite reviews/forms use the same interface. | Preserve customer wording. Agent replies and copied transcripts are not separate demand events or authoritative product facts. |
| PIM/merchant product data | SKU/variant identity, category, labeled properties and revision. | First source for product assignments and a complete SKU denominator. Demand volume never substitutes for product evidence. |
| CMS/product pages | SKU-linked descriptions and labeled specifications, immutable page revision and URL/reference. | Add evidence absent from structured fields. Keep disagreements with the PIM visible; no implicit source-wins rule. |
| Product documents | SKU-linked manuals/spec sheets, revision, page/section and upstream-extracted text. | Use text imports first. PDF parsing/OCR is an optional adapter, not part of the standard-library core. |
| Product images | SKU-linked asset, content hash, revision and explicit extraction result. | Route as `asset_type: image`. Neither a filename nor caption alone proves a visual property; extraction requires an explicit adapter. |
| External feedback | Separately identified competitor or third-party observations. | Context/hypotheses only; excluded from local demand and product assignments. |

## Phased integration

| Phase | Deliverable | Status and exit condition |
| --- | --- | --- |
| 0: portable snapshots | Map search/support and PIM/CMS exports to CSV/JSONL; import with repeated `--signals` or a Python iterable. | File readers exist. Mapping a particular provider's export is operator work. Exit: one redacted real snapshot with traceable IDs, counts and complete declared inventory. |
| 1: scheduled materialization | Operator-owned export job produces an immutable snapshot; `loop watch` enqueues changed exports, and `loop work` processes them. | Local watcher, worker and checkpoint recovery are implemented and tested. `loop revisit` adds sources to retained demand. Provider schedulers and authenticated pollers remain integrations. |
| 2: incremental adapters | Implement the highest-volume search/support export first, then product revisions and deletions. Add serving telemetry for retrieval diagnosis. | Planned. Exit: paging, retry, rate limits, watermark replay, deletions and SKU mapping pass synthetic adapter fixtures before connection to authorized data. |
| 3: richer assets | Document text with page provenance, then explicit image/OCR or model extraction; benchmark optional semantic routing. | Planned adapters. Existing custom text extraction is reusable but is not built-in PDF/vision support. Exit: grounded outputs, visible unsupported assets and measured quality/cost improve on the lexical baseline. |
| 4: downstream publication | Export the approved local snapshot into the owner's indexing/merchandising pipeline. | Planned external integration; local publish/rollback alone do not update a storefront. Exit: serving version can be verified and rolled back. |

Choose a provider only after obtaining its actual export/API shape and an authorized
data owner. Do not make the core depend on a provider SDK or an external model.
Polling credentials and optional paid inference belong to explicit operator-managed
adapters, never to fixtures, saved source records or the default demonstration.

## Record contract

Use JSONL for nested metadata, annotations or vectors. CSV supports the basic flat
fields; its reader converts `count`, not arbitrary nested JSON cells. Existing
Discovery accepts Python iterables through `explore(model, records, ...)`.

| Field | Contract |
| --- | --- |
| `id` | Nonempty, namespaced record identity. Identical repeats count once; conflicting contents under the same ID are rejected. Include a revision in the ID when multiple immutable revisions must coexist. |
| `category`, `role`, `source`, `text` | Required nonempty strings; `role` is `demand`, `catalog` or `external`. `text` is the exact redacted/imported text used for evidence offsets. `source` is an origin label, never executable adapter selection. |
| `date`, `count` | Demand requires `date` as `YYYY-MM-DD`; `count` is a positive integer, default 1. Declare timezone/day boundaries in the export manifest. |
| `product_id` | Required on catalog records; canonical SKU/variant identity. Resolve joins upstream and preserve mapping provenance. Never infer identity from a similar title. |
| `asset_type` | Loop extension: `text`, `document` or `image`; ordinary feed text uses the text path. An image needs an explicit extraction adapter. |
| `extractions` | Existing optional annotations: `extraction_text`, `char_interval: {start_pos,end_pos}`, `attributes: {label,value}`. Quote must equal `text[start_pos:end_pos]`. |
| `intents` | Working-branch Benchmark accepts demand annotations with `label`, `start`, `end`, `quote`, optional `key`, `definition`, `aliases`. It verifies the source slice; semantic interpretation remains the annotator's responsibility. `intent_extractor` is a Python hook, not a connected model provider. |
| `outcome` | Working-branch heuristic input: `no_results`, `unsatisfied`, `unavailable_filter`. Preserve richer search telemetry separately; this label alone does not prove a retrieval defect. |
| Additional metadata | Proposed adapter fields such as `source_ref`, `source_record_id`, `revision`, `content_hash`, `observed_at`, `language`, `page`, `access_scope`, `redaction_version`. Preserve them in frozen loop inputs; preservation does not imply validation or automatic behavior. |

Example synthetic records that existing Discovery can import:

```jsonl
{"id":"search:q17:2026-11-01","category":"running-shoes","role":"demand","source":"search_export","date":"2026-11-01","count":12,"text":"room for my toes"}
{"id":"support:t42:request1","category":"running-shoes","role":"demand","source":"support_export","date":"2026-11-02","text":"Can I filter shoes by toe box?"}
{"id":"pim:SKU-01:r3","category":"running-shoes","role":"catalog","source":"pim_export","product_id":"SKU-01","text":"Width: standard\nToe box: wide","revision":"r3"}
```

These records need a matching category model and aliases to match indirect wording
in old Discovery. The model requires `category`, `existing_facets`, `window_start`,
`window_end`, and optional `aliases`. The loop contract adds optional `version`,
`facets: [{key,label,definition,values}]` and accepted
`assignments: [{fact_key,product_id,value,evidence}]`. Names alone are insufficient
to distinguish all coverage and retrieval gaps.

## Provenance and extraction boundary

Retain the imported text unchanged within a snapshot. Evidence uses `record_id`,
`source`, `quote`, `start`, `end` and, for loop product evidence, `asset_type`.
Offsets are half-open Unicode character positions, not byte or UTF-16 positions.
Redact and normalize before generating annotations; changing text invalidates spans.
Document quotes refer to a frozen text rendition; retain document hash and page
mapping. Image adapters must retain asset provenance and their evidence rendition;
an exact text slice validates that rendition, not what an image actually depicts.
Visual interpretation still needs adapter evaluation and review.

The contracted loop seam is
`extract(candidate, records, model=None, *, top_k=50, exhaustive=False, embedding_provider=None, extractor=None)`.
Its output separates assignments, conflicts, unknown products, routing and metrics.
Optional embeddings must be explicitly supplied; the default routing is lexical.
Evidence from `demand` or `external` records cannot become a product assignment.
No source selected, an unsupported image, and a supported explicit negative are
three different outcomes. Count selected assets separately from extraction calls.

Existing Discovery instead accepts `extract_specs=callable`, yielding
`Spec(label, value, start, end)` from source text, or the annotations above. That
interface does not by itself implement the new loop or fetch any external source.

## Incremental adapter contract (planned)

Adapters materialize records; they do not publish models. A future connector batch
should carry a manifest with adapter/version, category, source scope, export time,
window/timezone, snapshot/revision, input/output cursor, record count, distinct SKU
count, content digest, completeness and redaction policy. This manifest is a proposed
adapter contract, not a currently accepted CLI option.

- Fetch into staging, validate and durably persist the complete snapshot/job, then
  advance the checkpoint. Retry the same page/batch safely. Partial exports must be
  marked incomplete and must not claim complete catalog coverage.
- For demand aggregates, use fixed non-overlapping buckets and stable IDs. A revised
  bucket replaces the previous version in the next materialized snapshot; do not
  concatenate both revisions or mix raw events with their aggregates.
- For products, build the current snapshot using explicit revision rules. Retain old
  evidence in historical jobs, but do not treat a superseded source revision as a
  current contradiction. Independent current sources can still conflict.
- Apply source deletions/tombstones upstream when building the next snapshot. The
  current record contract has no built-in tombstone or change-stream processor.
- Keep a canonical product registry upstream. Until a dedicated inventory interface
  exists, include a catalog record for every in-scope SKU, even when only its genuine
  title/description is available. No invented specification is needed for inclusion.

## Counting and privacy rules

`demand_events` sums `count` over matching deduplicated demand records within the
inclusive observation window; `len(demand_records)` counts contributing records.
Neither is unique shoppers. A request may match several candidates, so candidate
totals must not be summed into unique total demand. Store separate external counts.
Deduplicate overlapping exports upstream when IDs differ; a new namespace prevents
ID collisions, not semantic duplicate events.

Product coverage is uncontested assigned distinct SKUs divided by distinct SKUs in
the declared category snapshot. Multiple pages/images never increase that denominator.
Report its scope/completeness: source-backed inventory is not automatically the full
store catalog. Keep assigned, conflicting and unknown products distinguishable;
retrieval-selected asset counts are a separate metric.

Remove names, emails, phone numbers, addresses, order/account IDs, tokens and free-text
secrets upstream as appropriate to the authorized use. Prefer query aggregates and
minimal request excerpts; avoid customer identifiers when they add no product value.
Pseudonymous identifiers can still be personal data. Reports include source quotes,
and frozen jobs/publication history can retain them; use the source's access policy
for databases, HTML, JSON and backups. Do not embed credential-bearing URLs.

Automatic PII detection, row-level access control, retention/deletion propagation
and rights management are not established baseline features. The operator must set
access and retention and handle deletion across retained artifacts before a private
data pilot. Default examples and tests remain synthetic and local.

## Connector acceptance checklist

For each proposed adapter, verify one replay, one interrupted page/retry, an amended
demand bucket, a product revision/deletion, an unknown SKU, non-ASCII evidence and a
redacted record. Reconcile input events and distinct SKUs with the export manifest.
Verify that excluded dates/categories and external feedback do not inflate demand;
that quotes resolve against frozen source text; and that unsupported assets remain
visible. Finally, rerun the same frozen snapshot offline and obtain the same proposal.
Only then describe that adapter as implemented and name the provider it actually uses.
