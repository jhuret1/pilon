# Provider configuration

`pilon.providers.load_config(path)` returns the validated version 1 configuration.
`Client(config, transport=None)` constructs an offline client; only an explicit
`client.complete_json(messages, schema=None)` attempts inference. Configuration
checks do not contact providers, inspect model availability, or read API keys.
The examples contain environment-variable names only. Set credentials outside
the repository. A local server needs no dummy key. The client writes no files.

The three examples target OpenRouter, the OpenAI-compatible Chat Completions API,
and local Ollama. Choose a model installed locally or available from your remote
provider. Example remote prices are illustrative estimates, **not current model
prices or a billing guarantee**; set prices for your selected deployment before
execution. Loading an example does not download a model or start a server.

## API contract

```python
from pilon.providers import Client, load_config

config = load_config("configs/openrouter.json")
client = Client(config)
messages = [{"role": "user", "content": "Return a JSON object describing the task."}]
estimate = client.estimate_request(messages)  # offline; no key needed
# Explicit inference, only when the caller is ready to spend its budget:
# result = client.complete_json(messages)
usage = client.report()
```

`messages` is a nonempty list of text-only `role`/`content` objects. Supported
roles are `system`, `developer`, `user`, and `assistant`. The client prepends a
JSON-only instruction. `response_format` defaults to `json_object`; `none` omits
the response-format API parameter but still requires JSON object output.
`json_schema` requires a schema argument whose root type is `object` and sends
`{type: "json_schema", json_schema: {name: "pilon_response", strict: true, schema: ...}}`.
In the other modes, a supplied schema becomes a prompt instruction. The client
validates strict JSON object syntax; the caller validates domain/schema rules.
It never repairs Markdown-wrapped output or falls back to another format.

The API root must include its version prefix (for example `/v1` or `/api/v1`),
without `/chat/completions`; that suffix is appended. Requests send `max_tokens`,
`temperature`, and `stream: false`. Select a model supporting those parameters;
unsupported model capabilities produce an explicit error. The client does not
discover capabilities, change parameters, or retry automatically. OpenRouter
requests also disable provider fallbacks and require parameter support.

All root/section fields in the examples are required except `api_key_env` for
loopback servers and the provider defaults: `response_format=json_object`,
`temperature=0`, `max_output_tokens=3000`, `timeout_seconds=60`. Unknown fields
(including raw keys and custom authorization headers) are rejected. Remote
endpoints require HTTPS and an `api_key_env` reference. HTTP is restricted to
literal loopback addresses or `localhost`. URL credentials, queries, fragments,
and redirects are forbidden. The default transport bypasses proxy environment
settings and uses the standard HTTPS certificate checks.

`ConfigError` extends `ValueError`. `ProviderError` extends `RuntimeError`, and
`BudgetExceeded` extends `ProviderError`. Errors contain no request/response
bodies, URLs, or credential values. Missing credentials fail before an attempt.
Each attempt has the configured HTTP timeout and an 8 MiB response-size limit.
Malformed JSON, duplicate object members, nonfinite numbers, refusals, and any
completion without `finish_reason="stop"` are rejected.

## Limits and usage

One client owns a cumulative request and estimated-cost budget, including failed
attempts. It serializes concurrent calls. `max_input_chars` caps each full JSON
request, including the schema and generated instructions. Before transport, it
reserves:

`(UTF-8 request bytes * input_price_per_million + max_output_tokens * output_price_per_million) / 1_000_000`

The whole request's byte length is a conservative input-token proxy, not a model
tokenizer. Reservations are never refunded, including on timeout or invalid
output. These configured-price estimates are **not a provider billing cap**;
use provider-side spend controls for billing limits. Local estimated prices can
be zero; remote estimated prices must be positive. `max_requests=0` disables
inference. The integration layer enforces `benchmark.max_records` and
`benchmark.max_model_chars`; the provider client validates those values only.

`estimate_request(messages, schema=None)` returns `input_chars`,
`input_tokens_estimate` (UTF-8 bytes), `max_output_tokens`, and
`estimated_cost_usd`. It uses identical request construction without consuming
budget, resolving credentials, or making a request.

`report()` returns safe aggregates:

| Field | Meaning |
| --- | --- |
| `provider`, `model` | Configured kind and model identifier |
| `calls`, `failed_calls` | HTTP attempts and attempts that failed; preflight rejections do not count |
| `input_tokens`, `output_tokens` | Summed provider-reported token pairs, not estimated tokens |
| `provider_cost_usd` | Sum of `usage.cost`, or `null` unless every attempt reported a valid cost |
| `estimated_cost_usd` | Cumulative conservative reservations at configured prices |
| `elapsed_seconds` | Total time spent in attempted calls, including parsing |
| `usage_reported_calls` | Attempts with valid input and output token counts |
| `provider_cost_reported_calls` | Attempts with a valid reported cost |
| `known_provider_cost_usd` | Partial reported cost, or `null` when none was reported |
| `cost_basis` | Explanation of the estimate |

Even local billing remains `null` unless reported explicitly. A reported zero
cost is preserved as zero. Failed completions with readable usage still count
toward reported tokens and cost. No prompts, completions, keys, URLs, or raw
provider metadata are retained in reports.

For offline tests, inject a trusted callable
`transport(request: urllib.request.Request, timeout_seconds) -> (status: int, body: bytes)`.
It must not retry or follow redirects. The request includes transient credentials
when configured; custom transports must not persist them.

## Protocol references

- [OpenRouter structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs)
- [OpenRouter routing controls](https://openrouter.ai/docs/guides/routing/provider-selection)
- [OpenRouter usage accounting](https://openrouter.ai/docs/cookbook/administration/usage-accounting)
- [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
- [Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)
