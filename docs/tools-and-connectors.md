# Connect the model. Bring the evidence.

PILON connects requests to your catalog structure, then selected proposals to product evidence. **Benchmark**, **Extract** and **Induct** stay separate: choosing an inference provider does not also configure extraction or publication.

Start with the [two-route guide](getting-started.md) or local **[/start](http://127.0.0.1:8473/start)**. For endpoint settings and credentials, use [model connectors](model-connectors.md).

## What works today

| You want to… | Available now | You supply |
| --- | --- | --- |
| Interpret new customer requests | OpenRouter, OpenAI-compatible and local Ollama connections for **Benchmark** | Model configuration, endpoint access and any credentials |
| Bring your catalog and demand | Model JSON; CSV/JSONL, stdin and Python records; WANDS and Home Depot importers | Exported data mapped to PILON's record format |
| Investigate product facts | **Extract**: labeled specifications, supplied annotations, lexical or supplied-vector routing | Product IDs and unchanged source text; adapters for richer extraction |
| Review and retain a change | **Induct**: local projections, explicit publication/rollback and JSON/HTML exports | Review and any downstream PIM, search-index or storefront integration |

The core uses Python 3.11+ and the standard library. A source name such as `support_chat` records provenance; it does not connect a support account.

## Benchmark: choose how requests are interpreted

`pilon benchmark run` previews by default; `--execute` enables the configured provider. It sends the complete catalog model and each selected demand record, validates source quotations and model references, and caches validated reviews for resume. It stops at Benchmark.

| Connection | Useful when | Tradeoff |
| --- | --- | --- |
| [OpenRouter](../configs/openrouter.json) | You want a hosted model through OpenRouter | Inputs leave your machine; you manage credentials, model choice and price estimates. |
| [OpenAI-compatible](../configs/openai-compatible.json) | You already use a compatible hosted or local endpoint | The backend must support the configured chat-completion and JSON-response options. |
| [Local Ollama](../configs/local-ollama.json) | You want inference on a local service | You provide the running service, model, memory and compute. PILON does not install them. |

The local **[/connectors](http://127.0.0.1:8473/connectors)** page creates configuration downloads. It neither tests the connection nor starts model calls. See [configuration, cost estimates and limits](model-connectors.md).

<details>
<summary>Other Benchmark paths: local rules, imported reviews and callbacks</summary>

| Path | Status and boundary |
| --- | --- |
| Configured phrases and grounded intents | **Built in.** The [local baseline](../src/pilon/loop/benchmark.py) recognizes configured wording; unfamiliar requests can remain unresolved. |
| Imported semantic decisions | **Built in.** [Review validation](../src/pilon/loop/semantic.py) and [detached bundles](../src/pilon/loop/review_bundle.py) check provenance and references. Replaying a review does not measure its accuracy. |
| `benchmark(model, records, intent_extractor=...)` | **Extension interface.** You implement and evaluate the callback; record-level `intents` take precedence. |
| Live search diagnosis | **Integration/evaluation work.** A catalog gap does not prove a ranking failure; diagnosis needs serving telemetry. |

</details>

## Sources: bring exports first

Use model JSON and CSV/JSONL records. Repeat `--signals` to combine feeds where supported; `--signals -` reads JSONL from stdin. Use JSONL for nested annotations or vectors. Generic Excel, TSV and vendor JSON exports need conversion. See [input examples](getting-started.md#prepare-your-own-files) and [source records](source-connectors.md).

| Source | Available now | Still requires integration |
| --- | --- | --- |
| Search, CRM/support, PIM and CMS | Import mapped exports | Authenticated accounts, remote polling, paging, revisions and deletions |
| Local export folders | `loop watch` enqueues changed snapshots; `loop work` processes them; `loop revisit` adds immutable records | Your exporter and its scheduling/atomic writes |
| WANDS and Home Depot | Dataset-specific importers; WANDS can explicitly download data; Home Depot reads supplied CSVs | Your local dataset preparation. Home Depot's review replay makes no new inference calls. |
| Documents and images | Text exports and explicit extraction interfaces | Bundled PDF parsing, OCR and vision adapters remain planned |

Preserve `id`, `category`, `role`, `source` and original `text`; product records also need `product_id`. Customer demand expresses a need. Only catalog evidence can support a product assignment.

## Extract: select sources, then check claims

| Tool | Status | Tradeoff |
| --- | --- | --- |
| `Label: value` parser and supplied annotations | **Built in** | Simple specifications work locally. Exact quotes verify grounding, not the interpretation. |
| Lexical and cosine routing | **Built in** | Lexical routing uses wording; cosine routing needs compatible supplied vectors or your embedding callback. No default embedding generation. |
| Home Depot FTS5/BM25 shortlist | **Built in** | Ranks local descriptions and preserves hashes. A shortlist selects sources; it does not establish extraction quality or full-catalog recall. |
| LangExtract or another LLM extractor | **Interface available; bundled adapter planned** | Supply annotations or implement an extractor. The Benchmark provider is not automatically reused. |
| BGE, ANN index or reranker | **Vector/callback interfaces available; bundled integrations planned** | You supply vectors or retrieval logic. PILON does not install BGE or provide an ANN index. |
| OCR, document or vision extraction | **Extractor interface available; bundled adapters planned** | You supply extracted evidence and asset provenance. A filename or verified text quote cannot validate image contents. |

<details>
<summary>Implement an extractor or embedding adapter</summary>

The [Python extraction interface](../src/pilon/loop/extraction.py) is:

```python
extract(candidate, records, model=None, *, top_k=50, exhaustive=False,
        embedding_provider=None, extractor=None)
```

`extractor(candidate, record)` returns `Spec` objects or accepted annotations such as `{label, value, quote, start, end}`. Labels must match the candidate's labels/aliases; quotes must match the unchanged text at Python character offsets. Supplied `extractions: []` suppresses fallback parsing.

`embedding_provider(text)` supplies vectors. Declared embedding spaces must agree on model and dimensions. Precomputed vectors allow distinct query/document preprocessing.

`top_k=50` limits assets per candidate, not tokens or spending. Embedding calls can happen before shortlisting. `exhaustive=True` bypasses retrieval and analyzes every supported asset in scope. Custom hooks do not inherit the Benchmark connector's caching or billing controls.

</details>

<details>
<summary>Inspect Home Depot retrieval or supplied embedding geometry</summary>

The [Home Depot helpers](../src/pilon/home_depot_assets.py) are Python functions:

```python
index_descriptions(csv_path, database, encoding='utf-8')
route_assets(database, phrases, limit=30)
```

The router searches quoted phrases joined with OR, accepts a limit of 1–500 assets, retains hashes and reports sources outside the shortlist.

Optional [geometry inspection](local-geometry.md), enabled with `--geometry` on supported loop commands, examines neighborhoods, minimum-spanning-tree merges and zero-dimensional persistence over supplied declared embeddings. It does not change extraction or establish semantic classes or accuracy gains.

</details>

## Select proposals explicitly

After reviewing a completed Benchmark, save product-only sources from the same dataset as `product-sources.jsonl`. For the getting-started synthetic example:

```jsonl
{"id":"source-1","category":"running-shoes","role":"catalog","source":"synthetic_product_spec","product_id":"shoe-1","text":"Removable insole: yes"}
```

Replace that example with your genuine product text. Select an exact candidate key from Benchmark, then run:

```sh
pilon loop enrich BENCHMARK_JOB --candidate CANDIDATE_KEY --signals product-sources.jsonl --db runtime/my-benchmark/jobs.sqlite
pilon loop work --job ENRICHMENT_JOB --once --db runtime/my-benchmark/jobs.sqlite
```

Replace `BENCHMARK_JOB` and `CANDIDATE_KEY` with the reviewed run and proposal; use the child job ID printed by `enrich` for `ENRICHMENT_JOB`. If your Benchmark uses another database, use that path in both commands.

`enrich` prints the **Extract** and **Induct** links. If the local server from getting started is still running, open them. Otherwise start it with `pilon start --db runtime/my-benchmark/jobs.sqlite`.

**Extract** shows evidence, conflicts and unknowns. **Induct** shows the proposed structure and assignment changes, blocked changes and publication state. Publication and rollback are explicit local commands; see the [publication contract](background-loop-contract.md).

<details>
<summary>Select several proposals or limit their source records</summary>

Repeat `--candidate` for several proposals. Sharing an attribute key does not select every proposal for it. Existing attributes retain their keys; new facts require a stable `proposed_key`. Unresolved intent needs clarification first.

Optional `--routing routing.json` accepts one manifest for one target, or manifests keyed by target for several. Export a source packet's `records` as JSONL, not its `{records, routing}` wrapper. Exhaustive analysis of a supplied shortlist still leaves the rest of the catalog unassessed. See [handoff validation](../src/pilon/loop/enrichment.py).

</details>

## Judge the result on your data

Compare useful proposals, evidence quality, unknowns and review effort alongside latency and usage. Configured rates are estimates; missing provider cost is not zero. Neither the synthetic demo nor the Home Depot replay establishes general accuracy, full-catalog recall or conversion lift.
