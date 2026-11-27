# End-to-end use case: discovering an emerging maintenance risk

Design sketch. The incidents, counts and costs below are fictional. The runnable
example ships with the [commerce guide](use-case-ecommerce-filter-discovery.md).

## Situation

A manufacturer already operates a governed knowledge graph. It contains equipment,
components, maintenance procedures, failures, and links from validated facts to
their source documents.

The graph already knows:

```text
Seal-17  --partOf-->  Pump-42
Solvent-C  --usedBy-->  Cleaning-Procedure-8
Seal deformation  --canCause-->  Pressure loss
```

It does not contain a relationship between `Solvent-C` and seal deformation.

During three months, new maintenance reports arrive from several sites. The normal
pipeline extracts routine facts and attaches them to the graph. No individual report
is strong enough to justify a new causal relationship.

## Goal

Run PILON as a separate, read-only discovery task. It must find useful information
that is supported by the reports but not already represented in the graph.

## 1. Connect existing knowledge

PILON reads:

- the current model and constraints;
- relevant equipment and maintenance facts;
- the provenance attached to those facts;
- the newly connected reports;
- a checkpoint from the previous discovery run.

It does not copy or replace the canonical graph.

## 2. Scan economically

The `explore` stages use graph statistics, embeddings, cooccurrences, and an optional
TDA plugin. They detect a new cluster around:

```text
Solvent-C → cleaning intervention → seal swelling → pressure loss
```

The cluster appears across 18 reports from 11 independent sources. This is a signal,
not yet a fact.

```json
{
  "kind": "unexplained_cluster",
  "documents": 18,
  "independent_sources": 11,
  "novelty": 0.88,
  "estimated_cost_to_investigate_usd": 0.21
}
```

## 3. Escalate the candidate

The run policy promotes the signal because it crosses the support and novelty
thresholds. A lightweight extractor identifies candidate entities and relations.
Only the relevant passages are sent to the configured structured extractor.

The candidate becomes:

```text
Solvent-C  --mayIncreaseRiskOf-->  Seal deformation
```

PILON does not label the relationship as causal merely because the events cooccur.

## 4. Ground the evidence

The `auditable` route verifies the strongest passages against their exact source
positions. Example:

```json
{
  "document_id": "report:site-b:2026-0412",
  "quote": "The seal was visibly swollen after the Solvent-C cleaning cycle.",
  "start": 284,
  "end": 347,
  "alignment": "exact"
}
```

Every source remains independently inspectable. Duplicate reports and copied text
do not count as independent corroboration.

## 5. Compare with existing knowledge

PILON searches the current graph for:

- equivalent facts and aliases;
- known effects of `Solvent-C`;
- known causes of seal deformation;
- temporal or equipment-specific restrictions;
- evidence contradicting the candidate.

It finds no equivalent relation and one report in which the seal remained intact.
The contradiction is kept in the candidate package.

## 6. Validate the model boundary

The ontology already permits a maintenance material to have a risk relationship
with a failure mode. No schema extension is required. PILON classifies the result as
an `emerging_relation`, not an `ontology_gap`.

If the relation could not be represented, PILON would produce a separate model-gap
proposal rather than silently inventing a predicate.

## 7. Produce the discovery

```json
{
  "kind": "emerging_relation",
  "hypothesis": {
    "subject": "material:solvent-c",
    "predicate": "mayIncreaseRiskOf",
    "object": "failure:seal-deformation"
  },
  "support": {
    "documents": 18,
    "independent_sources": 11,
    "exact_evidence_spans": 14,
    "contradicting_sources": 1
  },
  "knowledge_check": {
    "equivalent_fact_found": false,
    "ontology_compatible": true
  },
  "status": "candidate"
}
```

## 8. Review and return control

A reliability engineer sees:

- the proposed relation;
- supporting and contradicting sources;
- affected equipment;
- the chronology;
- methods and model versions;
- checks already performed;
- estimated operational impact.

The engineer may reject it, request an investigation, or approve it. Approval calls
the customer's existing workflow. PILON itself still does not write directly to the
canonical graph.

## Demonstrated value

This example shows the complete product thesis:

1. PILON uses the customer's existing knowledge rather than rebuilding it.
2. Cheap methods reduce the search space before expensive extraction.
3. Several weak observations become one inspectable multi-source hypothesis.
4. Exact evidence is added only when the candidate deserves promotion.
5. Novelty is checked against existing facts and aliases.
6. Contradicting evidence is preserved.
7. Discovery remains separate from publication.

## Demo acceptance criteria

The public demo is complete only when it can prove that:

- the candidate is absent from the initial graph;
- the discovery disappears when the supporting reports are removed;
- copied reports do not inflate independent-source support;
- every promoted claim links to a valid exact span;
- the graph remains unchanged before explicit approval;
- the exported candidate is deterministic for the bundled fixture;
- the complete demo runs locally without a paid model.
