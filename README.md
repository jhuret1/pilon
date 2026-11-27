# PILON Discovery

PILON finds gaps between what people ask for and what a knowledge system already describes. Its first workflow discovers missing **e-commerce filters** from customer feedback and product evidence.

A runner asks support for “room for my toes.” The store already filters shoes by width. In the sample catalog, **Pace 01** has standard width and a wide toe box, while **Ridge 02** has wide width and a tapered toe box. PILON proposes a *Toe box* filter and shows the listing behind each assignment.

## See it in one command

From the checkout with Python 3.11 or later:

```sh
python -m src.pilon demo
```

Open **runtime/ecommerce-facets.html**. Explore the proposed values and click **wide** to see the matching products. The bundled demo runs offline with the Python standard library. On Windows, double-click **start-local.cmd** to generate and open the same page.

Prefer a local server? Run `python -m src.pilon serve` and open **http://127.0.0.1:8472/**. The JSON result is available at **/api/report**.

## From customer language to a usable filter

| Exploration level | Result in the synthetic running-shoe example |
| --- | --- |
| **Discovery** | 34 observed customer signals across search, chat, reviews and a feedback form point to toe room. A competitor review adds an external observation. |
| **Forecast** | At September's rate, 68 matching signals would occur over 60 days. The default horizon is 30 days. |
| **Induction** | Three observed values form the proposed vocabulary. Four of six products have an uncontested value. One listing needs more information and one product has conflicting sources. |
| **Usage** | Preview the filter, inspect its evidence and hand the proposed product IDs to a merchandising or search pipeline. |

The forecast projects signal volume under a constant-rate assumption. Commercial impact can be measured in a storefront experiment.

## Bring your own data

Install from this checkout with `python -m pip install -e .`. A category snapshot lists current filters, optional aliases and the observation window. A CSV or JSONL feed supplies the records. Channel names come from your own systems.

```sh
pilon discover --model model.json --signals catalog.csv --signals feedback.jsonl --output candidates.json
pilon serve --model model.json --signals signals.csv
```

Use `--signals -` for JSONL on stdin and omit `--output` to pipe the result downstream. Choose `--through discovery`, `forecast`, `induction` or `usage` to stop at the level your job needs.

| Input role | Typical sources | Contribution |
| --- | --- | --- |
| Demand | Site searches, support chats, feedback forms, customer reviews | Observed local demand |
| External | Competitor reviews, third-party feedback | Evidence of an interest to investigate |
| Catalog | Product pages, PIM exports, merchant feeds | Evidence for a specific product and value |

The built-in extractor reads labeled specifications such as `Toe box: wide`. The detector matches labels and optional phrases against feedback. For free-form product prose, pass a custom Python extractor or provide grounded annotations from an existing model job, including LangExtract. PILON verifies the supplied quotes and offsets. [Integration guide and CSV example](docs/use-case-ecommerce-filter-discovery.md)

## Develop and contribute

- [Discovery engine and Python API](src/pilon/facets/) — feed an iterable of records from an existing job.
- [Editable demo inputs](src/pilon/facets/example/) — change the catalog, signals or filter model and rerun.
- [Contribution guide](CONTRIBUTING.md) · [Data handling](SECURITY.md) · [MIT license](LICENSE)
- [Discovery levels and product direction](docs/discovery.md) — where the current workflow fits into an existing knowledge system.
