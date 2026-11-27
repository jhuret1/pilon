# PILON

**Turn reviews into an inspectable, evidence-linked candidate ontology.**

PILON is a local research workbench for ontology induction. It extracts assertions
with exact source spans, retrieves nearby concept definitions, and chooses whether
to reuse a concept or propose a new one. Values and their provenance stay attached.

**Research alpha:** a matching quotation proves where words came from, not that an
interpretation is correct. Generated concepts remain candidates. PILON does not
claim calibrated precision, recall, production readiness or a fully verified ontology.

## Quickstart — no key, no model download

Python 3.11–3.13:

```sh
git clone https://github.com/jhuret1/pilon.git
cd pilon
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e .
pilon demo
```

Open **http://127.0.0.1:8472**. Stop the local server with Ctrl+C.
The viewer shows concepts, values, complete source reviews, exact character spans,
decisions, routing proportions, latency and recorded costs. Opening it never calls a model.

The bundled example contains **24 fictional product reviews, 12 products, six
languages, 32 scripted assertions and 12 candidate concepts**. It includes missing
accessories, broken components, repairs, comparison to an old product, advertisement
claims, no mention, and an instruction embedded in review text.

**The offline demo is a fixture replay:** extraction and decisions are scripted;
vectors are deterministic hash vectors, not BGE. It checks the software path and
explains the output format. It is not a model benchmark. Expect zero API calls and
zero API cost. No accommodation reviews or private experiment data are included.

```sh
pilon demo --no-serve             # terminal / CI smoke test
pilon serve                     # reopen existing results; read-only
pilon export RUN_ID --output runtime/export.json
```

## Real product reviews — optional Amazon import

The importer fetches a bounded slice of **Amazon Reviews 2023**, maintained by the
McAuley Lab. It resolves an immutable dataset revision, streams only the requested
slice, records hashes and source positions, and excludes reviewer IDs and image URLs.
No dataset Python code is executed. Review text is unchanged and is **not claimed
to be anonymized**.

```sh
pilon import-amazon --limit 20 --output data/amazon-home-kitchen.json
# Reproduce a download with its recorded 40-character revision:
pilon import-amazon --limit 20 --offset 20 --revision REVISION --output data/amazon-next.json
```

`--limit` counts **reviews, not products**. A contiguous slice is useful for a smoke
test; it is not a representative or labeled evaluation dataset. Downloading does
not invoke any model. Downloaded data remains in ignored `data/`.

The source authors do not assign a license to review text and describe the release
as primarily for research. Amazon texts are therefore **not bundled or relicensed
under this repository's MIT license**. See the [dataset](https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023)
and [authors' usage clarification](https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/discussions/1).

## Real induction — explicitly opt into paid inference

```sh
python -m pip install -e ".[openrouter]"
export OPENROUTER_API_KEY="your-key" # PowerShell: $env:OPENROUTER_API_KEY="your-key"
pilon run data/amazon-home-kitchen.json --provider openrouter --budget 1 --allow-paid
pilon serve
```

This sends the selected review text and extracted concept cards to OpenRouter and
its model providers. The current adapter uses LangExtract with Gemini 2.5 Flash,
BGE-M3 embeddings through OpenRouter, and the JEV Decisions endpoint for identity
and family choices. Service/model availability is checked at runtime; it is not
guaranteed by this release. Embeddings use the configured Parasail / DeepInfra
preference, with OpenRouter fallback routing enabled.

The USD budget is an **admission limit using conservative reservations**, not a
provider-enforced billing cap. Known usage costs are recorded separately from
unconfirmed reservations. Unknown billed outcomes are not automatically retried.
Only explicit uncharged HTTP 429 responses can retry automatically. Model price
changes or unavailable endpoints pause the run. No paid test is run in CI.

Repeated identical commands reuse the same run. After interruption, repeat the
command to resume committed reviews; uncertain API calls require inspection.
Only one worker process can write a given database. Use a new `--request-key`
deliberately for a separate experiment and separate budget.

## What runs

```mermaid
flowchart LR
    A[Reviews + source IDs] --> B[LangExtract: assertions + exact spans]
    B --> C[Validate offsets, attributes and subject]
    C --> D[BGE-M3: concept + definition]
    D --> E[Top-K + mandatory identity collisions]
    E --> F[Reuse / new candidate / abstain]
    F --> G[Existing broad family or pending classification]
    G --> H[SQLite checkpoints + local viewer + JSON export]
```

Values do not define identity: `present` and `absent` can belong to one presence
concept. Absence, breakdown, repair and no mention remain distinct. A new value
does not automatically create a new concept. Name collisions are held for review;
exact name-and-definition matches reuse identity without certifying the value.
The first usable assertion bootstraps a **candidate**, not a validated fact.

See [architecture](docs/architecture.md), [input and output contract](docs/data-contract.md),
[evaluation](docs/evaluation.md), [French quickstart](docs/quickstart-fr.md),
[contributing](CONTRIBUTING.md) and [security](SECURITY.md).

## Scope and next work

Included: sequential ontology induction with bounded extraction prefetch, exact
spans, collision guards, broad product families, checkpointed SQLite storage,
metered provider calls, optional complete-link consolidation primitives, a local
viewer and exports. No GPU or Docker is needed for the offline demo.

Not included: automatic production publication, a trained local specialist,
anisotropic boundary learning, a hypergraph retrieval engine, a hosted service,
and a statistically validated benchmark. Consolidation functions are a Python API;
the initial CLI does not run a paid consolidation campaign. Broad families are
seeded; new-family suggestions remain pending. Product prompts/families are the
reference domain, not a claim of plug-and-play performance in every domain.

## Development

```sh
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check src tests
python -m build
```

CI runs on Linux and Windows. Tests mock provider calls, exercise a complete offline
run, verify resume/cache/budget behavior, inspect exact evidence, and check the Amazon
normalizer. Live API accuracy needs separate held-out labels and an explicit budget.

Code and original synthetic fixtures: MIT. Dependencies and third-party datasets
retain their own terms. This repository contains no private source history.
