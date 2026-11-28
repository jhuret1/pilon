# Product plan: a background knowledge improvement loop

PILON turns recurring user requests into reviewable improvements to a product
model. It runs **Benchmark -> Extract -> Ingest** asynchronously. A customer's
search continues to use the last published snapshot; Benchmark never answers that
customer or changes the live catalog.

## Implementation boundary

Baseline: `07b3f3f`; background-loop v0.3.0a1 integrated on 2026-11-27 under the
[background-loop contract](background-loop-contract.md). Automated tests cover
synthetic end-to-end execution, interrupted work, source replay, publication and
rollback. These checks establish implementation behavior, not real-corpus accuracy.

| Capability | Verified implementation or planned boundary |
| --- | --- |
| Discovery | `facets/engine.py`: catalog-label and alias matching, event counts, constant-rate forecast, grounded assignments, conflicts and unknowns. Preserve `pilon discover`, `pilon demo`, their reports and Python API. |
| Source import | CSV, JSONL, stdin and Python iterables; repeated `--signals`; optional precomputed annotations. These are import interfaces, not connected provider accounts. |
| Extraction baseline | Labeled text specifications or a caller-supplied extractor; exact quote/offset validation. This checks the quote, not the truth of its interpretation. |
| Benchmark | Working-branch `loop/benchmark.py`: configured phrases, explicit filter requests, supplied grounded intents and an unresolved queue. Five focused Benchmark tests passed during documentation review. General semantic induction remains planned. |
| Background loop | `loop/store.py` and `loop/worker.py`: frozen inputs, fenced SQLite leases, checkpoints and candidate-first orchestration. Tests cover new-source replay, cache reuse and failed-job recovery. `loop/projection.py` builds the proposed diff. |
| Publication | `loop/projection.py`: explicit local publish/rollback, atomic writes, revision/base-hash checks and audit history, tested through the CLI. No automatic publication or hosted search integration. |
| Beyond the baseline | Provider polling, general intent discovery, OCR/vision, semantic retrieval, ANN/TDA and storefront experiments are planned. No provider connection or paid inference is included. |

## Decisions that unblock the first product

1. Start with one category, its current model, a complete SKU export, and redacted
   search/support requests. A merchandiser owns the model; a search owner handles
   retrieval defects. Use existing exports before building authenticated connectors.
2. Demand determines what deserves investigation. Keep an actionable request even
   when no product source can answer it. External observations remain a separate
   hypothesis queue and never increase local demand counts.
3. Give each candidate a stable key, definition, aliases and quoted demand evidence.
   Label a seed/alias-based detector explicitly. Unmatched requests remain available
   for review; a finite seed list is not discovery of arbitrary new concepts.
4. Separate the request queue from the product evidence corpus. A support request
   establishes a need; only product-specific evidence can support an assignment.
5. Review an actual schema-and-assignment diff. Missing and conflicting evidence
   stay visible. Publish is a separate explicit action against the same base model.

## Async stage responsibilities

| Stage | Input and output | Completion rule |
| --- | --- | --- |
| Benchmark | Frozen category model plus dated demand; produce ranked candidates with `gap_type`, `demand_events`, quoted `demand_records`, and initial `status: needs_extraction` for defined intents. | Rank by observed events with stable tie-breaking; retain requests with no product match. Current unresolved intents use `needs_definition`. Do not pre-answer the request. |
| Extract | Candidate definition plus product corpus; route assets, then extract assignments and exact source evidence. | Return assignments, conflicts, unknown products, unsupported/skipped assets and measured routing/extraction work. A skipped asset proves nothing about a product. |
| Ingest | Model, candidates and extraction outputs; build a deterministic projection. | Show `schema_changes`, `assignment_changes`, `blocked`, base hash and proposed model. Building a projection never modifies the published snapshot. |
| Publish/revisit | An explicitly reviewed projection, or retained demand replayed with a later product-source snapshot. | Publish only on a matching base hash; retain rollback history. Submit a new job; a product-only export does not automatically recover demand from prior jobs. |

The worker checkpoints completed stages and resumes after interruption. A lease
prevents two workers owning the same job; expiry permits recovery. Enqueue must
freeze model and source contents, including extra source fields, before returning
success. Job completion means a proposal is ready for review, not that it is live.
Pure stage functions leave their inputs unchanged. Replaying retained demand with
updated product sources can resolve an old candidate without another customer
repeating the request. `pilon loop revisit JOB_ID --signals new-source.jsonl` loads
that job's retained demand and adds new immutable source records. `loop watch`
detects changes in local exports; provider polling and cross-job automatic backlog
reconciliation are separate integrations.

## Diagnose the gap before changing the model

| `gap_type` | Required distinction | Product action |
| --- | --- | --- |
| `schema_gap` | The requested property cannot be represented by the current model and its definitions/aliases. Example: toe-box shape differs from overall shoe width. | Propose a definition and supported values/assignments. With zero evidence, current projection retains a blocked candidate; schema-only publication is not implemented. |
| `coverage_gap` | The property already exists, but relevant SKUs lack accepted assignments. | Extract missing values under the existing key. Do not create a duplicate facet. |
| `retrieval_gap` | The property and accepted product facts exist, but evidence from the serving search shows that users cannot retrieve them. | Hand off an alias/index/ranking fix to search; evaluate against the published snapshot before changing retrieval. |
| `unresolved_intent` | The request is ambiguous, out of scope, unmatched by the detector, or available evidence cannot distinguish the above cases. | Retain the request, evidence and review reason; ask the domain owner to define it or obtain missing evidence. |

Use model definitions and accepted assignments, not a matching word alone, to
distinguish schema from coverage. Zero results or an existing facet name alone do
not establish a retrieval gap: require query/filter context, serving model/index
version and returned product IDs or a replay. Without that telemetry, flag a
suspected issue for review. Mixed cases need a primary diagnosis plus documented
follow-up work; the four values are not a claim of exhaustive automatic diagnosis.

Current Benchmark uses assignment presence across supplied inventory plus a demand
`outcome` of `no_results`, `unsatisfied` or `unavailable_filter` to label a retrieval
gap. Treat that output as a hypothesis: it does not verify the serving index, a
requested value, relevance or causal failure. The worker hands it off without
product extraction. Definitions/alias identity and telemetry-based diagnosis need
stronger validation before this classification can be trusted automatically.

## Acceptance gates for the local loop

- **Compatibility and locality:** existing Discovery tests pass unchanged; both
  demos run with the Python standard library, without network access or credentials.
- **Demand survives:** a request for a new property produces a retained candidate
  with no matching product source. A later snapshot with supporting evidence yields
  a proposed assignment. An unrecognized request is inspectable, not silently lost.
- **Correct gap handling:** fixtures cover an absent property, an existing property
  with missing values, proven retrieval failure, and ambiguous intent. No duplicate
  facet is proposed for an existing property; heuristic diagnoses remain visible.
- **Evidence:** every proposed assignment points to the same SKU and a verified
  source slice. Invalid quotations cannot enter a projection. Contradictory values
  remain blocked; explicit `no` stays distinct from unknown. Images require an
  explicit adapter, and skipped/unsupported assets stay in the report.
- **Counts:** replaying identical IDs changes no counts; conflicting versions under
  one ID fail clearly. Date windows are inclusive. External observations and catalog
  records add zero demand events. Coverage uses distinct in-scope SKUs, not assets.
- **Recovery and review:** interrupt after a completed stage, restart without
  recomputing it, and obtain the same proposal. The viewer shows before/after schema,
  assignments, evidence, unknowns and review status. A stale base blocks publication;
  rollback restores the chosen prior snapshot and records the action.

## Measurable first experiment

Proposed pilot, not measured results: one consenting catalog owner, one category,
a four-week demand window, at least 200 distinct redacted request records and 50
in-scope SKUs if available. Freeze all inputs. Have a domain owner label a random
request sample plus the top-volume requests, identify actionable intents and gaps,
and adjudicate product evidence. Report sample sizes if fewer are available.

Compare old Discovery, the background seed/lexical baseline, and exhaustive
extraction using the same extractor and corpus. Tune aliases on an earlier window;
hold out the last week. Include unseen vocabulary and requests with no matching
product text. Reviewers label demand independently of the seed list. Exhaustive
extraction measures routing misses, not semantic truth; human review supplies that.

| Measure | Definition and proposed pilot gate |
| --- | --- |
| Useful proposals | At least 80% of the top 20 reviewed candidates are actionable, distinct needs; report the actual denominator. |
| Demand coverage | Report intent recall against independently labeled requests, both event-weighted and unweighted, with unseen intents separate. Unknown detector output counts as a miss until reviewed. No seed-demo recall claim. |
| Assignment quality | At least 95% of reviewed assignments are judged supported; 100% have valid quotes/SKU linkage. Report all conflicts and unknowns separately. |
| Routing tradeoff | Target at least 95% of supported candidate/SKU/value triples found by exhaustive extraction while extracting at most 50% as many assets. Report actual workload and elapsed time; if the target fails, use exhaustive extraction for this corpus. |
| Operational value | Record review minutes per accepted proposal, accepted proposals per run, extraction calls and measured elapsed time. Optional adapters report actual cost separately; no hypothetical savings. |

These are provisional go/no-go targets. Show counts and uncertainty; a small sample
does not establish production reliability. After an approved model and search
integration exist, pre-register a storefront experiment with successful product
finding as the primary metric and zero-result rate/latency as guardrails. Determine
sample size from the site's baseline. Event forecasts do not establish conversion
uplift, revenue or unique-user demand.

## Delivery order and limits

First ship the restartable local loop and reviewable diff. Next validate one real
pair of demand/product exports, then add the highest-value incremental adapters
described in [Source connectors](source-connectors.md). Add retrieval telemetry
before promising reliable retrieval-gap diagnosis. Add document/image extraction
and semantic routing only when the lexical baseline's measured misses justify them.

Current Discovery starts from supply labels and can miss demand with no labeled
product evidence. Seeds and aliases improve reproducibility but bound what the new
detector can recognize. Lexical routing misses paraphrases, languages and relevant
assets below `top_k`; it does not prove entailment. General intent induction, TDA
and ANN remain experiments until benchmarked against these baselines.
