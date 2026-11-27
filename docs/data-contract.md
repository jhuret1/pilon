# Corpus and evidence contract

```json
{
  "schema_version": "pilon-corpus-v1",
  "synthetic": false,
  "provenance": {"name": "Your permitted product review sample"},
  "items": [{
    "id": "product-1",
    "title": "Example lamp",
    "reviews": [{"id": "review-1", "text": "No cable was included.", "language": "en"}]
  }]
}
```

Item IDs and review IDs are unique within the input. Each item has 1–2000 nonempty
reviews, each at most 50000 characters. The alpha batch contains 1–100 items.
Text is not translated or stripped before alignment. Optional `source_order` lists
all review IDs exactly once when input order interleaves products. No semantic
deduplication or averaging of reviews is performed.

An assertion keeps `quote`, `start`, `end`, `attributes`, `review_index`, `route`,
`fact_id`, `embedding_id`, `candidates`, `answers`, `proof_status` and
`qualification_status`. Resolve the review index against the frozen `rows` array
to get the original item ID, review ID, text and provenance.

Attributes separate `concept`, `definition`, `family`, `value`, `presence`,
`condition`, `subject`, `temporality`, and optional exact `context`.

| Dimension | Allowed values |
|---|---|
| presence | present, absent, unknown, not_applicable |
| condition | working, broken, resolved, unknown, not_applicable |
| subject | reviewed_item, other_item, advertisement, unknown |
| temporality | during_use, past, resolved, unknown |

An absent component cannot simultaneously be working, broken or repaired.
Assertions about another product, an advertisement or an unknown subject remain
inspectable but do not populate the reviewed-product ontology. No mention should
produce no assertion; it must not become `absent`.

Exact spans use Python Unicode character indices, not UTF-8 byte offsets. An
incorrect interval can be repaired only when the **unchanged literal quotation
occurs exactly once** in the review. Multiple occurrences cannot be guessed.
The contextual quotation must also be present verbatim.

`proof_status=exact_span` and `qualification_status=not_revalidated` intentionally
coexist. The first is a deterministic source check; the second indicates that the
meaning/value has not undergone an independent entailment audit. Observed `values`
on a concept are not a validated enum contract.
