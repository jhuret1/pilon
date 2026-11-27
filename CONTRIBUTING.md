# Contributing

Start with the offline quickstart and tests. Small, reproducible contributions are
welcome: independent evaluations, retrieval/collision failures, evidence alignment,
language coverage, alternative adapters and clearer inspection tools.

Use fictional text or a permitted public dataset reconstruction script in bug
reports. Do not attach customer reviews, identifiers, API keys, `.env`, raw provider
logs or a runtime database. Include version, platform, minimal reproducer, expected
behavior and actual behavior. Clearly distinguish accuracy measurements from fixture
tests and model-agreement estimates.

Before proposing changes, run `python -m pytest`, `python -m ruff check src tests`
and `pilon demo --no-serve`. New providers must preserve source IDs, exact quotations,
budget accounting and failure semantics. Changes to an embedding contract need a
new cache namespace. Never promote an ontology silently on page load or import.

The repository is distributed under MIT; contributions should be compatible with
that license. External dataset text must retain its own terms.
