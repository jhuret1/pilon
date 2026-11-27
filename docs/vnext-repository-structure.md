# Proposed vNext repository structure

The repository should remain a single Python package until scale forces a split.
The public surface is a small CLI, a Python API, and stable plugin contracts.

```text
pilon/
├── README.md
├── pyproject.toml
├── src/pilon/
│   ├── cli.py                 # Thin command layer
│   ├── config.py              # Validated project and run configuration
│   ├── models.py              # Canonical documents, facts, evidence, candidates
│   ├── pipeline.py            # Run orchestration and checkpoints
│   ├── policy.py              # Profile, cost, privacy and escalation decisions
│   ├── registry.py            # Plugin discovery and capability matching
│   ├── connectors/            # Sources and knowledge systems
│   │   ├── files.py
│   │   ├── rdf.py
│   │   └── neo4j.py
│   ├── discovery/             # Candidate generation
│   │   ├── rules.py
│   │   ├── graph.py
│   │   ├── semantic.py
│   │   └── topology.py
│   ├── extraction/            # Entity, relation and claim extraction
│   ├── evidence/              # Exact grounding and provenance
│   ├── resolution/            # Entity and fact identity
│   ├── validation/            # Constraints, conflicts and corroboration
│   ├── review/                # Candidate lifecycle and decisions
│   ├── api/                   # Optional HTTP service
│   └── web/                   # Static local review client
├── examples/
│   └── ecommerce-facets/
│       ├── catalog-model.json
│       ├── catalog-signals/
│       ├── expected-discoveries.json
│       └── pilon.yaml
├── tests/
│   ├── contracts/             # Every plugin must pass the same contract tests
│   ├── unit/
│   ├── integration/
│   └── e2e/
└── docs/
    ├── concepts.md
    ├── profiles.md
    ├── plugins.md
    ├── evaluation.md
    ├── security.md
    ├── use-case-ecommerce-filter-discovery.md
    └── use-case-maintenance-discovery.md
```

## Stable core contracts

The core should contain data types and protocols, not vendor implementations.

```python
class SourceConnector(Protocol):
    def changes(self, checkpoint: str | None) -> Iterable[Document]: ...

class KnowledgeAdapter(Protocol):
    def model(self) -> KnowledgeModel: ...
    def facts(self, scope: Scope) -> Iterable[KnownFact]: ...

class SignalDetector(Protocol):
    def detect(self, context: DiscoveryContext) -> Iterable[Signal]: ...

class ClaimExtractor(Protocol):
    def extract(self, signal: Signal, context: DiscoveryContext) -> Iterable[Claim]: ...

class EvidenceGrounder(Protocol):
    def ground(self, claim: Claim, documents: Iterable[Document]) -> EvidenceResult: ...

class CandidateValidator(Protocol):
    def validate(self, candidate: Candidate, context: DiscoveryContext) -> Validation: ...
```

All implementations return canonical models. Vendor-specific response objects must
not leak into the candidate store or review interface.

## Plugin discovery

Use standard Python entry points rather than a custom package manager:

```toml
[project.entry-points."pilon.plugins"]
my_detector = "my_package.plugin:plugin"
```

A plugin descriptor declares capabilities separately from implementation:

```yaml
name: exact-langextract
kind: evidence_grounder
inputs: [text, claim]
outputs: [exact_span]
guarantees:
  exact_grounding: true
  deterministic: false
operations:
  local_execution: configurable
  cost_class: high
  data_egress: configurable
```

The registry should reject incompatible plugins before a run begins.

## Lean configuration

One project file should be enough for most users:

```yaml
knowledge:
  plugin: neo4j
  uri: ${NEO4J_URI}

sources:
  plugin: files
  path: ./reports

profile: balanced

policy:
  max_cost_usd: 5
  require_exact_grounding_for: [missing_fact, contradiction]
  canonical_writes: false

output:
  plugin: jsonl
  path: ./pilon-candidates.jsonl
```

Advanced users can replace stages individually, but the default path should never
require them to understand the full pipeline.

## Profiles, not configuration sprawl

Profiles resolve to policies and plugin routes:

- `explore`: local and inexpensive candidate generation;
- `balanced`: escalate credible candidates to structured extraction;
- `auditable`: require exact grounding, constraint checks and review.

Users may override one decision without copying the entire profile.

## What stays out of the core

- model-provider SDKs;
- database-specific objects;
- orchestration frameworks;
- graph visualization libraries;
- customer-specific rules;
- publication logic for canonical systems.

These belong in optional extras or external plugins. The first release should ship
only the adapters required by the ecommerce demo and the evaluation suite.
