"""Import inspectable semantic decisions; never call a remote model or publish them."""
from collections import Counter
from copy import deepcopy
from hashlib import sha256

from .store import fingerprint


ASSESSMENTS = {'represented', 'attribute_gap', 'value_gap', 'filter_proposal', 'unresolved'}


def annotate_records(model, records, reviews):
    """Validate an entire review pass against a frozen model and exact source spans."""
    demands = {r['id']:r for r in records if r['role']=='demand'}
    facets = {f['key']:f for f in model.get('facets', [])}
    categories = set(model.get('categories', []))
    if not isinstance(reviews, list):
        raise ValueError('Semantic reviews must be an array')
    by_id = {}
    for review in reviews:
        if not isinstance(review, dict):
            raise ValueError('Each semantic review must be an object')
        rid = review.get('record_id')
        if rid not in demands or rid in by_id:
            raise ValueError('Unknown or duplicated semantic review record: ' + str(rid))
        if not isinstance(review.get('interpretation'), str) or not review['interpretation'].strip():
            raise ValueError('Each semantic review needs an interpretation')
        criteria = review.get('criteria')
        if not isinstance(criteria, list) or not criteria:
            raise ValueError('Each request needs at least one reviewed criterion')
        for criterion in criteria:
            if not isinstance(criterion, dict):
                raise ValueError('Each semantic criterion must be an object')
            state = criterion.get('assessment')
            if not isinstance(state, str) or state not in ASSESSMENTS:
                raise ValueError('Invalid semantic assessment: ' + str(state))
            for name in ('label', 'rationale'):
                if not isinstance(criterion.get(name), str) or not criterion[name].strip():
                    raise ValueError('Semantic criterion requires ' + name)
            start, end = criterion.get('start'), criterion.get('end')
            text = demands[rid]['text']
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
                raise ValueError('Invalid semantic evidence offsets: ' + rid)
            if text[start:end] != criterion.get('quote'):
                raise ValueError('Semantic evidence quote mismatch: ' + rid)
            key, value = criterion.get('fact_key'), criterion.get('matched_value')
            for field in ('fact_key', 'matched_value', 'value', 'proposed_key'):
                if criterion.get(field) is not None and not isinstance(criterion[field], str):
                    raise ValueError('Semantic ' + field + ' must be text or null')
            refs = criterion.get('category_refs', [])
            if not isinstance(refs, list) or any(not isinstance(c, str) or c not in categories for c in refs):
                raise ValueError('Unknown semantic category reference: ' + rid)
            if key is not None and key not in facets:
                raise ValueError('Unknown semantic attribute reference: ' + str(key))
            if value is not None and (key is None or value not in facets[key].get('values', [])):
                raise ValueError('Unobserved matched value: ' + str(value))
            if key:
                scopes = facets[key].get('scopes', [])
                reference_scope = refs or [demands[rid].get('query_class', '')]
                if scopes and not set(scopes).intersection(reference_scope):
                    raise ValueError('Semantic attribute outside referenced categories: ' + rid)
                value_scopes = facets[key].get('value_scopes', {})
                if value is not None and value_scopes and not set(value_scopes.get(value, [])).intersection(reference_scope):
                    raise ValueError('Semantic value outside referenced categories: ' + rid)
            if state in ('represented', 'filter_proposal') and not key and not refs:
                raise ValueError('Represented criteria need a model or category reference: ' + rid)
            if state == 'value_gap' and (not key or value is not None):
                raise ValueError('Value gaps require an existing attribute without a matched value')
            if state == 'attribute_gap' and (key or value is not None):
                raise ValueError('Attribute gaps cannot reference an already represented attribute')
        by_id[rid] = deepcopy(review)
    if set(by_id) != set(demands):
        raise ValueError('Semantic pass is incomplete: ' + str(len(set(demands)-set(by_id))) + ' requests missing')
    model_hash = fingerprint(model)
    out = deepcopy(records)
    for row in out:
        if row['role']=='demand':
            row['semantic_review'] = by_id[row['id']]
            row['reviewed_model_hash'] = model_hash
            row['reviewed_source_hash'] = fingerprint([row['id'], row['text'], row.get('query_class')])
    return out


def reviewed_benchmark(model, records):
    """Aggregate grounded proposals, separating navigation suggestions from gaps."""
    demands = [r for r in records if r['role']=='demand']
    model_hash = fingerprint(model)
    if any(r.get('reviewed_model_hash') != model_hash for r in demands):
        raise ValueError('Semantic reviews do not match this model snapshot')
    if any(r.get('reviewed_source_hash') != fingerprint([r['id'], r['text'], r.get('query_class')]) for r in demands):
        raise ValueError('Semantic reviews do not match the unchanged source context')
    reviews = [r.get('semantic_review', {}) for r in demands]
    annotate_records(model, records, reviews)
    candidates, covered, counts = {}, [], Counter()
    for row in demands:
        seen = set()
        review = row['semantic_review']
        for c in review['criteria']:
            state = c['assessment']
            counts[state] += 1
            proof = dict(record_id=row['id'], source=row['source'], quote=c['quote'],
                         start=c['start'], end=c['end'], count=row.get('count',1),
                         interpretation=review['interpretation'], rationale=c['rationale'])
            info = dict(fact_key=c.get('fact_key'), label=c['label'], requested_value=c.get('value'),
                        matched_value=c.get('matched_value'), category_refs=c.get('category_refs', []),
                        rationale=c['rationale'], evidence=proof, assessment=state,
                        validation_status='agent_reviewed_not_independently_audited')
            if state == 'represented':
                covered.append(dict(record_id=row['id'], status='schema_represented',
                                    value_status='observed_semantic' if c.get('matched_value') is not None else 'represented_by_category' if not c.get('fact_key') else 'attribute_represented',
                                    **info))
                continue
            gap = {'attribute_gap':'schema_gap', 'value_gap':'value_gap',
                   'filter_proposal':'filter_proposal', 'unresolved':'unresolved_intent'}[state]
            # A supplied stable proposal key groups related demands without dropping source evidence.
            target = c.get('fact_key') or c.get('proposed_key') or c['label']
            identity = [gap, target, c.get('value'), sorted(c.get('category_refs', []))]
            if state == 'unresolved':
                identity.append(row['id'])
            key = 'review_' + sha256(str(identity).encode()).hexdigest()[:16]
            if key in seen:
                continue
            seen.add(key)
            candidate = candidates.setdefault(key, dict(key=key, **{k:v for k,v in info.items() if k!='evidence'},
                proposed_key=c.get('proposed_key'), definition=c['rationale'], aliases=[], gap_type=gap,
                detection='agent_semantic_review', identity_status='proposed', status='needs_review',
                known_assignment_count=None, demand_records=[], demand_events=0,
                filter_availability='not_provided',
                value_status='not_observed_semantic' if state=='value_gap' else
                    ('observed_semantic' if c.get('matched_value') is not None else 'attribute_represented' if c.get('fact_key') else 'represented_by_category')
                    if state=='filter_proposal' else 'not_assessed'))
            candidate['demand_records'].append(proof)
            candidate['demand_events'] += row.get('count',1)
    out = sorted(candidates.values(), key=lambda c:(-c['demand_events'],c['key']))
    return dict(schema_version=1, stage='benchmark', category=model['category'], candidates=out,
                already_represented=covered,
                analysis=dict(method='agent_semantic_review', status='reviewed', reviewed_records=len(demands),
                              reviewed_criteria=sum(counts.values()), assessments=dict(counts),
                              model_hash=fingerprint(model), independent_audit=False,
                              api_cost_usd=0, execution='imported_agent_decisions',
                              inference_accounting='Agent session usage is not metered by PILON; no provider API was called for replay.'),
                metrics=dict(candidate_count=len(out), source_records=len(records), inventory_products=None,
                             llm_calls=0, detector='imported agent semantic decisions',
                             demand_events=sum(c['demand_events'] for c in out)),
                limitations=['Decisions were reviewed by agents, not independently evaluated for accuracy.',
                             'Observed values are non-exhaustive; proposals do not prove absence.',
                             'The current storefront filter configuration was not supplied.',
                             'No products are assessed and no model or filter is published.'])
