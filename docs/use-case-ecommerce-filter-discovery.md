# Discover a missing filter from commerce exports

From the repository root, run the same pipeline as the bundled demo against editable files.

```sh
python -m src.pilon discover --model src/pilon/facets/example/model.json --signals src/pilon/facets/example/signals.jsonl --horizon-days 60 --output runtime/candidates.json --html runtime/filters.html
```

## Inputs

Use one snapshot per category. The model lists its existing filter labels, the inclusive
observation window for demand, and optional phrases that map customer language to
a catalog label. Delete the aliases in the example and the literal phrase “toe box”
still yields a candidate. Keep all products in the snapshot to calculate coverage.

Every record has a stable `id`, a `category`, a `role`, a channel name in `source`
and the original `text`. Map your CRM, PIM or analytics export to these columns.
Repeat `--signals` to read separate files in one run, for example
`--signals catalog.csv --signals chat.jsonl --signals searches.csv`. Prefix IDs
with a source namespace when two systems use the same local ID.
Identical records sharing an ID count once. Conflicting versions under one ID
raise an error. Use distinct IDs for distinct records and pseudonymous aggregates
for demand. Counts refer to events and may include several events from one shopper.

| Role | Extra fields | Example |
| --- | --- | --- |
| `demand` | `date` in YYYY-MM-DD format, optional positive integer `count` (default 1) | Query counts, a chat question, onsite review or form feedback |
| `external` | None | Competitor review or syndicated feedback used as context |
| `catalog` | `product_id` | Product page or supplier feed with one `Label: value` specification per line |

For existing filters, list their canonical names in `existing_facets` and any alternate
labels in `aliases`. Export zero, one or several catalog records per known product as
appropriate; include at least a description record for every product you want in the
denominator. Deduplicate overlapping demand exports upstream when their IDs differ.
The HTML and JSON reports include matching source text and inherit its access requirements.

## A minimal CSV integration

Save this as `signals.csv` and use the bundled category model:

```csv
id,category,role,source,text,date,count,product_id
q1,running-shoes,demand,search,wide toe box,2026-09-18,12,
c1,running-shoes,demand,support_chat,room for my toes,2026-09-19,1,
x1,running-shoes,external,competitor_review,I like a roomy toe box,,,
p1,running-shoes,catalog,pim,Toe box: wide,,,SKU-01
p2,running-shoes,catalog,pim,Width: wide,,,SKU-02
```

This yields 13 demand events, one external reference and one assignable SKU out
of two. The external review contributes context. The assignment for SKU-01 comes
from its own PIM record.

## Exploration levels

1. **Discovery** extracts potential labels from the supply side and checks customer
   text for those labels or their configured phrases. It skips existing filters and
   orders proposals by observed demand. External feedback can also surface a filter
   with supply-side evidence. Those proposals carry an external-only flag and have
   no local demand projection until customer signals arrive.
2. **Forecast** multiplies matching events by `horizon_days / window_days` and
   reports present catalog coverage. The bundled 30-day window contains 34 signals.
   A 60-day projection gives 68, assuming the observed rate holds.
3. **Induction** collects observed values and product assignments. Evidence includes
   the source record ID, quote and half-open Unicode character range. Disagreement
   stays inspectable. Missing evidence leaves a product unassigned.
4. **Usage** groups uncontested product IDs by value. Inspect a value in the HTML
   preview or read `candidates[].usage.product_ids_by_value` from JSON. An approved
   mapping can enter your normal indexing or experimentation workflow.

## Plug in another source or extractor

After installation a job can pass a generator of dictionaries directly:

```python
from pilon import explore

def run_catalog_job(category_model, incoming_records):
    return explore(category_model, incoming_records, through="usage", horizon_days=60)
```

For other catalog formats, pass `extract_specs=your_callable` to `explore`.
It receives one source text and yields `Spec(label, value, start, end)` with offsets
into that text. The engine stores the exact slice. The extractor is responsible for
the interpretation. This lets a team reuse its own parser or model behind the same
evidence contract. The supplied detector uses deterministic phrase matching.

For precomputed annotations, a JSONL catalog record may carry an `extractions`
array alongside its original `text`. For example, export the character interval,
extracted text and two attributes from a LangExtract job configured with label
and value attributes:

```json
{"id":"feed-7","role":"catalog","source":"enrichment_job","category":"running-shoes","product_id":"SKU-07","text":"Room for toes.","extractions":[{"extraction_text":"Room for toes","char_interval":{"start_pos":0,"end_pos":13},"attributes":{"label":"Toe box","value":"wide"}}]}
```

When the field is present, the supplied annotations replace parsing for that
record. PILON checks the quote against its offsets before using the supplied value.
The source passage can be inspected during review of the proposed interpretation.
