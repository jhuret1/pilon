"""Public product projection contract: no inference, loss of evidence or mutation."""
from copy import deepcopy

import pytest

from pilon.loop.benchmark_ui import build_view
from pilon.loop.recommendations import build_recommendations


ITEM_FIELDS = {'id', 'label', 'category_refs', 'values', 'fact_key', 'basis',
               'record_ids', 'demand_count', 'proofs', 'rationales', 'candidate_keys',
               'model_values', 'filter_availability'}


@pytest.fixture
def model():
    return dict(category='catalog', assessment_scope='schema_only', observation_period='unknown',
                categories=['Beds', 'Desks'], facets=[
                    dict(key='height', label='raw_height', values=['20 in', '30 in'], scopes=['Beds', 'Desks']),
                    dict(key='color', label='raw_color', values=['white', 'red'], scopes=['Beds', 'Desks'])])


def proof(rid='q1', quote='  blanc «exact»  ', **overrides):
    return dict(record_id=rid, quote=quote, start=3, end=3 + len(quote), source='search',
                count=100, rationale='Original rationale.',
                **overrides)


def represented(rid='q1', **overrides):
    return dict(dict(record_id=rid, fact_key='color', label='Couleur', category_refs=['Beds'],
                     requested_value='blanc', matched_value='white', evidence=proof(rid)), **overrides)


def candidate(key='c1', gap='filter_proposal', **overrides):
    return dict(dict(key=key, gap_type=gap, label='Hauteur basse', proposed_key='low_height',
                     fact_key='height', category_refs=['Beds'], requested_value='bas',
                     matched_value=None, demand_events=999, demand_records=[proof()]), **overrides)


def test_exact_contract_and_detached_immutable_inputs(model):
    rows = [dict(id='q1', query_class='Desks', text='Original query', count=100)]
    direct = [represented(evidence=proof(refs={'document': ['source:42']}, extra={'verbatim': '  keep  '}))]
    candidates = [candidate()]
    inputs = model, rows, candidates, direct
    before = deepcopy(inputs)
    result = build_recommendations(*inputs)
    assert inputs == before
    assert set(result) == {'filters', 'explore', 'uncertain', 'categories', 'counts'}
    assert result['counts'] == dict(filters=2, explore=0, uncertain=0, uncertain_requests=0)
    for item in result['filters']:
        assert set(item) == ITEM_FIELDS
        assert item['filter_availability'] == 'not_provided'
        assert item['demand_count'] == 1
        assert item['category_refs'] == ['Beds']  # entry refs outrank query class
    item = next(i for i in result['filters'] if i['basis'] == 'existing_attribute')
    assert item['proofs'] == [direct[0]['evidence']]
    assert item['model_values'] == ['white']
    assert item['values'] == ['blanc']
    item['proofs'][0]['refs']['document'].append('changed')
    item['category_refs'].append('changed')
    assert inputs == before


def test_direct_values_proofs_and_unique_queries_aggregate_with_semantic_label(model):
    entries = [represented(label='Teinte'), represented('q2', label='Couleur', requested_value='rouge', matched_value='red'),
               represented(label='Couleur'), represented('q3', label='Couleur', requested_value='blanc')]
    item, = build_recommendations(model, [], [], entries)['filters']
    assert item['label'] == 'Couleur'
    assert item['record_ids'] == ['q1', 'q2', 'q3'] and item['demand_count'] == 3
    assert item['values'] == ['blanc', 'rouge']
    assert item['model_values'] == ['red', 'white']
    assert len(item['proofs']) == 4  # repeated proof survives; request counted once
    assert item['candidate_keys'] == []


def test_exact_sorted_scopes_are_separate_and_unknown_is_not_inferred(model):
    rows = [dict(id='q1', query_class='Desks'), dict(id='q2', query_class='unmapped query')]
    entries = [represented(category_refs=['Desks', 'Beds']),
               represented('q2', category_refs=['Beds', 'Desks'], requested_value='rouge'),
               represented(category_refs=[]), represented('q2', category_refs=[]),
               represented('q3', category_refs=['Beds'])]
    result = build_recommendations(model, rows, [], entries)
    by_scope = {tuple(i['category_refs']): i for i in result['filters']}
    assert set(by_scope) == {('Beds', 'Desks'), ('Desks',), (), ('Beds',)}
    assert by_scope[('Beds', 'Desks')]['values'] == ['blanc', 'rouge']
    assert by_scope[()]['record_ids'] == ['q2']
    assert result['categories'] == ['Beds', 'Desks']


def test_candidate_fallbacks_keep_separate_query_scopes(model):
    rows = [dict(id='q1', query_class='Beds'), dict(id='q2', query_class='Desks')]
    c = candidate(category_refs=[], demand_records=[proof('q1'), proof('q2'), proof('unknown')])
    items = build_recommendations(model, rows, [c], [])['filters']
    assert {tuple(i['category_refs']) for i in items} == {('Beds',), ('Desks',), ()}
    assert all(i['demand_count'] == 1 and len(i['proofs']) == 1 for i in items)


def test_category_only_represented_is_not_a_filter(model):
    entries = [represented(fact_key=None, label='Type de meuble'), represented(fact_key='not_a_model_key')]
    assert build_recommendations(model, [], [], entries)['filters'] == []
    c = candidate(fact_key=None, proposed_key='audience', label='Public')
    item, = build_recommendations(model, [], [c], entries)['filters']
    assert item['basis'] == 'derived_filter' and item['fact_key'] is None


def test_derived_filters_keep_proposal_fact_and_scope_separate_from_raw_height(model):
    direct = [represented(fact_key='height', label='Hauteur', requested_value='20 pouces', matched_value='20 in')]
    candidates = [candidate(), candidate('c2', requested_value='très bas', demand_records=[proof('q2')]),
                  candidate('c3', proposed_key='adjustable_height'), candidate('c4', fact_key='color'),
                  candidate('c5', category_refs=['Desks']), candidate('c6', proposed_key=None),
                  candidate('c7', proposed_key=None)]
    items = build_recommendations(model, [], candidates, direct)['filters']
    assert len(items) == 7
    raw, = [i for i in items if i['basis'] == 'existing_attribute']
    assert raw['values'] == ['20 pouces'] and raw['candidate_keys'] == []
    low, = [i for i in items if i['candidate_keys'] == ['c1', 'c2']]
    assert low['values'] == ['bas', 'très bas'] and low['demand_count'] == 2


def test_exploration_groups_values_by_target_scope_and_gap_type(model):
    cs = [candidate('a', 'schema_gap', proposed_key='finish', fact_key=None, requested_value='mat'),
          candidate('b', 'schema_gap', proposed_key='finish', fact_key=None, requested_value='brillant'),
          candidate('c', 'schema_gap', proposed_key='finish', fact_key=None, category_refs=['Desks']),
          candidate('d', 'value_gap', fact_key='color', requested_value='ultraviolet'),
          candidate('e', 'value_gap', fact_key='color', requested_value='infrarouge')]
    result = build_recommendations(model, [], cs, [])
    assert result['filters'] == [] and result['uncertain'] == []
    assert result['counts']['explore'] == 3
    merged, = [i for i in result['explore'] if i['candidate_keys'] == ['a', 'b']]
    assert merged['basis'] == 'missing_attribute' and merged['values'] == ['brillant', 'mat']
    assert merged['demand_count'] == 1 and len(merged['proofs']) == 2
    values, = [i for i in result['explore'] if i['basis'] == 'unobserved_value']
    assert values['values'] == ['infrarouge', 'ultraviolet'] and values['model_values'] == []


def test_unresolved_candidates_stay_individual_with_unique_request_count(model):
    cs = [candidate('u1', 'unresolved_intent'), candidate('u2', 'unresolved_intent'),
          candidate('u3', 'unresolved_intent', demand_records=[proof('q1'), proof('q2')])]
    result = build_recommendations(model, [], cs, [])
    assert result['counts'] == dict(filters=0, explore=0, uncertain=3, uncertain_requests=2)
    assert all(i['basis'] == 'unresolved' and len(i['candidate_keys']) == 1 for i in result['uncertain'])
    original_id = next(i['id'] for i in result['uncertain'] if i['candidate_keys'] == ['u1'])
    cs[0].update(label='Changed label', category_refs=['Desks'], requested_value='other')
    assert build_recommendations(model, [], cs[:1], [])['uncertain'][0]['id'] == original_id


def test_order_independence_label_ties_and_stable_group_ids(model):
    direct = [represented(label='Teinte'), represented('q2', label='Couleur')]
    cs = [candidate(), candidate('c2', requested_value='très bas', demand_records=[proof('q2'), proof('q1')])]
    before = build_recommendations(model, [], cs, direct)
    cs.reverse()
    for c in cs:
        c['demand_records'].reverse()
    assert build_recommendations(model, [], cs, direct[::-1]) == before
    raw = next(i for i in before['filters'] if i['basis'] == 'existing_attribute')
    assert raw['label'] == 'Couleur'
    direct.append(represented('q3', requested_value='nouveau'))
    assert next(i for i in build_recommendations(model, [], [], direct)['filters']
                if i['basis'] == 'existing_attribute')['id'] == raw['id']


def test_empty_and_no_evidence_do_not_invent_sources_or_counts(model):
    assert build_recommendations({}, [], [], []) == dict(filters=[], explore=[], uncertain=[], categories=[],
        counts=dict(filters=0, explore=0, uncertain=0, uncertain_requests=0))
    c = candidate(demand_records=[], category_refs=[], matched_value=None)
    item, = build_recommendations(model, [], [c], [])['filters']
    assert item['proofs'] == item['record_ids'] == item['category_refs'] == item['model_values'] == []
    assert item['demand_count'] == 0
    item, = build_recommendations(model, [], [], [represented(evidence=None)])['filters']
    assert item['record_ids'] == ['q1'] and item['demand_count'] == 1 and item['proofs'] == []


@pytest.mark.parametrize('analysis,enabled', [
    ({}, False), ({'method': 'lexical', 'status': 'reviewed'}, False),
    ({'method': 'agent_semantic_review'}, False),
    ({'method': 'agent_semantic_review', 'status': 'pending'}, False),
    ({'method': 'agent_semantic_review', 'status': 'reviewed'}, True)])
def test_build_view_adds_only_reviewed_semantic_product_view(model, analysis, enabled):
    bp = dict(analysis=analysis, candidates=[candidate()], already_represented=[represented()])
    report = dict(model=model, benchmark=bp)
    before = deepcopy(report)
    view = build_view(report)
    assert report == before
    if enabled:
        assert view['product_view'] == build_recommendations(model, view['demands'], bp['candidates'], bp['already_represented'])
    else:
        assert view['product_view'] is None
    assert build_view(dict(model=model, analysis=analysis))['product_view'] is None
