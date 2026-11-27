# Security and data handling

This alpha is a local research tool, not an authenticated hosted service. The viewer
binds only to 127.0.0.1, rejects unexpected Host headers, provides read-only endpoints
and escapes review text. Do not expose it with a public tunnel or reverse proxy.

Credentials are read only from `OPENROUTER_API_KEY` in the current process environment.
The package does not search parent folders or load `.env` automatically. Provider
authorization headers are not written to SQLite. Raw requests/responses can contain
review text; keep `runtime/` and downloaded `data/` private.

Imports do not execute dataset code. Paid inference requires CLI opt-in and a budget.
Unknown external billing outcomes are retained rather than silently repeated. Source
text may contain prompt injection; it is labeled untrusted, but prompts do not prove
resistance. The fixture test only checks the transport/grounding path.

For a vulnerability, contact the repository maintainer through a private channel
available on the hosting platform. Do not post credentials or private review text in
a public issue. This local source distribution does not configure a private reporting
endpoint; maintainers should enable one before public hosting.
