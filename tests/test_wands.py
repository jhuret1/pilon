from copy import deepcopy
from hashlib import sha256
import io
import json

import pytest

from pilon import wands
from pilon.loop.benchmark import benchmark
from pilon.loop.store import Queue
from pilon.loop.worker import run_once


def fixture_model():
    return wands.schema_from_rows([
        dict(product_id='PRIVATE_PRODUCT_ID', product_name='PRIVATE_NAME',
             product_description='PRIVATE_DESCRIPTION', product_class='Sofas',
             product_features='color:red|color:blue|material:solid wood| :invalid|broken'),
        dict(product_id='OTHER_PRODUCT', product_class='Lamps', product_features='color:green|bulb:yes'),
        dict(product_class='Sofas', product_features='color: red |color:red|ratio:1:2'),
    ])[0]


def request(text, category='Sofas'):
    return dict(id='q', role='demand', source='search', category='WANDS', text=text,
                query_class=category, count=1)


def annotated_request(value):
    row = request('color ' + value)
    row['intents'] = [dict(label='color', start=0, end=5, quote='color', value=value,
                          value_evidence=dict(start=6, end=len(row['text']), quote=value))]
    return row


def test_model_retains_values_in_category_scope_but_no_product_instances():
    model = fixture_model()
    color = next(f for f in model['facets'] if f['label']=='color')
    assert color['values'] == ['blue', 'green', 'red']
    assert color['value_scopes'] == {'blue':['Sofas'], 'green':['Lamps'], 'red':['Sofas']}
    assert color['values_status'] == 'observed_not_exhaustive'
    assert next(f for f in model['facets'] if f['label']=='ratio')['values'] == ['1:2']
    assert not model['assignments']
    exported = json.dumps(model)
    assert 'PRIVATE' not in exported and 'OTHER_PRODUCT' not in exported
    assert all(f['label'] not in ('', 'broken') for f in model['facets'])


def test_requests_are_original_undated_samples_without_fabricated_frequency():
    row, = wands.requests_from_rows([dict(query_id='001', query=' Red SOFA? ', query_class='Sofas')])
    assert row['text'] == ' Red SOFA? '
    assert row['original_query_id'] == '001' and row['source_order'] == 0
    assert 'date' not in row and row['count_basis']=='one_sampled_query'
    assert 'product_id' not in row
    with pytest.raises(ValueError, match='Duplicate'):
        wands.requests_from_rows([dict(query_id='1', query='x')]*2)


def test_multicategory_product_contributes_values_to_each_class():
    model, stats = wands.schema_from_rows([dict(product_class='Beds|Kids Beds', product_features='woodspecies:acacia')])
    assert model['categories'] == ['Beds', 'Kids Beds']
    facet, = model['facets']
    assert facet['value_scopes']['acacia'] == ['Beds', 'Kids Beds']
    assert stats['categories']==2 and stats['attribute_values']==1


def test_schema_only_does_not_conflate_value_domain_and_product_coverage():
    model, row = fixture_model(), request('color red')
    before = deepcopy((model, row))
    out = benchmark(model, [row])
    assert out['metrics']['inventory_products'] is None
    assert out['candidates'] == []
    represented, = out['already_represented']
    assert represented['value_status']=='observed_exact'
    assert represented['requested_value']=='red'
    assert represented['value_evidence']['quote']=='red'
    assert (model, row)==before
    out = benchmark(model, [request('bulb', 'Sofas')])
    assert out['candidates'][0]['gap_type']=='unresolved_intent'
    assert not out['already_represented']


def test_missing_values_are_scoped_proposals_with_grounded_evidence():
    model = fixture_model()
    rows = [annotated_request('green'), {**annotated_request('purple'), 'id':'q2'}]
    out = benchmark(model, rows)
    assert len(out['candidates'])==2
    assert {c['requested_value'] for c in out['candidates']} == {'green', 'purple'}
    for candidate in out['candidates']:
        assert candidate['gap_type']=='value_gap'
        assert candidate['value_status']=='not_observed_exact'
        assert candidate['semantic_validation']=='not_performed'
        assert candidate['value_evidence']['quote']==candidate['requested_value']
    rows[0]['intents'][0]['value_evidence']['quote']='fabricated'
    with pytest.raises(ValueError, match='quote mismatch'):
        benchmark(model, rows)


def test_undecoded_value_is_unknown_not_absent():
    out = benchmark(fixture_model(), [request('color ultraviolet')])
    assert out['already_represented'][0]['value_status']=='not_assessed'
    assert not out['candidates']
    model = fixture_model()
    model.pop('observation_period')
    with pytest.raises(ValueError):
        benchmark(model, [request('color')])


def test_two_values_for_one_attribute_survive_in_the_same_request():
    row = request('color purple or mauve')
    row['intents'] = [dict(label='color', quote='color', start=0, end=5, value=v,
                          value_evidence=dict(quote=v,start=row['text'].index(v),end=row['text'].index(v)+len(v)))
                      for v in ('purple', 'mauve')]
    result = benchmark(fixture_model(), [row])
    assert {c['requested_value'] for c in result['candidates']} == {'purple', 'mauve'}
    assert all(c['demand_records'][0]['value_evidence']['quote']==c['requested_value'] for c in result['candidates'])


def test_benchmark_only_does_not_run_other_products_and_is_idempotent(tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError('Extract/Ingest must not run')
    queue = Queue(tmp_path/'queue.sqlite')
    jid = queue.enqueue(fixture_model(), [request('color red')], synthetic=False)
    out = run_once(queue, job_id=jid, hooks={'extract':forbidden, 'projection':forbidden})
    assert out['status']=='completed' and out['stage']=='benchmark'
    assert out['projection'] is None and out['extractions']==[]
    assert out['metrics']['llm_calls']==0 and out['metrics']['api_cost_usd']==0
    assert run_once(queue, job_id=jid) is None


def test_streaming_import_and_verified_offline_reuse(tmp_path, monkeypatch):
    query = b'query_id\tquery\tquery_class\n1\tred sofa\tSofas\n'
    product = b'product_id\tproduct_class\tproduct_features\nSECRET\tSofas\tcolor:red|color:blue\n'
    fetched=[]
    def fetch(req, **kwargs):
        fetched.append(req.full_url)
        if req.full_url.endswith('/query.csv'):
            return io.BytesIO(query)
        if req.full_url.endswith('/product.csv'):
            return io.BytesIO(product)
        assert req.full_url.endswith('/LICENSE')
        return io.BytesIO(b'MIT fixture license')
    monkeypatch.setattr(wands.urllib.request, 'urlopen', fetch)
    model, records, manifest = wands.import_wands(tmp_path)
    assert manifest['attribute_values']==2 and manifest['retained_product_records']==0
    assert manifest['sources'][1]['sha256']==sha256(product).hexdigest()
    assert manifest['observed_value_domains_retained']
    assert not manifest['product_value_assignments_retained']
    assert set(p.name for p in tmp_path.iterdir())=={'model.json','queries.jsonl','manifest.json','LICENSE-WANDS.txt'}
    assert 'SECRET' not in (tmp_path/'model.json').read_text()
    assert len(fetched)==3
    assert wands.import_wands(tmp_path)==(model,records,manifest)
    assert len(fetched)==3
    (tmp_path/'model.json').write_text('{}')
    with pytest.raises(ValueError, match='Changed or incomplete'):
        wands.import_wands(tmp_path)
