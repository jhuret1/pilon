"""Demand-first gap detection with explicit, pluggable intent extraction.

The default adapter recognizes configured aliases and explicit filter requests.
It is a reproducible baseline, not a multilingual semantic understanding model.
Unrecognized requests remain in an unresolved queue instead of disappearing.
"""
from collections import defaultdict
from copy import deepcopy
from hashlib import sha256
from functools import lru_cache
import re

from ..facets.engine import _key, _day, _terms, labeled_specs
from .extraction import _records as _source_records
from .store import canonical


def _identifier(label):
    return _key(label).replace(" ", "_")


@lru_cache(maxsize=32768)
def _phrase_pattern(phrase):
    # Reuse the same vocabulary across queries without caching customer texts.
    words = re.findall(r"[^\W_]+", phrase, re.UNICODE)
    if not words:
        return None
    expression = r"(?<!\w)" + r"[\W_]+".join(re.escape(w) for w in words) + r"(?!\w)"
    return re.compile(expression, re.IGNORECASE)


def _span(text, phrase):
    # Unicode case insensitive matching keeps offsets in the original string.
    pattern = _phrase_pattern(phrase)
    return pattern.search(text) if pattern is not None else None


def _proof(row, start, end):
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(row["text"]):
        raise ValueError(f"Invalid intent evidence in {row['id']}")
    return dict(record_id=row["id"], source=row["source"], quote=row["text"][start:end],
                start=start, end=end, count=row.get("count", 1))


def _vocabulary(model, rows):
    vocab = {}
    def add(label, aliases=(), definition="", canonical_key=None):
        if not isinstance(label, str) or not _key(label):
            raise ValueError("Intent labels must be nonempty text")
        if not isinstance(aliases, (list, tuple, set)) or any(not isinstance(a,str) or not _key(a) for a in aliases):
            raise ValueError('Intent aliases must be a list of nonempty strings')
        label_key = _identifier(label)
        mapped = [] if canonical_key else [k for k,v in vocab.items() if label_key in {_identifier(a) for a in v['aliases']}]
        key = _identifier(canonical_key) if canonical_key else (mapped[0] if len(mapped)==1 else label_key)
        v = vocab.setdefault(key, dict(key=key, label=label, definition=definition,
                                      aliases=set()))
        if definition:
            v["definition"] = definition
        v["aliases"].update({label, key.replace('_',' '), *aliases})
    for facet in model.get("facets", []):
        add(facet.get("label", facet.get("key")), facet.get("aliases", []), facet.get("definition", ""), facet.get('key'))
    for label in model.get("existing_facets", []):
        add(label)
    for label, aliases in model.get("aliases", {}).items():
        add(label, aliases)
    for hint in model.get("intent_hints", []):
        add(hint["label"], hint.get("aliases", []), hint.get("definition", ""))
    # Vectors are supplied artifacts, never invented by the lexical baseline.
    for item in [*model.get('facets',[]),*model.get('intent_hints',[])]:
        target=_identifier(item.get('key',item.get('label','')))
        if target in vocab:
            for field in ('embedding','embedding_contract','scopes'):
                if field in item:
                    vocab[target][field]=deepcopy(item[field])
    # Supply can add hints, but it is NEVER required for a demand candidate to exist.
    for row in rows:
        if row["role"] == "catalog" and row.get("asset_type", "text") != "image":
            for spec in labeled_specs(row["text"]):
                add(spec.label)
    return vocab


def _intents(row, vocabulary, intent_extractor):
    supplied = row.get("intents")
    if supplied is None and intent_extractor:
        supplied = list(intent_extractor(deepcopy(row)))
    if supplied is not None:
        if not isinstance(supplied, list):
            raise ValueError("intents must be an array")
        if not supplied:
            yield _unresolved(row)
            return
        for intent in supplied:
            if not isinstance(intent, dict) or not isinstance(intent.get("label"), str) or not _key(intent["label"]):
                raise ValueError("Invalid grounded demand intent")
            proof = _proof(row, intent.get("start"), intent.get("end"))
            if proof["quote"] != intent.get("quote"):
                raise ValueError(f"Intent quote mismatch in {row['id']}")
            intent_aliases=_terms(intent.get('aliases',[intent['label']]),'intent aliases')
            key = _identifier(intent.get("key", intent["label"]))
            if key not in vocabulary:
                labels={key,_identifier(intent['label'])} | {_identifier(a) for a in intent_aliases}
                matches=[k for k,v in vocabulary.items()
                         if labels & {_identifier(a) for a in v['aliases']}]
                if len(matches)==1:
                    key=matches[0]
            concept=vocabulary.get(key,{})
            value_fields = {}
            if 'value' in intent:
                if not isinstance(intent['value'], str) or not intent['value'].strip():
                    raise ValueError('Demand values must be nonempty strings')
                span = intent.get('value_evidence', {})
                if not isinstance(span, dict):
                    raise ValueError('Demand value evidence must be an exact source span')
                value_proof = _proof(row, span.get('start'), span.get('end'))
                if value_proof['quote'] != span.get('quote'):
                    raise ValueError('Demand value quote mismatch')
                value_fields = dict(requested_value=intent['value'], value_evidence=value_proof)
            yield dict(key=key, label=intent["label"], definition=concept.get('definition') or intent.get("definition", ""),
                       aliases=sorted(intent_aliases | set(concept.get('aliases',[]))), evidence=proof,
                       **value_fields,
                       **{k:deepcopy(intent[k]) for k in ('embedding','embedding_contract') if k in intent},
                       detection="supplied_grounded_intent", identity_status="proposed")
        return
    matched = False
    for key, concept in sorted(vocabulary.items()):
        for phrase in sorted(concept["aliases"], key=lambda x: (-len(x), x)):
            match = _span(row["text"], phrase)
            if match:
                matched = True
                yield {**concept, "aliases": sorted(concept["aliases"]),
                       "evidence": _proof(row, *match.span()), "detection": "configured_phrase",
                       "identity_status": "proposed"}
                break
    if matched:
        return
    # Only an explicit attribute request is parsed, not arbitrary sentiment.
    match = re.search(r"(?:filter\s+by|filtrer\s+par|filtre\s+sur)\s+([^?.!;\n]{2,80})", row["text"], re.I)
    if match:
        label = match[1].strip()
        start = match.start(1) + len(match[1]) - len(match[1].lstrip())
        yield dict(key=_identifier(label), label=label, definition="", aliases=[label],
                   evidence=_proof(row, start, start+len(label)), detection="explicit_attribute_request",
                   identity_status="needs_definition")
        return
    # Preserve the request for interpretation without fabricating a fact name.
    yield _unresolved(row)


def _unresolved(row):
    key = "unresolved_" + sha256(_key(row["text"]).encode()).hexdigest()[:12]
    return dict(key=key, label="Intent to clarify", definition="", aliases=[],
               evidence=_proof(row, 0, len(row["text"])), detection="unresolved",
               identity_status="unresolved")


def _value_assessment(row, intent, facet):
    """Exact domain comparison; lack of a literal match is not semantic absence."""
    values = facet.get('values', [])
    scopes = facet.get('value_scopes', {})
    values = [v for v in values if not scopes or row.get('query_class', '') in scopes.get(v, [])]
    requested = intent.get('requested_value')
    proof = intent.get('value_evidence')
    if requested is None:
        matches = [(v, _span(row['text'], v)) for v in values if isinstance(v, str)]
        matches = [(v, m) for v, m in matches if m]
        if len(matches) != 1:
            return dict(value_status='unresolved' if matches else 'not_assessed')
        requested, match = matches[0]
        proof = _proof(row, *match.span())
    norm = lambda value: ' '.join(value.split()).casefold()
    present = any(norm(v) == norm(requested) for v in values)
    return dict(requested_value=requested, value_evidence=proof,
                value_status='observed_exact' if present else 'not_observed_exact',
                value_comparison='literal_only', semantic_validation='not_performed')


def benchmark(model, records, *, intent_extractor=None):
    """Find demand gaps even when no catalog evidence exists. Inputs are immutable."""
    if not isinstance(model, dict) or not isinstance(model.get("category"), str):
        raise ValueError("A category model is required")
    known = {_identifier(x) for x in _terms(model.get("existing_facets", []), "existing_facets")}
    for facet in model.get("facets", []):
        known.add(_identifier(facet.get("key", facet.get("label", ""))))
    schema_only = model.get('assessment_scope') == 'schema_only'
    undated = model.get('observation_period') == 'unknown'
    if undated:
        start = end = None
    else:
        start, end = _day(model.get("window_start"), "window_start"), _day(model.get("window_end"), "window_end")
        if end < start:
            raise ValueError("Invalid observation window")
    source = [r for r in _source_records(records) if r['category']==model['category']]
    for row in source:
        if row['role']!='catalog' and not row['text'].strip():
            raise ValueError('Demand and external records require nonempty text')
        if row['role']=='demand':
            if not undated or row.get('date'):
                _day(row.get('date'),'date')
            if type(row.get('count',1)) is not int or row.get('count',1)<1:
                raise ValueError('Invalid demand count')
    if schema_only and any(r.get('semantic_review') for r in source if r['role']=='demand'):
        from .semantic import reviewed_benchmark
        return reviewed_benchmark(model, source)
    # Schema-only assessment must not discover hints in individual product records.
    vocab = _vocabulary(model, [] if schema_only else source)
    facets = {_identifier(f.get('key', f.get('label', ''))):f for f in model.get('facets', [])}
    scoped_vocabs = {}
    inventory = {r["product_id"] for r in source if r["role"] == "catalog"}
    assignments = defaultdict(set)
    observed = defaultdict(set)
    for a in model.get("assignments", []):
        product=a.get('product_id')
        if not isinstance(product,str) or not product.strip():
            raise ValueError('Model assignments require a product ID')
        inventory.add(product)
        value=a.get('value')
        if value is None or (isinstance(value,str) and not value.strip()) or value==[] or value=={}:
            continue
        if a.get('status') in ('unknown','conflict','rejected'):
            continue
        observed[(_identifier(a.get('fact_key',a.get('key',''))),product)].add(canonical(value))
    for (key,product),values in observed.items():
        if len(values)==1:
            assignments[key].add(product)
    candidates = {}
    covered = []
    for row in source:
        if row["role"] != "demand" or (not undated and not start <= _day(row["date"], "date") <= end):
            continue
        row_vocab = vocab
        if schema_only:
            scope = row.get('query_class', '')
            if scope not in scoped_vocabs:
                scoped_vocabs[scope] = {k:v for k,v in vocab.items() if not v.get('scopes') or scope in v['scopes']}
            row_vocab = scoped_vocabs[scope]
        seen = set()
        for intent in _intents(row, row_vocab, intent_extractor):
            key = intent["key"]
            identity = (key, ' '.join(intent.get('requested_value', '').split()).casefold())
            if identity in seen:
                continue
            seen.add(identity)
            assigned = assignments[key]
            if intent["identity_status"] == "unresolved":
                gap = "unresolved_intent"
            elif key not in known or (schema_only and key not in row_vocab):
                gap = "schema_gap"
            elif schema_only:
                # An attribute-name match is not validation of the entire request.
                assessment = _value_assessment(row, intent, facets.get(key, {}))
                if assessment['value_status'] != 'not_observed_exact':
                    covered.append(dict(record_id=row['id'], fact_key=key, label=intent['label'],
                                        status='schema_represented', evidence=intent['evidence'], **assessment))
                    continue
                gap = 'value_gap'
                # Different missing values must not collapse into a single candidate.
                value_key = sha256(assessment['requested_value'].casefold().encode()).hexdigest()[:12]
                intent = {**intent, **assessment, 'fact_key':key, 'key':key + '__value_' + value_key}
                key = intent['key']
            elif not inventory or not inventory <= assigned:
                gap = "coverage_gap"
            elif row.get("outcome") in ("no_results", "unsatisfied", "unavailable_filter"):
                gap = "retrieval_gap"
            else:
                covered.append(dict(record_id=row["id"], fact_key=key, status="already_represented"))
                continue
            c = candidates.setdefault(key, {k:deepcopy(v) for k,v in intent.items() if k != "evidence"})
            c.setdefault("gap_type", gap)
            c.setdefault("status", "needs_definition" if gap == "unresolved_intent" else "needs_extraction")
            evidence = deepcopy(intent['evidence'])
            if intent.get('value_evidence'):
                evidence.update(requested_value=intent['requested_value'],
                                value_evidence=deepcopy(intent['value_evidence']))
            c.setdefault("demand_records", []).append(evidence)
            c["demand_events"] = c.get("demand_events", 0) + row.get("count", 1)
            c["known_assignment_count"] = None if schema_only else len(assigned)
    out = sorted(candidates.values(), key=lambda x: (-x["demand_events"], x["key"]))
    return dict(schema_version=1, stage="benchmark", category=model["category"],
                candidates=out, already_represented=covered,
                metrics=dict(candidate_count=len(out), source_records=len(source),
                             inventory_products=None if schema_only else len(inventory), llm_calls=0,
                             detector="grounded annotations / configured phrases / unresolved queue",
                             demand_events=sum(c["demand_events"] for c in out)),
                limitations=["Default detection is lexical, not semantic induction.",
                             "Demand volume counts events, not unique shoppers."] +
                            (["Schema-only: product coverage and retrieval performance are not assessed.",
                              "Observed values are not exhaustive; literal gaps require semantic review."] if schema_only else []))
