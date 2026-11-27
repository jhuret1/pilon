# Contributing to PILON Discovery

Start with `python -m src.pilon demo`. Edit the example under `src/pilon/facets/example/` and rerun the command to see how a new signal affects the proposal.

A good issue includes a small fictional category model, a few input records, the observed result and what you expected. For a proposed product assignment, include the source text and its character range. For a forecast, include the observation dates, count and desired horizon.

Adapters can yield records from an existing data job. Catalog extractors implement a Python callable returning `Spec(label, value, start, end)`. Keep source IDs stable across replays and cover disagreement, missing evidence and duplicate records. [Integration guide](docs/use-case-ecommerce-filter-discovery.md)

Install development tools with `python -m pip install -e ".[dev]"`. Run `python -m pytest -q`, `python -m ruff check src tests` and `python -m build` before submitting a change. Keep examples synthetic or use redistributable data with an explicit license.
