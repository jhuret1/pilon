"""Compact, read-only projection of supplied semantic benchmark decisions.

No matching, inference, product assessment or publication happens here. Category
fallbacks use only exact query classes present in the frozen model. Evidence is
copied verbatim, including duplicates; demand counts use distinct source IDs.
"""
from collections import Counter
from copy import deepcopy
from hashlib import sha256

from .report import _entries, _mapping
from .store import canonical


def _strings(values):
    return sorted({v for v in values if isinstance(v, str) and v})


def _proofs(entry):
    proofs = list(entry.get('demand_records') or [])
    if isinstance(entry.get('evidence'), dict) and entry['evidence']:
        proofs.append(entry['evidence'])
    return proofs


def _record_ids(entry, proofs):
    return _strings([entry.get('record_id'), *(entry.get('record_ids') or []),
                     *(p.get('record_id') for p in proofs)])


def _scoped_sources(entry, proofs, query_categories):
    """Never turn separate source categories into a guessed combined scope."""
    record_ids = _record_ids(entry, proofs)
    refs = tuple(_strings(entry.get('category_refs') or []))
    if refs:
        return [(refs, record_ids, proofs)]
    scopes = {}
    for rid in record_ids:
        scope = query_categories.get(rid, ())
        scopes.setdefault(scope, []).append(rid)
    # An unscoped proof without a source ID must still survive the projection.
    if not scopes or any(not p.get('record_id') for p in proofs):
        scopes.setdefault((), [])
    return [(scope, ids, [p for p in proofs if p.get('record_id') in ids
                         or (not p.get('record_id') and not scope)])
            for scope, ids in sorted(scopes.items())]


def _new_item(identity, basis, fact_key, refs):
    return dict(id=sha256(canonical(identity).encode()).hexdigest()[:24],
                label='', category_refs=list(refs), values=[], requested_values=[], fact_key=fact_key,
                basis=basis, record_ids=[], demand_count=0, proofs=[], rationales=[],
                candidate_keys=[], model_values=[], filter_availability='not_provided')


def build_recommendations(model, demands, candidates, represented):
    """Separate proposed filters, exploration, covered needs and unresolved needs.

    Existing attributes group by their exact model key and category scope. Derived
    filters additionally require the same proposal key; exploration groups keep
    missing attributes separate from unobserved values. Neither source frequency
    weights nor reported event totals are interpreted as distinct requests.
    """
    model = _mapping(model)
    facets = {f['key']: f for f in _entries(model.get('facets')) if f.get('key')}
    categories = set(model.get('categories') or [])
    query_categories = {}
    for demand in _entries(demands, key='id'):
        category = demand.get('query_class')
        if category in categories:
            query_categories.setdefault(demand.get('id'), set()).add(category)
    # Conflicting source rows cannot establish one exact fallback scope.
    query_categories = {rid: tuple(sorted(refs)) if len(refs) == 1 else ()
                        for rid, refs in query_categories.items()}
    groups = dict(filters={}, explore={}, covered={}, uncertain={})
    labels = {}

    def add(section, identity, entry, basis, fact_key, refs, ids, proofs, candidate=False):
        item = groups[section].setdefault(identity, _new_item(identity, basis, fact_key, refs))
        label = entry.get('label') or facets.get(fact_key, {}).get('label') or fact_key or entry.get('key') or ''
        labels.setdefault(item['id'], Counter())[label] += 1
        requested = entry.get('requested_value')
        matched = entry.get('matched_value')
        item['requested_values'].extend(_strings([requested]))
        # Reuse only the supplied match to an exact observed value. Do not infer
        # synonym/case equivalence; the original wording stays in requested_values
        # and in its source quotation. Derived filters retain their proposed value.
        observed = facets.get(fact_key, {}).get('values') or []
        display_value = (matched if basis == 'existing_attribute' and matched in observed
                         and isinstance(matched, str) else requested)
        item['values'].extend(_strings([display_value]))
        item['record_ids'].extend(ids)
        item['proofs'].extend(deepcopy(proofs))
        item['rationales'].extend(_strings([entry.get('rationale') or entry.get('definition'),
                                           *(p.get('rationale') for p in proofs)]))
        item['model_values'].extend(_strings([entry.get('matched_value')]))
        if candidate:
            item['candidate_keys'].extend(_strings([entry.get('key')]))

    for entry in _entries(represented):
        fact_key = entry.get('fact_key')
        # Category-only represented product types are navigation, not filters.
        if not fact_key or fact_key not in facets:
            continue
        for refs, ids, proofs in _scoped_sources(entry, _proofs(entry), query_categories):
            identity = ('existing_attribute', fact_key, refs)
            # A represented criterion is coverage, not an opportunity to add a
            # filter. Storefront filter availability cannot be inferred either.
            add('covered', identity, entry, 'existing_attribute', fact_key, refs, ids, proofs)

    for entry in _entries(candidates):
        gap = entry.get('gap_type')
        fact_key = entry.get('fact_key') or None
        sources = _scoped_sources(entry, _proofs(entry), query_categories)
        if gap == 'unresolved_intent':
            # One item per supplied candidate, even when multiple requests agree.
            refs = _strings(ref for scope, _, _ in sources for ref in scope)
            identity = ('unresolved', entry.get('key'))
            add('uncertain', identity, entry, 'unresolved', fact_key, refs,
                _record_ids(entry, _proofs(entry)), _proofs(entry), candidate=True)
            continue
        for refs, ids, proofs in sources:
            if gap == 'filter_proposal':
                identity = ('derived_filter', entry.get('proposed_key') or entry.get('key'), fact_key, refs)
                add('filters', identity, entry, 'derived_filter', fact_key, refs, ids, proofs, candidate=True)
            elif gap in ('schema_gap', 'value_gap'):
                target = fact_key or entry.get('proposed_key') or entry.get('key')
                basis = 'missing_attribute' if gap == 'schema_gap' else 'unobserved_value'
                identity = (basis, target, refs)
                add('explore', identity, entry, basis, fact_key, refs, ids, proofs, candidate=True)

    result = {}
    for section, items in groups.items():
        for item in items.values():
            item['label'] = min(labels[item['id']], key=lambda label: (-labels[item['id']][label], label))
            for field in ('values', 'requested_values', 'record_ids', 'rationales', 'candidate_keys', 'model_values'):
                item[field] = _strings(item[field])
            item['demand_count'] = len(item['record_ids'])
            item['proofs'].sort(key=canonical)
        result[section] = sorted(items.values(), key=lambda item: (-item['demand_count'], item['label'], item['id']))
    result['categories'] = _strings(ref for items in result.values() for item in items for ref in item['category_refs'])
    result['counts'] = {section: len(result[section]) for section in groups}
    result['counts']['uncertain_requests'] = len({rid for item in result['uncertain'] for rid in item['record_ids']})
    return result
