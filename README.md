# PILON

**Background products for keeping a catalog's knowledge useful: Benchmark, Extract, and Ingest.**

People ask for things that a catalog does not yet describe. PILON compares those requests with the current model, looks for supporting product evidence, and prepares a change for review. Your search application continues to use a published model snapshot while this work runs in the background.

The running-shoe example makes the distinction concrete. A shopper asks for “room for my toes.” **Pace 01** has standard width and a wide toe box. **Ridge 02** has wide width and a tapered toe box. A width filter cannot express that difference. PILON proposes a **Toe box** facet and keeps the source behind each proposed product assignment.

**v0.3.0a1 / local alpha:** Discovery, the background loop, and explicit local publication/rollback are implemented. The example data are synthetic. No production deployment, benchmark advantage, or AI accuracy is claimed. The [implementation contract](docs/background-loop-contract.md) describes the stage boundaries.

[Open the eight-slide presentation](docs/presentation.html) in a browser. It is a single HTML file with local illustrations, keyboard navigation, and a print layout. It needs no network connection.

## Three background products

| Product | Question it answers | Inputs | Reviewable output |
| --- | --- | --- | --- |
| **Benchmark** | What does the current model fail to describe or support? | A frozen model, existing assignments, and incoming demand or external observations | Candidates with a gap type, observed demand, and source quotations |
| **Extract** | Which products have evidence for the proposed fact? | A candidate and available product sources | Proposed values with exact source spans, plus conflicts, unknowns, and a record of which assets were selected |
| **Ingest** | What would change if we accepted this proposal? | The base model, candidates, and extraction results | A before/after schema and assignment diff, with blocked changes visible |

### Benchmark: identify the next fact to investigate

Benchmark compares demand with the model and its stored facts. The loop contract distinguishes a `schema_gap` (a missing facet), a `coverage_gap` (missing assignments), a `retrieval_gap` (a modeled fact that needs retrieval investigation), and `unresolved_intent` (a request that still needs interpretation). These are review categories, not a claim that PILON has diagnosed a live search system.

A candidate starts with `needs_extraction`. “Room for my toes” can justify investigating a toe-box facet even when no product source matches yet. Demand counts describe observed events, not unique shoppers or projected revenue. Customer feedback supports the need for a fact; it does not establish that fact for a product. Benchmark runs in the background and never answers a customer query.

### Extract: route sources and retain evidence

Extract selects relevant assets, extracts proposed values, and checks quotations against the unchanged source text. The baseline uses lexical matching and labeled specifications such as `Toe box: wide`. Its routing record explains selected, unselected, and unsupported assets. Retrieval counts and elapsed time remain separate from extraction counts and elapsed time.

Missing evidence, an explicit negative value, and conflicting sources remain distinct. A skipped asset is not evidence of absence. A matching quote proves where the text came from; it does not prove that the interpretation or source is correct.

The interface allows a custom extractor or embedding provider. Supplied vectors can support routing, but the default does not generate embeddings or call a hosted model. Document text must be supplied through an adapter or export. Images require an explicit extraction adapter; a filename alone cannot support an assignment.

### Ingest: propose a model change, then publish explicitly

Ingest first builds an immutable projection: the proposed facet definitions and vocabulary, supported product assignments, and the changes blocked by missing or conflicting evidence. The report shows the base and proposed models so a reviewer can see what acceptance would mean.

The worker stops at this proposal. Publication and rollback are explicit local operations, with revision and base-hash concurrency checks, atomic writes, immutable snapshots, and a persisted audit trail. Publication changes a local model snapshot. Connecting that snapshot to a storefront or search index requires your own integration.

## How the background loop fits

```text
Model + source exports
          |
          v
Frozen job inputs -> persistent queue -> worker
                                          |
                                     Benchmark
                                          |
                                       Extract
                                          |
                                  Ingest projection
                                          |
                                    Review the diff
                                          |
                                  Explicit publication
                                          |
                                  Published snapshot -> your search application

Later source snapshot -> new job             Explicit rollback -> prior snapshot
```

The local loop uses SQLite leases and stage checkpoints so a restarted worker can reuse completed stages. Each job keeps its frozen model and source inputs, including unknown source fields. A later job can bring new evidence for a previously unresolved fact. The background worker never publishes automatically, and the customer query path reads only a published snapshot.

## Background-loop quickstart

These commands are implemented in v0.3.0a1 and follow the [implementation contract](docs/background-loop-contract.md). They may be unavailable in an older installed release. Python 3.11 or later is required. The core runtime and synthetic demonstration use the standard library and require no API key or paid request.

For the `pilon` executable, install this checkout into your Python environment:

```sh
python -m pip install -e .
```

Installation may fetch packaging tools. The existing no-install, offline quickstart is below.

The loop demo uses bundled synthetic inputs:

```sh
pilon loop demo
```

Open **runtime/background-loop.html**. The JSON snapshot is **runtime/background-loop.json**. From an uninstalled checkout, the equivalent command is `python -m src.pilon loop demo`.

To demonstrate how a later source resolves a gap:

```sh
pilon loop demo --new-source --html runtime/background-loop-new-source.html --output runtime/background-loop-new-source.json
```

The first snapshot leaves `removable_insole` without product evidence. The added source supports a proposed `yes` assignment in the later projection. `arch_support` remains unknown. Neither run publishes a model. The separate output paths let you compare both reports.

The explicit job lifecycle uses the same sample model and feed:

```sh
pilon loop enqueue --model src/pilon/facets/example/model.json --signals src/pilon/facets/example/signals.jsonl
pilon loop work --once
pilon loop report JOB_ID --html runtime/loop-report.html
pilon loop serve
```

Replace `JOB_ID` with the identifier returned by enqueue. `work --once` processes a queued job through projection. Add `--job JOB_ID` to target a job. Repeat `--signals` to combine exports. `report` exports its review page and accepts `--output` for a JSON file. `serve` opens the read-only **PILON Benchmark** workspace at **http://127.0.0.1:8473/** and does not start jobs or publish models. Failed jobs can be explicitly queued again with `pilon loop retry JOB_ID` to resume from their checkpoints.

Benchmark has its own overview, opportunity table, demand sources, model reference and history. Search and filter opportunities, inspect exact customer quotations, and export the filtered results. Extract and Ingest remain separate products. The complete loop report is still available at `/report`. [Workspace and design system](docs/benchmark-workspace.md)

### Real requests against an observed model: WANDS

```sh
pilon benchmark wands
pilon loop serve
```

This optional import downloads the public [WANDS dataset](https://github.com/wayfair/WANDS) at a pinned revision. It retains **480 sampled customer queries** and reconstructs attribute names, their observed values and category scopes. Product rows are streamed and discarded: no product descriptions, IDs, individual assignments, query/product associations or relevance labels are exported. The data and MIT attribution remain under ignored `runtime/wands/`, outside the source distribution.

WANDS does not provide an official business schema, query dates or traffic frequencies. The reconstructed model is an observed vocabulary, not an exhaustive allowed-value contract. A value absent from this sample may be a synonym, valid but unobserved, or genuinely missing. Attribute/value domains remain scoped to product categories; the query and product category taxonomies are not automatically equated.

This command runs **Benchmark only**, with no paid API calls. The lexical baseline keeps unrecognized requests for interpretation; it does not label them missing attributes. Grounded intent adapters may supply a requested value and its exact source span: comparison distinguishes observed values from literal gaps requiring confirmation. Product coverage and retrieval performance are not assessed in this mode. Extract and Ingest do not run.

Use `--import-only` to prepare the inputs without a run, or `--db PATH` to select a queue (use the same path for `loop serve`). Re-running the import verifies file hashes and reuses the local files without downloading again. A different source revision or import format requires a new `--output-dir`.

To replay a semantic review prepared by an agent or another annotation process:

```sh
pilon benchmark review --reviews reviewed-demands.json
```

The decision file contains `model_hash`, `records_hash` (the SHA-256 fingerprints produced by `pilon.loop.store.fingerprint`) and a `reviews` array. Every demand requires an interpretation and grounded criteria: exact `quote`, `start`, `end`, a rationale, and an assessment (`represented`, `attribute_gap`, `value_gap`, `filter_proposal`, or `unresolved`). Attribute keys, observed values and category references must exist in the frozen model. A changed model, incomplete pass or invalid quotation blocks import. The code contract is in `src/pilon/loop/semantic.py`.

For example, “desk for kids” can support a suggested audience filter backed by an existing **Kids Desks** category. This is distinct from missing product information. The actual storefront filter configuration is unknown. Imported agent decisions are inspectable proposals, not an independent accuracy measurement or automatically published changes. This command replays supplied decisions; it does not invoke an LLM or provide an automated annotation service.

### Revisit retained demand when new evidence arrives

Add a new source to an earlier job without sending its demand records again:

```sh
pilon loop revisit JOB_ID --signals new-product-source.jsonl
pilon loop work --once --job NEW_JOB_ID
```

`revisit` retains the previous job's frozen demand and source records, adds the new records, and enqueues a job. Replace `NEW_JOB_ID` with the returned identifier. Add `--model newer-model.json` to use a newer model; otherwise the previous model is retained. The worker remains a separate step.

Record IDs are immutable. Identical records with the same ID are deduplicated, while changed content under an existing ID is rejected. Give a revised source a distinct ID. Both versions then remain inspectable, and contradictory product values stay visible as conflicts rather than silently replacing earlier evidence.

### Watch local exports in the background

Run the watcher in one terminal and the worker in another:

```sh
pilon loop watch --model model.json --signals catalog.csv --signals feedback.jsonl
```

```sh
pilon loop work
```

The watcher hashes local export content and enqueues changed snapshots. It does not poll a CRM, PIM, or external provider. Export files atomically from your own systems. Add `--once` to check the exports once. The worker processes queued jobs continuously until stopped; `--once` processes at most one job. Both commands use **runtime/background.sqlite** by default. Use the same `--db` path for commands that should share a queue.

### Publish a reviewed local projection

After reviewing a completed job's diff, publish explicitly:

```sh
pilon loop publish JOB_ID --store runtime/model-store --actor local
```

Replace `JOB_ID` with the completed job's identifier. An empty store is initialized to that job's base model at revision 0. The first publication advances it to revision 1. Existing stores are never reset. Publication checks the proposal's base hash and atomically compares the current revision before writing a new snapshot. Add `--expected-current INT` to require a specific revision. The output identifies the receipt, current revision, and snapshot hash.

For a store currently at revision 1, explicitly restore its original revision 0:

```sh
pilon loop rollback --store runtime/model-store --actor local --target 0 --expected-current 1
```

Use the actual revision numbers for your store. Rollback appends an audited revision containing the old snapshot; it does not erase history. These commands change local model files only. Neither the demo nor the normal worker publishes, and no bundled connector updates a live storefront or search index.

## Existing Discovery quickstart

The original Discovery entry points remain available. From this checkout, run:

```sh
python -m src.pilon demo
```

Open **runtime/ecommerce-facets.html**. Explore the proposed values and click **wide** to inspect the matching products. This bundled demo runs offline with the Python standard library. On Windows, double-click **start-local.cmd** to generate and open the same page.

For the existing local viewer:

```sh
python -m src.pilon serve
```

Open **http://127.0.0.1:8472/**. The JSON report is available at **/api/report**.

Discovery retains its four exploration levels: **Discovery**, **Forecast**, **Induction**, and **Usage**. These are stages in the original report. Benchmark, Extract, and Ingest describe the new background products.

The legacy synthetic sample has 34 matching demand events in a 30-day observation window. Its 60-day forecast gives 68 events under a constant-rate assumption. Four of six products have an uncontested toe-box value, one lacks evidence, and one has conflicting sources. These are fixture results, not measures of commercial impact, retrieval performance, or AI accuracy.

### Bring your own exports to Discovery

After installing the checkout:

```sh
pilon discover --model model.json --signals catalog.csv --signals feedback.jsonl --output candidates.json
pilon serve --model model.json --signals signals.csv
```

Use `--signals -` for JSONL on stdin and omit `--output` to pipe the result downstream. Choose `--through discovery`, `forecast`, `induction`, or `usage` to stop at the level your job needs.

| Input role | Example exports | What they establish |
| --- | --- | --- |
| `demand` | Site searches, support conversations, customer reviews, feedback forms | Observed customer interest |
| `external` | Competitor reviews or third-party feedback | Context for an investigation |
| `catalog` | Product pages, PIM exports, merchant feeds | Evidence for a particular product and value |

Every record has `id`, `category`, `role`, `source`, and the original `text`. Catalog records also have `product_id`. Demand records have `date` and may have an event `count`. The model supplies `category`, `existing_facets`, optional `aliases`, and the observation window. The loop contract adds optional versioned facet definitions and existing assignments without replacing this feed shape.

These are file and Python interfaces. Source names such as “support chat” or “PIM” do not imply a bundled connector. See the [integration guide and CSV example](docs/use-case-ecommerce-filter-discovery.md) for the input format, a Python extractor, and importing precomputed annotations, including annotations produced by a separately run LangExtract job.

## What is implemented, reusable, and still ahead

| Status | Scope |
| --- | --- |
| **Implemented baseline** | Offline Discovery, CSV/JSONL/stdin inputs, Python iterables, deterministic phrase matching, labeled-spec extraction, quotation/offset checks, JSON and HTML reports, and a local preview server |
| **Implemented local loop** | Benchmark/Extract/Ingest projection, frozen inputs, persistent jobs, a local export watcher, restart checkpoints, reports, a read-only viewer, and the new-source synthetic demo |
| **Implemented local publication** | Explicit publication/rollback, immutable snapshots, concurrency checks, and a persisted audit trail |
| **Reusable interfaces** | Existing record feeds and extractor callables; loop contracts for optional embeddings, extraction adapters, projection results, and a self-contained report renderer. An interface does not supply an external service. |
| **Roadmap and evaluation** | Production connectors, live index integration, richer document/image extraction, and measured comparisons of alternative routing strategies, including ANN or topological data analysis (TDA) |

TDA and ANN are not deployed defaults. No performance improvement, extraction accuracy, recall, or cost saving has been established by the synthetic demo. The lexical baseline depends on explicit language and configured aliases. It can miss an intent or select incomplete evidence, which is why proposals retain review status and unknowns remain visible.

## Business value to evaluate

For merchandising teams, the useful output is a concrete filter proposal with inspectable product evidence. For search teams, it is a reproducible model diff that can enter an existing review and indexing process. For data teams, it is a record of supported assignments, disagreements, and the evidence still needed.

Evaluate these outcomes on your own reviewed data:

- **Useful proposals:** accepted candidates relative to candidates reviewed, with reasons for rejection.
- **Evidence coverage:** supported assignments alongside conflicts, unknown products, and assets left unexamined.
- **Processing effort:** measured retrieval and extraction time and counts, plus human review time. Claims about recall need an independently labeled evaluation set.
- **Customer impact:** an experiment after publication, measuring filter use or search success. The offline demo does not establish a conversion or revenue effect.

## Develop and contribute

- [Discovery engine and Python API](src/pilon/facets/) and [editable synthetic inputs](src/pilon/facets/example/).
- [Background-loop contract](docs/background-loop-contract.md) and [Discovery design](docs/discovery.md).
- [Contribution guide](CONTRIBUTING.md), [data handling](SECURITY.md), and [MIT license](LICENSE).

Reports contain source quotations and inherit the access requirements of their inputs. Keep public examples synthetic or explicitly licensed. Custom adapters control their own external calls and costs; the default demo and tests do not need paid services.
