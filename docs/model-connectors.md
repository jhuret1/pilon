# Configure a model for Benchmark

Use a model connection when you want PILON to interpret **new customer requests** against your own schema. It produces grounded semantic reviews for Benchmark. Product-source extraction, model publication and storefront integration remain separate steps.

The built-in client uses Python's standard library to send non-streaming chat-completion requests. You choose the endpoint and model in JSON. No provider SDK or API key is needed to load a configuration or preview a run. [Client implementation](../src/pilon/providers.py).

## Choose a connection

| Configuration | Use it for | What you must prepare |
| --- | --- | --- |
| [OpenRouter](../configs/openrouter.json) | A hosted model reached through OpenRouter | A model ID supported by your account, an API key environment variable, and current price estimates |
| [OpenAI-compatible](../configs/openai-compatible.json) | Another service exposing compatible chat completions | Its API root, model ID, credentials and supported JSON response mode |
| [Local Ollama](../configs/local-ollama.json) | A model served locally through Ollama's compatible `/v1` API | A running local service and an already available model; PILON does not install or download either |

The endpoint must accept the configured model, output-token limit and response format. “Compatible” describes the protocol PILON sends; it does not guarantee every backend supports every option.

For an initial comparison, choose a small, bounded set of representative requests. A model selected for lower cost or shorter latency may be sufficient for straightforward language; a larger model may be worth evaluating for ambiguity or more complex constraints. These are choices to measure, not promises about a particular model. Local inference keeps calls on your chosen local endpoint but still requires compute, memory and model maintenance.

Include aliases, units, ambiguous requests and already represented constraints in your evaluation. Compare useful proposals and review effort alongside usage and latency. A model name or parameter count is not an accuracy result.

## Preview first

From an installed checkout, use the bundled synthetic model and four requests:

```sh
pilon benchmark run --model src/pilon/facets/example/benchmark-model.json --signals src/pilon/facets/example/benchmark-requests.jsonl --config configs/openrouter.json --output-dir runtime/my-benchmark --db runtime/my-benchmark/jobs.sqlite
```

This is a **dry run**. It prints a JSON summary without contacting the endpoint, creating a job or writing output files. Check `records`, `cached_reviews`, `pending_reviews`, model size, observed-value count and the request/cost estimates, then substitute your files using the [input guide](getting-started.md#prepare-your-own-files). To preview local inference instead, change `--config` to `configs/local-ollama.json`. A successful preview does not establish model availability or valid credentials.

Copy a configuration before customizing it, or download one from the read-only `/connectors` form. The form creates the file in your browser; it does not save a server setting or test the connection. Unknown fields are rejected. The configuration has four top-level objects/fields: `version`, `provider`, `limits` and `benchmark`. See the [configuration contract](../configs/README.md) for the lower-level client API.

## Provider settings

| Field | Meaning |
| --- | --- |
| `version` | Configuration format version; currently `1`. |
| `provider.kind` | `openrouter`, `openai_compatible` or `ollama`. |
| `provider.base_url` | API root, without `/chat/completions`. The client appends that path. Use the compatible `/v1` root for the local Ollama example. |
| `provider.model` | Exact model identifier recognized by your endpoint; edit the template to match your setup. |
| `provider.api_key_env` | Name of an environment variable, never the secret itself. Required for remote endpoints; optional on loopback. |
| `provider.response_format` | `json_object`, `json_schema` or `none`. The default is `json_object`. `none` omits the transport response-format field but still requests and validates JSON. |
| `provider.temperature` | Finite value from 0 to 2; default `0`. This does not guarantee deterministic semantic judgments. |
| `provider.max_output_tokens` | Requested completion limit; default `3000`. An incomplete/truncated completion is rejected. |
| `provider.timeout_seconds` | Transport timeout per attempt; default `60`. |

Remote endpoints require HTTPS. Plain HTTP is allowed only on loopback. URLs containing embedded credentials, query parameters or fragments are rejected. The client does not automatically retry or follow redirects; the OpenRouter request also disables provider fallback.

Set the environment variable named in your configuration before execution. For the OpenRouter example, enter the key privately in your current shell, or use your usual secret-management process.

Bash:

```bash
read -r -s -p "OpenRouter API key: " OPENROUTER_API_KEY
export OPENROUTER_API_KEY
```

PowerShell 7:

```powershell
$env:OPENROUTER_API_KEY = Read-Host "OpenRouter API key" -MaskInput
```

For another configuration, use its `api_key_env` name. The local Ollama template needs no dummy key. Do not place an actual API key in JSON or source files. Loading the configuration and dry runs do not read credentials; the client looks up the variable when making a request.

When executing against a hosted service, the complete model JSON and each selected demand record are sent to that endpoint, including any attached fields. Remove material that should not leave your environment before preparing the input files, or choose an appropriate local deployment. Caches and reports retain source text locally and need the same access controls as those inputs.

## Limits and cost estimates

| Field | What it bounds |
| --- | --- |
| `benchmark.max_records` | Number of demand records allowed in a run; the supplied starting configurations use `20`. Larger inputs are rejected, not silently sampled. |
| `benchmark.max_model_chars` | Serialized model context. Full attributes and observed values must fit; they are not silently truncated. |
| `limits.max_input_chars` | Complete serialized request, including JSON instructions and the response schema. |
| `limits.max_requests` | HTTP attempts made by the client, including failed attempts. There are no hidden automatic retries. |
| `limits.max_estimated_cost_usd` | Estimated-spend guard checked before a request is sent. |
| `limits.input_price_per_million` | Your estimated input-token rate. |
| `limits.output_price_per_million` | Your estimated output-token rate. |

Model and request limits are measured in **characters**, not a provider's advertised token context window. Choose values that also fit your backend. Reducing the number of demand records does not shrink the model context sent with a record. If your schema is too large, prepare a genuinely scoped model and corresponding requests, or use a suitable endpoint and explicit larger limits; do not drop values and treat their absence as a model gap.

The client conservatively estimates input tokens from the serialized request's UTF-8 byte length and reserves the configured maximum output tokens. It applies your configured rates to that estimate. Reservations remain consumed after a timeout or invalid response. These are local planning and execution guards, **not a guaranteed billing cap**. Provider billing, tokenization and ancillary charges may differ.

Update rates yourself against your provider's current terms; PILON does not fetch pricing. The OpenRouter template's `0.1` input and `0.4` output rates are manually configured estimates per million tokens, not verified current prices. Remote configurations require positive input and output rates. A local configuration may use zero provider rates; that does not mean local compute is free.

Usage reporting separates call counts, failed calls, reported token totals, estimated cost and provider-reported cost. An absent or incomplete provider cost is `null`, not a zero-cost claim. Token totals cover reported usage only; the client exposes how many calls supplied usage and cost. Review your provider's billing records for actual charges. General custom extractor hooks do not automatically gain these controls.

## Execute and resume

Add `--execute` to authorize inference for that invocation:

```sh
pilon benchmark run --model src/pilon/facets/example/benchmark-model.json --signals src/pilon/facets/example/benchmark-requests.jsonl --config configs/openrouter.json --output-dir runtime/my-benchmark --db runtime/my-benchmark/jobs.sqlite --execute
```

The runner makes one review request per uncached demand record. Each review must preserve exact source quotations and Python character offsets. Existing fact keys, matched values and category references must exist in the supplied model. Unsupported criteria, including invalid spans or references, become explicit `unresolved` criteria; valid criteria in the same response are retained. The completed run reports `invalid_criteria`. Transport failures, malformed JSON and incomplete completions stop execution with a safe checkpoint. These checks establish structural/source validity, not that the model's interpretation is correct.

The checkpoint ties record reviews to the full model hash, records hash, configuration hash and prompt version; each record also has input and review fingerprints. Re-run the same command with the same output directory to reuse validated work. Changed inputs, configuration or prompt version are rejected against that checkpoint: choose a new output directory for a new run. A new directory starts new work and does not erase prior provider charges.

Saved sessions retain cumulative attempts and estimated spending, which are deducted when resuming the same run. Normal failures preserve completed reviews for reuse. An interruption during an in-flight request has an unknown remote outcome and blocks automatic resume until reconciled; a stale run lock likewise requires checking the previous process. Do not assume that an interrupted request was unbilled. Inspect the printed usage and cache information when resuming.

Execution writes these local artifacts:

| File | Contents |
| --- | --- |
| `checkpoint.json` | Input identities, record reviews, validation counts, session usage and resume state |
| `reviews.json` | Complete validated reviews and inference accounting |
| `annotated-signals.jsonl` | Original demand records with attached semantic reviews |
| `benchmark.json` | Completed Benchmark snapshot |

The examples explicitly select `runtime/my-benchmark/jobs.sqlite` for the job database; it is separate from the JSON/JSONL exports. A `run.lock` prevents concurrent execution in the same output directory. See the [runner](../src/pilon/model_review.py) and [CLI](../src/pilon/model_commands.py).

A completed semantic run creates a **Benchmark-only** job and prints its database/job details. For the examples above, use `pilon start --db runtime/my-benchmark/jobs.sqlite` to view that workspace. To inspect selected product evidence later, explicitly use [`pilon loop enrich`](tools-and-connectors.md#select-proposals-explicitly). Neither execution nor opening the UI publishes a model.

## If a run stops

| Symptom | Next action |
| --- | --- |
| Missing API-key variable | Set the variable named by `provider.api_key_env` in the environment used to execute PILON. |
| Model or request context exceeds the configured limit | Check the complete schema size, backend context and intentional scope; the runner will not silently remove values. |
| Request or estimated-cost limit would be exceeded | Review the preview and rates, then reduce the batch or deliberately adjust the configuration. |
| Endpoint rejects the model or JSON response mode | Check the endpoint/model settings and use a response mode that backend supports. |
| Invalid quote, reference, JSON or incomplete output | Inspect the failed record and model settings. Do not turn invalid output into an accepted review by inventing source evidence. |

The supplied Home Depot benchmark is a different path: it replays existing agent reviews with no inference calls. Its 1,000-request results are not performance or accuracy measurements for these connectors. See [the reproducible example](home-depot-example.md).
