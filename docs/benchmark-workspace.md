# Benchmark workspace

`pilon loop serve` opens the local **PILON Benchmark** workspace at `http://127.0.0.1:8473/`. Extract and Ingest are separate product surfaces; neither appears as a stage in Benchmark's navigation. Existing job processing and publication commands are unchanged.

## Reading levels

- **Overview:** observed demand, missing attributes, and the largest opportunities.
- **Opportunities:** searchable, channel-filtered and sortable work table, with explicit gap categories.
- **Inspector:** diagnosis, original customer wording with highlighted exact spans, then the definition and technical record.
- **Demand:** original imported texts, including requests without a known intent.
- **Model:** the frozen input model alongside missing attributes proposed by the Benchmark.
- **Sources / history:** observed channel volumes and saved runs. Opening a run does not execute it.

CSV export follows the visible filters. Model export preserves the input JSON. The legacy complete loop report remains available at `/report` or `/reports/JOB_ID`; its CLI export is unchanged.

For a completed schema-only semantic review, the workspace uses a compact catalog view:

- **Suggested filters:** represented attributes with requested values, plus proposals for derived filters. Basic product-type category matches are excluded.
- **Explore:** attributes to document or requested values to verify.
- **Clarify:** unresolved criteria, kept separate from recommendations.

Filter by catalog category to see each recommendation's requested values, distinct source-query count, and next action. The inspector opens with one quotation; further quotations, reasoning and provenance are expandable. CSV export includes recommendation scopes, values, source-query IDs and model references.

The `product_view` is a deterministic projection, not a new inference pass. Groups preserve exact attribute keys and category scopes; derived filters also preserve proposal identity. All original proofs and decisions remain unchanged. Query counts are sample counts, not traffic frequencies, and must not be added across recommendations. These suggestions concern the catalog model, not individual products. Existing storefront filters are not supplied, so a suggested filter is not a claim that it is currently absent.

## Design system

The self-contained assets in `src/pilon/loop/ui/` define the reusable visual system. No external font, charting library, CDN, or model request is required.

| Element | Contract |
| --- | --- |
| Surfaces | White work areas on a cool grey canvas; borders separate data sections |
| Accent | Indigo for navigation and interactions |
| Status | Violet: missing attribute; amber: incomplete coverage; blue: retrieval gap; grey: unresolved |
| Typography | System sans-serif; large headings, readable primary data, subordinate provenance |
| Navigation | Persistent sidebar; compact bottom navigation on mobile |
| Tables | Semantic headings, bounded pages, search and sorting; raw identifiers in the inspector |
| Inspector | Native dialog, keyboard focus containment, Escape, focus restoration, reduced-motion support |
| Evidence | Unmodified source text; highlight only when offsets reproduce the exact quote |

## Measurement boundaries

The headline demand count sums each input record's weight once, within its category and observation window. One record may support several opportunities. Consequently, volumes by opportunity must not be summed as unique demand: the synthetic demo has **62 demand events and 63 candidate associations**.

Coverage uses original model assignments, never subsequent extraction results or the proposed model. Unknown intent is retained. A completed run does not imply an accepted ontology, a published change, measured recall, revenue, or active source connections.

The browser reads a frozen snapshot. Reload or open another saved execution to see a newer one. Missing inputs and unfinished jobs remain explicitly identified; the interface does not substitute demo data.
