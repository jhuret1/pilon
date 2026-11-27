# PILON

Find the filters shoppers ask for and see which products your catalog can substantiate.

A shopper wants room for their toes. Your running-shoe store already filters by width.
One standard-width shoe has a wide toe box, while a wide shoe has a tapered one.
PILON compares customer language, product specifications and current filters, then
builds a filter preview with a source for each product assignment.

## Try it locally

From the repository root with Python 3.11 or later:

```sh
python -m src.pilon demo ecommerce-facets
```

Open **runtime/ecommerce-facets.html**. The example runs offline using the Python
standard library. Expand **wide** in the Usage section to see the two matching
products. Expand the citations in Induction to inspect what their listings say.

| Stage | What the bundled example shows |
| --- | --- |
| Discovery | 34 customer signals mention toe room in September. A competitor review supplies additional vocabulary. |
| Forecast | At September's rate, the next 30 days would bring 34 signals. Four of six products have an uncontested value in this snapshot. |
| Induction | Propose **Toe box** with three observed values. Keep one conflicting product and one undocumented product for review. |
| Usage | Preview **wide** on Pace 01 and Tempo 03. Export the candidate and product IDs for a merchandising decision. |

All names and counts are synthetic. The forecast estimates signal volume under a constant-rate assumption. The filter's effect on sales would need a storefront experiment.

## Use your own data

Install the CLI with `python -m pip install -e .`. Supply a category model and a
feed of records. The channel name is yours. Search logs, support chats, feedback
forms, store reviews, external reviews and product pages fit the same feed.

```sh
pilon discover --model model.json --signals signals.csv --output candidates.json
```

Use `--signals -` to stream JSONL from an existing job. Omit `--output` to return
JSON on stdout. Add `--through discovery` for signals alone, `--horizon-days 60`
for a different forecast window or `--html preview.html` for local review.
The usage stage exports a preview for your PIM or search team to approve.

The built-in detector finds explicit specification labels present in product text
and referenced in customer language. Existing filter names and configured aliases
are checked after normalization. Free-form catalog text can use your own extractor
through the Python interface. [Input contract and integration example](docs/use-case-ecommerce-filter-discovery.md)

## Repository

| Location | Use |
| --- | --- |
| [Commerce module](src/pilon/facets/) | Discovery stages, CLI adapters and standalone review page |
| [Runnable example](src/pilon/facets/example/) | Editable category model and synthetic multichannel feed |
| [Tests](tests/test_facets.py) | Replays, provenance, known filters, forecasts and conflicting sources |
| [Ontology workbench](docs/ontology-workbench.md) | Earlier induction experiment, local viewer and optional provider adapter |

For contributions, start with a small feed that reproduces a missed filter or an
incorrect assignment. Include the expected result and the passage supporting it.
[Contributing](CONTRIBUTING.md) · [License](LICENSE)
