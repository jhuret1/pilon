# Tools and connectors

Use [getting started](getting-started.md) for a first run and [model connectors](model-connectors.md) for executable provider configuration. This page distinguishes built-in behavior from extension interfaces and integration work.

The runtime uses Python 3.11+ and the standard library. Configuring a remote model does not install an SDK or connect a source system. See [package configuration](../pyproject.toml).

## What are you connecting?

| Connection | Available now | What you supply |
| --- | --- | --- |
| **Model inference** | Configurable OpenRouter, OpenAI-compatible and local Ollama chat-completion connections for semantic Benchmark | JSON configuration, a model identifier, endpoint access and an environment variable for any API key |
| **Customer demand and schema** | Model JSON; demand CSV/JSONL/stdin; Python records; WANDS and Home Depot importers | Exports from search logs, support tools or your catalog model |
| **Product evidence** | Catalog records, local source routing, labeled-spec parsing and supplied exact-span annotations | Product identity, unchanged source text and any reviewed annotations |
| **Downstream publication** | Immutable local projections, explicit local publication and rollback, JSON/HTML exports | Your own PIM, knowledge-graph, search-index or storefront integration |

Model and data connectors are separate. A `source` label such as `support_chat` describes provenance; it does not activate an authenticated support connector.

## Benchmark: a semantic provider is built in

`pilon benchmark run` uses a JSON configuration to interpret new requests against a complete model and its observed values. It previews by default; `--execute` enables inference. Requests are bounded, oversize context is rejected, responses require exact source quotations and valid model references, and validated record reviews can be reused from cache. Provider/model configuration, estimates and usage remain inspectable.

This path stops at Benchmark. It does not reuse the provider automatically for Extract or publish a model. The local `/start` and `/connectors` pages explain configuration and offer downloads; they do not start calls or expose keys.

Other Benchmark paths remain available:

| Path | Status | Boundary |
| --- | --- | --- |
| Configured phrases and supplied grounded intents | **Built in.** [Benchmark implementation](../src/pilon/loop/benchmark.py). | The lexical baseline does not provide general semantic understanding; unfamiliar wording can remain unresolved. |
| Imported semantic decisions | **Built in.** [Review validation](../src/pilon/loop/semantic.py) and [detached bundles](../src/pilon/loop/review_bundle.py). | Replaying a supplied review checks provenance and references, not independent accuracy. Home Depot uses this path. |
| Python intent callback | **Extension interface.** `benchmark(model, records, intent_extractor=...)`; record-level `intents` take precedence. | Custom adapters own their implementation, usage records and evaluation. |
| Retrieval diagnosis against live search results | **Integration/evaluation work.** | A model gap is not proof of a search-ranking failure; diagnosis needs serving telemetry. |

The full model goes into semantic review. A globally observed value does not establish category or product coverage, and an unobserved value does not prove a product is unavailable. See [configuration, limits and cost accounting](model-connectors.md).

## Source connectors

| Source interface | Status | Limits |
| --- | --- | --- |
| Local JSON model and CSV/JSONL signals | **Built in.** [Readers](../src/pilon/facets/io.py). Repeated `--signals` combines feeds where supported; `--signals -` reads JSONL. | General signals are one object per line or CSV, not a JSON array. Use JSONL for nested annotations and vectors; generic TSV/Excel/vendor JSON need conversion. |
| Local export watching | **Built in.** `loop watch` enqueues changed snapshots; `loop work` processes jobs; `loop revisit` adds immutable records. [Commands](../src/pilon/loop/commands.py). | Your exporter owns remote polling, paging, atomic writes and deletion handling. |
| WANDS and Home Depot | **Built in.** Dataset-specific schema/demand importers with checked local caches. | WANDS can explicitly download its dataset. Home Depot reads user-supplied CSVs; its replay uses supplied decisions, not new provider calls. Neither uses relevance judgments as Benchmark truth. |
| Search, CRM/support, PIM and CMS services | **Exports supported; direct authenticated adapters remain integration work.** | No automatic account connection, vendor-schema discovery, watermarking or remote writeback. |
| Documents and images | **Text exports supported; richer adapters remain integration work.** | No bundled PDF parser, OCR or vision model. An image filename is not product evidence. |

All records carry `id`, `category`, `role`, `source` and original `text`. Catalog records also need `product_id`. Dates and counts must reflect the declared observation window or sample; explicitly undated schema-only requests are supported. Preserve immutable identities and Python character offsets into unchanged text. See [input examples](getting-started.md#prepare-your-own-files) and the [source contract](source-connectors.md).

## Extract: local tools and optional adapters

| Tool | Status | What it does and does not establish |
| --- | --- | --- |
| Labeled specifications and supplied annotations | **Built in.** Parse `Label: value` text or accept `{label, value, quote, start, end}` annotations. | Exact quotation checks establish source grounding, not semantic correctness. Empty `extractions: []` suppresses fallback parsing. |
| Home Depot FTS5/BM25 shortlist | **Built in.** [Index and router](../src/pilon/home_depot_assets.py). | Indexes local descriptions with hashes; searches quoted phrases joined with OR. A ranked shortlist is source selection, not extraction or measured recall. |
| Lexical and cosine routing | **Built in.** [Extraction implementation](../src/pilon/loop/extraction.py). | Cosine routing consumes supplied compatible vectors; the default does not generate embeddings. |
| LangExtract or another LLM extractor | **Callable/data interface; bundled integration remains planned.** | Supply annotations from an upstream run or implement `extractor(candidate, record)`. The new Benchmark provider is not a LangExtract adapter. |
| BGE encoder, ANN index or reranker | **Vector/callback interface; bundled integration remains planned.** | Precompute vectors or implement `embedding_provider(text)`. PILON does not install BGE, generate its vectors, or provide ANN retrieval. |
| OCR, document and vision extraction | **Explicit extractor interface; bundled adapters remain planned.** | Claims still require source-grounded text. A validated quote alone does not verify image contents. |
| Geometry inspection | **Built in, optional.** [Geometry](local-geometry.md) over supplied declared embeddings; opt in with `--geometry`. | Inspects neighborhoods, MST merges and zero-dimensional persistence. It neither changes extraction nor establishes semantic classes or an accuracy gain. |

The extraction interface is:

```python
extract(candidate, records, model=None, *, top_k=50, exhaustive=False,
        embedding_provider=None, extractor=None)
```

Callbacks can supply `Spec` objects or accepted annotation dictionaries. Labels must match the candidate's labels/aliases and quotes must match the original source. Embedding contracts declare a model and dimensions; declared spaces must match. Precomputed vectors are useful when an encoder needs distinct query/document preprocessing. [Full contract](../src/pilon/loop/extraction.py).

The Home Depot helpers are Python functions, not a general indexing CLI: `index_descriptions(csv_path, database, encoding='utf-8')` and `route_assets(database, phrases, limit=30)`. The router accepts 1–500 selected assets, preserves hashes and reports what remains outside its shortlist.

## Select proposals explicitly

After reviewing a completed Benchmark, select exact candidate IDs and supply product-only sources from the same dataset:

```sh
pilon loop enrich BENCHMARK_JOB --candidate CANDIDATE_KEY --signals annotated-sources.jsonl --db YOUR_DB
pilon loop work --job ENRICHMENT_JOB --once --db YOUR_DB
pilon start --db YOUR_DB
```

Use the child job ID printed by `enrich`. Repeat `--candidate` for multiple proposals; sharing an attribute key does not mean you selected every proposal for that attribute. Existing attributes keep their stable keys. New facts need stable `proposed_key` identities, and unresolved intent must be clarified first.

Optional `--routing routing.json` accepts one manifest for one target, or manifests keyed by target for several targets. Export a source packet's `records` as JSONL, not its `{records, routing}` wrapper. Each target analyzes its selected records; exhaustive analysis here means the supplied shortlist, not the full catalog. See [handoff validation](../src/pilon/loop/enrichment.py).

The read-only **`/extract/JOB`** page shows routing, claims, evidence, conflicts and unknowns. **`/induct/JOB`** shows the before/after projection, blocked changes and publication state. Publication and rollback are explicit local commands; external systems remain your integration responsibility. [Projection implementation](../src/pilon/loop/projection.py).

## Costs, limits and evaluation

Provider calls and local processing are accounted for separately. The semantic connector has request/context/time limits and an estimate-based spending guard. Configured rates are user-maintained inputs, not live pricing or a guaranteed billing cap. Reported provider usage/cost, when available, must remain distinct from estimates; missing provider cost is not zero. [Details](model-connectors.md).

The generic extractor's `top_k=50` is an **asset limit per candidate**, not a token or money limit. An embedding callback may run before that shortlist is selected. `exhaustive=True` bypasses retrieval and analyzes all supported assets in scope. Local CPU, storage, indexing and review time remain costs even with no hosted inference.

Custom worker hooks remain Python integration interfaces. They do not automatically gain the semantic connector's caching or billing controls. Track adapter/model/prompt versions and usage explicitly when replacing stages.

Evaluate proposal usefulness, evidence quality, unknowns and review effort on your own data. Neither the synthetic demo nor the supplied Home Depot review proves general accuracy, full-catalog recall, conversion lift, or a universal advantage for one model or routing strategy.
