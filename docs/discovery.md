# How discovery fits into a knowledge pipeline

PILON starts with a model that someone already uses, the facts recorded under that
model, and new source material. A run produces a proposal for a domain owner to
inspect. The commerce implementation uses the store’s category and filters as the
model, product assignments as facts, and incoming feedback as evidence of interest.

| Level | Decision the result supports | Implemented for commerce |
| --- | --- | --- |
| Discovery | Which gap deserves investigation? | Match demand or external observations to product labels absent from the category’s filter list. Inspect source IDs and counts. |
| Forecast | Is the opportunity large enough to evaluate? | Project observed signal volume over a chosen horizon and count catalog items with an uncontested value. |
| Induction | How should we represent it? | Propose a facet vocabulary and candidate assignments. Preserve exact quotations, competing values and products needing evidence. |
| Usage | Where would this change the user experience? | Expand a value in the local preview and export its product IDs for review or an experiment. |

## Integration points available today

- **Inputs.** CSV, JSONL, stdin and Python iterables can carry records from separate systems. The role determines how to interpret a record. A customer request, an external observation and a supplier statement have different implications.
- **Extraction.** Start with labeled product specifications, pass an extractor callable, or import annotations with verified character ranges. Teams can keep model selection and inference budgets in their own jobs.
- **Outputs.** Each run returns a versioned JSON report. A local viewer and portable HTML expose the same snapshot. An approved result can feed the existing merchandising workflow.

## Product direction

Future workflows could read an existing knowledge graph and its evidence through
an adapter, accept ranked structural signals from clustering or TDA, and send
selected candidates for deeper extraction. Evaluation should compare useful
discoveries per reviewed candidate and cost per accepted discovery. The current
release provides a reproducible commerce baseline for that comparison.
