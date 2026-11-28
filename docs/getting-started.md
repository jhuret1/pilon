# Your catalog has blind spots.

A customer asks for shoes with removable insoles. Can your catalog describe that need? PILON compares customer requests with your catalog structure, shows possible gaps, and lets you investigate selected proposals with product evidence.

**Start with one question. Follow its evidence. Review the change.**

| Choose your route | What you need | What you get |
| --- | --- | --- |
| **[1. Explore the offline demo](#route-1-explore-the-offline-demo)** | Python and this checkout | A synthetic example across Benchmark, Extract and Induct. No model service or API key. |
| **[2. Use your own catalog and requests](#route-2-use-your-own-catalog-and-requests)** | Catalog structure, request exports and a model configuration | A semantic Benchmark review. Preview locally before enabling inference. |

## Set up the cloned repository

Open a terminal in the project folder containing `pyproject.toml`. Use **Python 3.11+**, and run all commands on this page from that folder:

```sh
python -m pip install -e .
```

Installation may download packaging tools. The demo itself runs offline. If you cannot install, use the no-install option below.

## Route 1: Explore the offline demo

```sh
pilon start --demo
```

Open **[/start](http://127.0.0.1:8473/start)** at the printed local address, then open the demo run. The example uses synthetic requests and product sources, with local rules rather than model calls.

Each workspace answers a different question:

| Workspace | Look for |
| --- | --- |
| **Benchmark** — What is missing? | Represented needs, proposed attributes or values, and requests that need clarification. |
| **Extract** — What can the products prove? | Source quotations, product assignments, conflicts and unknowns. |
| **Induct** — What would change? | The proposed catalog structure and assignment changes before publication. |

The demo prepares a local projection; nothing is published. Keep the terminal running while you browse. Press **Ctrl+C** to stop it before switching routes.

<details>
<summary>No installation or browser server: save an offline report</summary>

From the same project folder, with Python 3.11+:

```sh
python -m src.pilon loop demo
```

Open `runtime/background-loop.html`. The accompanying data is in `runtime/background-loop.json`. This uses the checkout directly and makes no inference calls.

</details>

## Route 2: Use your own catalog and requests

Start the local guide with a separate workspace:

```sh
pilon start --db runtime/my-benchmark/jobs.sqlite
```

Open **[/start](http://127.0.0.1:8473/start)**. Keep this terminal running and use a second terminal in the same project folder for the commands below. The pages help prepare configuration and commands; you run those commands yourself.

### Prepare your own files

Save these three files in the project folder:

| File | Contents |
| --- | --- |
| `model.json` | Your **catalog model**: categories, stable attribute keys, definitions and full observed value lists. |
| `requests.jsonl` | Customer requests, one JSON object per line. CSV with the same field names as headers also works. |
| `pilon.config.json` | Your **inference model** connection: endpoint, model identifier and run limits. |

Start with a small set of representative requests. The supplied configurations allow up to **20 records** per run; larger inputs require an explicit scope or limit change. The complete catalog model must fit the configured context.

<details>
<summary>Copy a minimal catalog model and two requests</summary>

This synthetic `model.json` describes the catalog structure only:

```json
{
  "category": "running-shoes",
  "version": "example-v1",
  "synthetic": true,
  "assessment_scope": "schema_only",
  "observation_period": "unknown",
  "demand_unit": "sampled_queries",
  "categories": [],
  "facets": [
    {
      "key": "width",
      "label": "Width",
      "definition": "Overall shoe width, not space around the toes.",
      "values": ["standard", "wide"],
      "values_status": "observed_not_exhaustive"
    }
  ],
  "assignments": []
}
```

Save `requests.jsonl` without an enclosing array:

```jsonl
{"id":"request-1","category":"running-shoes","role":"demand","source":"synthetic_example","text":"wide running shoes","count":1}
{"id":"request-2","category":"running-shoes","role":"demand","source":"synthetic_example","text":"running shoes with a removable insole","count":1}
```

Replace the examples with your real data and remove the synthetic flag. Keep immutable record IDs and unchanged source text. The model and records must share the same `category`. An empty `categories` array means no product taxonomy was supplied.

Here each row is one sampled request. `schema_only` with an unknown observation period permits undated requests and no product assignments. Preserve the actual meaning of dates and event counts when using measured demand. This review alone cannot establish product availability or coverage. See the [source record guide](source-connectors.md) for broader feeds.

</details>

### Choose the inference connection

Download `pilon.config.json` from **[/connectors](http://127.0.0.1:8473/connectors)**, or copy and customize an [OpenRouter](../configs/openrouter.json), [OpenAI-compatible](../configs/openai-compatible.json) or [local Ollama](../configs/local-ollama.json) template. Save it in the project folder.

Set the endpoint and model for your setup. Hosted providers use an API key stored in the named environment variable; Ollama needs an already running local service and model. The **[model connector guide](model-connectors.md)** covers credentials, limits and resume.

### Preview, then run

```sh
pilon benchmark run --model model.json --signals requests.jsonl --config pilon.config.json --output-dir runtime/my-benchmark --db runtime/my-benchmark/jobs.sqlite
```

This is a **dry run**: no API key, model request or Benchmark job. Check the record count, model size and estimated requests/cost. A preview does not test endpoint availability or credentials.

When ready, enable inference explicitly:

```sh
pilon benchmark run --model model.json --signals requests.jsonl --config pilon.config.json --output-dir runtime/my-benchmark --db runtime/my-benchmark/jobs.sqlite --execute
```

Execution sends the complete catalog model and each selected request record to your configured endpoint. For a hosted service, prepare inputs suitable for sending there. Configured prices drive estimates, not a guaranteed billing cap.

### Review in Benchmark

Return to [/start](http://127.0.0.1:8473/start), refresh, and open the completed run matching the printed job ID. The server and command above use the same database.

Review represented needs, proposed attributes or values, and unresolved requests. Exact quotation and model-reference checks keep the review traceable; they do not guarantee correct interpretation. **This command stops at Benchmark.**

## Follow one proposal into product evidence

Once a proposal is worth investigating, supply product sources from the same dataset and select its exact candidate key. **[Select proposals explicitly](tools-and-connectors.md#select-proposals-explicitly)** provides the commands and a source-record example.

**Extract** checks product evidence. **Induct** shows the proposed change. Publication is a separate local action; connecting a PIM or storefront requires your own integration.

For a larger offline example, follow the [Home Depot replay](home-depot-example.md). It reuses supplied reviews for 1,000 requests and local CSVs; it makes no new inference calls and is not an independent accuracy test.
