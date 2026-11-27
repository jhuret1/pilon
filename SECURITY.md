# Security and data handling

The bundled workflow processes data locally. Reports preserve source text, channel labels, record IDs and matching product IDs. Apply the access controls of the original feed when saving or sharing JSON or HTML. Use redacted or aggregated customer feedback wherever possible.

The optional preview server binds to loopback and serves a fixed HTML report and its JSON representation. It accepts local hostnames and read-only requests. The HTML export escapes input text and works offline.

A custom extractor executes as application code with the permissions of the calling job. Its operator controls any external model calls and the data sent to them. Input records are data and cannot select executable code.

Report vulnerabilities privately to the repository maintainer. Use synthetic records in public issues.
