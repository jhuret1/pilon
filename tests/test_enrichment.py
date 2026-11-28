from copy import deepcopy
import pytest

from pilon.loop.enrichment import prepare_enrichment
from pilon.loop.semantic import annotate_records
from pilon.loop.store import Queue
from pilon.loop.worker import run_once


def benchmark_job(queue):
    model=dict(category='Tools',assessment_scope='schema_only',observation_period='unknown',categories=[],
               facets=[dict(key='power_mode',label='Power mode',values=['corded'])],assignments=[])
    records=[dict(id='q1',role='demand',source='search',category='Tools',text='cordless drill')]
    reviews=[dict(record_id='q1',interpretation='A cordless drill',criteria=[dict(
        label='Power mode',value='cordless',assessment='value_gap',fact_key='power_mode',
        quote='cordless',start=0,end=8,rationale='Cordless is not in the supplied observed domain.',category_refs=[])])]
    records=annotate_records(model,records,reviews)
    jid=queue.enqueue(model,records,options={'through':'benchmark'})
    result=run_once(queue,job_id=jid)
    return jid,result['candidates'][0]['key']


def test_enrichment_extends_existing_attribute_instead_of_duplicating_review_id(tmp_path):
    queue=Queue(tmp_path/'jobs.sqlite');parent,key=benchmark_job(queue)
    before=deepcopy(queue.get(parent))
    source=dict(id='p1',role='catalog',source='description',category='Tools',product_id='drill-1',
                text='Power mode: cordless')
    jid=prepare_enrichment(queue,parent,[key],[source])
    result=run_once(queue,job_id=jid)
    assert result['status']=='completed'
    assert result['candidates'][0]['key']=='power_mode'
    assert result['projection']['schema_changes'][0]['op']=='update'
    assert len(result['projection']['projected_model']['facets'])==1
    assert result['projection']['projected_model']['facets'][0]['values']==['corded','cordless']
    assert result['projection']['assignment_changes'][0]['fact_key']=='power_mode'
    assert result['publication']['status']=='not_published'
    assert queue.get(parent)==before
    assert prepare_enrichment(queue,parent,[key],[source])==jid
    assert run_once(queue,job_id=jid) is None


def test_invalid_selection_and_demand_as_product_evidence_are_rejected(tmp_path):
    queue=Queue(tmp_path/'jobs.sqlite');parent,key=benchmark_job(queue)
    source=dict(id='p1',role='catalog',source='description',category='Tools',product_id='d1',text='unknown')
    with pytest.raises(ValueError): prepare_enrichment(queue,parent,['invented'],[source])
    with pytest.raises(ValueError): prepare_enrichment(queue,parent,[key],[dict(source,role='demand')])


def multi_target_parent(queue):
    model = dict(category='Tools', assessment_scope='schema_only', observation_period='unknown',
                 categories=[], assignments=[], facets=[
                     dict(key='power_mode', label='Power mode', values=['corded']),
                     dict(key='color', label='Color', values=['blue'])])
    records, reviews = [], []
    for rid, key, label, value in [('q1', 'power_mode', 'Power mode', 'cordless'),
                                    ('q2', 'color', 'Color', 'red')]:
        records.append(dict(id=rid, role='demand', source='search', category='Tools', text=value+' drill'))
        reviews.append(dict(record_id=rid, interpretation=value+' drill', criteria=[dict(
            label=label, value=value, assessment='value_gap', fact_key=key, quote=value,
            start=0, end=len(value), rationale='Value absent from the observed domain.', category_refs=[])]))
    parent = queue.enqueue(model, annotate_records(model, records, reviews), options={'through':'benchmark'})
    result = run_once(queue, job_id=parent)
    return parent, [c['key'] for c in result['candidates']]


def catalog_sources():
    return [dict(id='p'+str(i), product_id='tool-'+str(i), role='catalog', source='description',
                 category='Tools', text='Power mode: cordless\nColor: red', embedding=[1, 0],
                 embedding_contract=dict(model='test', dimensions=2)) for i in range(1, 4)]


def routing_manifest(ids):
    return dict(method='test_shortlist', selected_record_ids=ids, selected_assets=len(ids),
                indexed_assets=10, matching_assets=5, unassessed_outside_shortlist=10-len(ids), limit=5)


def inspect_enrichment(queue, child):
    payload = deepcopy(queue.get(child)['payload'])
    payload['options']['geometry'] = True
    for candidate in payload['options']['prepared_benchmark']['candidates']:
        candidate.update(embedding=[1, 0], embedding_contract=dict(model='test', dimensions=2))
    jid = queue.enqueue(payload['model'], payload['records'], options=payload['options'])
    return jid, run_once(queue, job_id=jid)


@pytest.mark.parametrize('other_routing', ['selected', 'missing', 'legacy'])
def test_each_target_extracts_and_inspects_only_its_selected_catalog(tmp_path, other_routing):
    queue = Queue(tmp_path/'jobs.sqlite')
    parent, keys = multi_target_parent(queue)
    catalog = catalog_sources()
    routing = dict(power_mode=routing_manifest(['p1']), color=routing_manifest(['p2']))
    if other_routing == 'missing':
        del routing['color']
    elif other_routing == 'legacy':
        routing['color'] = {'method':'legacy'}
    before = deepcopy(routing)
    child = prepare_enrichment(queue, parent, keys, catalog, routing=routing)
    _, result = inspect_enrichment(queue, child)
    assert routing == before
    expected = dict(power_mode=['p1'], color=['p2'] if other_routing == 'selected' else ['p1', 'p2', 'p3'])
    products = {r['id']:r['product_id'] for r in catalog}
    for extraction in result['extractions']:
        ids = expected[extraction['candidate_key']]
        assert [r['id'] for r in extraction['source_records']] == ids
        assert [a['product_id'] for a in extraction['assignments']] == [products[rid] for rid in ids]
        assert extraction['unknown_products'] == []
        assert extraction['metrics']['extraction']['analyzed_assets'] == len(ids)
    for geometry in result['geometry']:
        ids = expected[geometry['candidate_key']]
        assert geometry['scope']['input_record_count'] == len(ids)
        assert geometry['scope']['identified_record_ids'] == ids
        assert [p['id'] for p in geometry['points']] == ids


def test_stage_caches_follow_selected_ids_and_content_not_other_targets(tmp_path):
    queue = Queue(tmp_path/'jobs.sqlite')
    parent, keys = multi_target_parent(queue)
    catalog = catalog_sources()
    routing = dict(power_mode=routing_manifest(['p1']), color=routing_manifest(['p2']))

    def run():
        child = prepare_enrichment(queue, parent, keys, catalog, routing=routing)
        return inspect_enrichment(queue, child)

    first, _ = run()
    routing['power_mode'] = routing_manifest(['p3'])
    second, result = run()
    assert next(e for e in result['extractions'] if e['candidate_key']=='power_mode')['assignments'][0]['product_id']=='tool-3'
    for prefix in ('extract:', 'geometry:'):
        assert queue.checkpoint(first, prefix+'power_mode')['input_hash'] != queue.checkpoint(second, prefix+'power_mode')['input_hash']
        assert prefix+'power_mode' not in result['metrics']['reused_stages']
        assert prefix+'color' in result['metrics']['reused_stages']
    catalog[0]['text'] = 'Power mode: changed outside both shortlists'
    _, result = run()
    assert {'extract:power_mode', 'extract:color', 'geometry:power_mode', 'geometry:color'} <= set(result['metrics']['reused_stages'])
    catalog[2]['text'] = 'Power mode: solar\nColor: red'
    fourth, result = run()
    assert next(e for e in result['extractions'] if e['candidate_key']=='power_mode')['assignments'][0]['value']=='solar'
    for prefix in ('extract:', 'geometry:'):
        assert queue.checkpoint(second, prefix+'power_mode')['input_hash'] != queue.checkpoint(fourth, prefix+'power_mode')['input_hash']
        assert prefix+'power_mode' not in result['metrics']['reused_stages']
        assert prefix+'color' in result['metrics']['reused_stages']


@pytest.mark.parametrize('routing,expected', [
    (None, ['p1', 'p2', 'p3']),
    ({'power_mode': {'method':'legacy', 'selected_assets':3}}, ['p1', 'p2', 'p3']),
    ({'method':'legacy', 'selected_assets':3}, ['p1', 'p2', 'p3']),
    (routing_manifest(['p2']), ['p2']),
    ({'power_mode':routing_manifest([])}, []),
])
def test_legacy_missing_ids_and_explicit_empty_shortlists(tmp_path, routing, expected):
    queue = Queue(tmp_path/'jobs.sqlite')
    parent, key = benchmark_job(queue)
    child = prepare_enrichment(queue, parent, [key], catalog_sources(), routing=routing)
    _, result = inspect_enrichment(queue, child)
    extraction, = result['extractions']
    assert [r['id'] for r in extraction['source_records']] == expected
    assert extraction['metrics']['extraction']['analyzed_assets'] == len(expected)
    assert result['geometry'][0]['scope']['identified_record_ids'] == expected


@pytest.mark.parametrize('ids', [None, 'p1', ['p1', 'p1'], ['missing'], ['q1'], ['tool-1'],
                               ['p1', 'missing'], [None], [1], [{}], [''], [' ']])
def test_invalid_or_missing_selected_catalog_ids_are_rejected_before_enqueue(tmp_path, ids, monkeypatch):
    queue = Queue(tmp_path/'jobs.sqlite')
    parent, key = benchmark_job(queue)
    def forbidden(*args, **kwargs):
        pytest.fail('Invalid routing must not enqueue a job')
    monkeypatch.setattr(queue, 'enqueue', forbidden)
    with pytest.raises(ValueError, match='selected_record_ids'):
        prepare_enrichment(queue, parent, [key], catalog_sources(),
                           routing={'power_mode':dict(selected_record_ids=ids)})


@pytest.mark.parametrize('changes', [
    dict(selected_assets=2), dict(selected_assets=True), dict(selected_assets='1'),
    dict(matching_assets=0), dict(matching_assets=11), dict(indexed_assets=0),
    dict(unassessed_outside_shortlist=10), dict(unassessed_outside_shortlist=-1),
    dict(limit=0), dict(matching_assets=1.5), dict(indexed_assets=None),
])
def test_routing_counts_must_agree_with_validated_selection(tmp_path, changes):
    queue = Queue(tmp_path/'jobs.sqlite')
    parent, key = benchmark_job(queue)
    manifest = routing_manifest(['p1'])
    manifest.update(changes)
    with pytest.raises(ValueError):
        prepare_enrichment(queue, parent, [key], catalog_sources(), routing={'power_mode':manifest})


@pytest.mark.parametrize('bad_id', [None, '', 'p2'])
def test_explicit_routing_rejects_ambiguous_or_unidentified_catalog_records(tmp_path, bad_id):
    queue = Queue(tmp_path/'jobs.sqlite')
    parent, key = benchmark_job(queue)
    catalog = catalog_sources()
    catalog[0]['id'] = bad_id
    with pytest.raises(ValueError, match='catalog record IDs'):
        prepare_enrichment(queue, parent, [key], catalog, routing={'power_mode':routing_manifest(['p2'])})
