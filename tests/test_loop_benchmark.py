from copy import deepcopy
import json
import pytest

from pilon.loop.benchmark import benchmark
from pilon.facets.commands import EXAMPLE
from pilon.facets.io import read_signals


def sample():
    model = json.loads((EXAMPLE/'model.json').read_text(encoding='utf-8'))
    records = list(read_signals(EXAMPLE/'signals.jsonl'))
    return model, records


def test_demand_survives_without_catalog_evidence():
    model, records = sample()
    records = [r for r in records if r['role']!='catalog']
    original = deepcopy((model,records))
    result = benchmark(model,records)
    toe = next(c for c in result['candidates'] if c['key']=='toe_box')
    assert toe['demand_events']==34
    assert toe['gap_type']=='schema_gap'
    assert toe['status']=='needs_extraction'
    assert toe['demand_records']
    assert original==(model,records)


def test_unrecognized_demand_is_retained_and_not_fabricated():
    model,_ = sample()
    rows=[dict(id='q',role='demand',source='search',category=model['category'],date=model['window_start'],
               text='Something nobody has described yet.')]
    candidate, = benchmark(model,rows)['candidates']
    assert candidate['gap_type']=='unresolved_intent'
    assert candidate['aliases']==[]
    assert candidate['status']=='needs_definition'


def test_grounded_intent_is_independent_of_vocabulary():
    model,_ = sample()
    text='A shoe with a replaceable sole.'
    row=dict(id='q',role='demand',source='chat',category=model['category'],date=model['window_start'],text=text,
             intents=[dict(key='sole.replacement',label='Replaceable sole',definition='Whether the sole can be replaced.',
                           start=14,end=30,quote=text[14:30])])
    candidate,=benchmark(model,[row])['candidates']
    assert candidate['key']=='sole_replacement'
    row['intents'][0]['quote']='a made up quote'
    with pytest.raises(ValueError,match='mismatch'):
        benchmark(model,[row])


def test_existing_schema_is_coverage_gap_then_retrieval_gap():
    model,_=sample()
    model.update(existing_facets=['toe box'],assignments=[])
    rows=[dict(id='q',role='demand',source='search',category=model['category'],date=model['window_start'],text='toe box',outcome='no_results'),
          dict(id='p',role='catalog',source='pim',category=model['category'],text='A shoe.',product_id='P1')]
    assert benchmark(model,rows)['candidates'][0]['gap_type']=='coverage_gap'
    model['assignments']=[dict(fact_key='toe_box',product_id='P1',value='wide')]
    assert benchmark(model,rows)['candidates'][0]['gap_type']=='retrieval_gap'
    rows[0].pop('outcome')
    assert not benchmark(model,rows)['candidates']


def test_events_are_idempotent_and_external_not_customer_demand():
    m,r=sample()
    assert benchmark(m,r)==benchmark(m,r+r)
    assert not benchmark(m,[x for x in r if x['role']=='external'])['candidates']
    r.append({**r[0],'count':200})
    with pytest.raises(ValueError,match='Conflicting'):
        benchmark(m,r)


def test_display_labels_and_catalog_labels_keep_existing_facet_key():
    m,_=sample()
    m.update(existing_facets=['shoe_toe_shape'], facets=[dict(key='shoe_toe_shape',label='Toe box',
             definition='Space around toes',aliases=['front space'])], aliases={'Toe box':['room for toes']})
    rows=[dict(id='q',role='demand',source='search',category=m['category'],date=m['window_start'],text='room for toes'),
          dict(id='p',role='catalog',source='pim',category=m['category'],text='Toe box: wide',product_id='P1')]
    c,=benchmark(m,rows)['candidates']
    assert c['key']=='shoe_toe_shape'
    assert c['gap_type']=='coverage_gap'


def test_invalid_alias_array_is_rejected():
    m,r=sample();m['aliases']['toe box']='not a list'
    with pytest.raises(ValueError,match='aliases'):
        benchmark(m,r)
