# Architecture and invariants

The public package is an isolated product-domain extraction of the PILON research
engine. It does not import or read a parent repository, its credentials, runtime
database or accommodation corpus.

| Stage | Implementation | Guarantee / limitation |
|---|---|---|
| Input | Versioned JSON; immutable source strings and IDs | Up to 100 products per alpha batch; source order retained |
| Extraction | LangExtract adapter; one full review per request | Local alignment and exact quote checks; no fuzzy semantic repairs |
| Grounding | Python character offsets `[start,end)` | An exact substring proves provenance, not entailment |
| Embedding | BGE-M3 via OpenRouter; 1024D, L2, float32 | Identity card contains concept and definition, never value |
| Retrieval | NumPy cosine; top eight plus all name/definition collisions | Top-K is a proposal mechanism; it can miss equivalences |
| Routing | Exact reuse, first-candidate bootstrap, otherwise JEV | Values are preserved as extracted, not independently validated |
| Families | Nine seeded broad product scopes; closed choice | A new family is a pending proposal, not automatic expansion |
| Persistence | SQLite WAL + atomic per-review ontology checkpoint | Three extraction threads, ordered routing, bounded prefetch |
| Budget | Transactional reservation per request + usage ledger | Conservative admission bound, not a hard third-party bill cap |
| Export | Atomic JSON + source references | No implicit publication or copying into another corpus |

Fixture vectors use `fixture-hash-v1|1024|l2|float32`; real vectors use
`baai/bge-m3|1024|l2|float32`. Cache keys include this contract and the exact card.
These spaces must never mix. Fixture decisions have no model-validation meaning.

Extraction is parallel; ontology mutations follow source order. The result can
therefore depend on corpus order. A checkpoint commits an entire review and its
ontology changes together. A process lock prevents two runs from mutating the same
database concurrently. The read-only UI does not manage workers.

Provider responses and costs are stored locally. Retrying a known successful call
reuses its cached response. An unconfirmed external outcome blocks automatic retry.
Changing inputs under the same request key fails rather than overwriting a run.

`consolidation.py` contains pair comparison and complete-link grouping primitives:
every cross-pair in a proposed merged group must have an accepted equivalence.
A chain A≈B≈C alone does not imply A≈C. This reduces unsafe merges but can leave
duplicates; threshold changes must be evaluated, not treated as guaranteed fixes.

## Extending the system

Provider protocol: `extract(text)`, `embed(cards)`, `enrich(row, assertion,
candidates, identity_only=True)`, `classify_families(facts, registry)`, and an explicit
`embedding_contract`. Add a contract namespace when representation changes. A
new domain needs prompts, broad family scopes, and held-out evaluation examples.
Never turn a value synonym or a topical neighbor into automatic predicate equivalence.

For scale, the current identity search scans concepts in memory. This is suitable
for bounded research batches, not a demonstrated million-review service. ANN,
incremental ontology snapshots, learned local verification and hypergraph retrieval
are extension points, not concealed dependencies of this quickstart.
