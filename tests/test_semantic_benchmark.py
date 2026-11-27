from copy import deepcopy
import json

import pytest

from pilon.loop.benchmark import benchmark
from pilon.loop.semantic import annotate_records
from pilon.loop.store import fingerprint


def inputs():
    model = dict(category='WANDS', assessment_scope='schema_only', observation_period='unknown',
                 categories=['Desks', 'Kids Desks', 'Lamps'],
                 facets=[dict(key='color',label='Color',values=['white'],scopes=['Desks'],
                              value_scopes={'white':['Desks']})])
    records = [dict(id='q',role='demand',source='search',category='WANDS',query_class='Kids Desks',
                    text='desk for kids',count=1)]
    reviews = [dict(record_id='q',interpretation='Bureau destiné aux enfants.',criteria=[
        dict(label='Public',value='enfants',quote='kids',start=9,end=13,assessment='filter_proposal',
             fact_key=None,matched_value=None,category_refs=['Kids Desks'],proposed_key='target_audience',
             rationale='La catégorie Kids Desks permet de proposer un filtre Public. Les filtres actuels sont inconnus.')])]
    return model, records, reviews


def test_category_encoded_need_becomes_filter_proposal_not_missing_attribute():
    model, rows, reviews = inputs()
    before = deepcopy((model, rows, reviews))
    annotated = annotate_records(model, rows, reviews)
    result = benchmark(model, annotated)
    c, = result['candidates']
    assert c['gap_type']=='filter_proposal' and c['requested_value']=='enfants'
    assert c['category_refs']==['Kids Desks'] and c['filter_availability']=='not_provided'
    assert c['demand_records'][0]['quote']=='kids'
    assert result['analysis']['reviewed_records']==1
    assert not result['analysis']['independent_audit']
    assert result['metrics']['inventory_products'] is None
    assert (model, rows, reviews)==before


@pytest.mark.parametrize('error', ['span','category','attribute','value','incomplete','duplicate','scope'])
def test_invalid_semantic_reviews_fail_closed(error):
    model, rows, reviews = inputs()
    c=reviews[0]['criteria'][0]
    if error=='span':
        c['quote']='children'
    elif error=='category':
        c['category_refs']=['Invented category']
    elif error=='attribute':
        c['fact_key']='invented'
    elif error=='value':
        c.update(fact_key='color',matched_value='not in model')
    elif error=='scope':
        c.update(fact_key='color',matched_value='white',category_refs=['Lamps'])
    elif error=='incomplete':
        reviews=[]
    elif error=='duplicate':
        reviews=reviews*2
    with pytest.raises(ValueError):
        annotate_records(model, rows, reviews)


def test_represented_semantic_synonym_has_source_and_model_references():
    model, rows, reviews = inputs()
    rows[0].update(text='bureau blanc',query_class='Desks')
    reviews[0]['criteria']=[dict(label='Couleur',value='blanc',quote='blanc',start=7,end=12,
        assessment='represented',fact_key='color',matched_value='white',category_refs=['Desks'],
        rationale='Blanc correspond à la valeur white observée pour les bureaux.')]
    result=benchmark(model,annotate_records(model,rows,reviews))
    assert not result['candidates']
    entry,=result['already_represented']
    assert entry['matched_value']=='white' and entry['evidence']['quote']=='blanc'
    assert entry['value_status']=='observed_semantic'


def test_annotations_cannot_be_replayed_against_a_changed_model():
    model, rows, reviews = inputs()
    annotated=annotate_records(model,rows,reviews)
    model['categories'].append('New category')
    assert annotated[0]['reviewed_model_hash']!=fingerprint(model)
    with pytest.raises(ValueError,match='snapshot'):
        benchmark(model,annotated)


def test_unresolved_modifier_survives_alongside_represented_category():
    model, rows, reviews = inputs()
    reviews[0]['criteria'].extend([
        dict(label='Type',value='bureau',quote='desk',start=0,end=4,assessment='represented',
             category_refs=['Desks'],rationale='Catégorie bureaux présente.'),
        dict(label='Sens incertain',value=None,quote='for',start=5,end=8,assessment='unresolved',
             category_refs=[],rationale='Fixture : ce critère doit rester visible.')])
    result=benchmark(model,annotate_records(model,rows,reviews))
    assert len(result['already_represented'])==1
    assert {c['gap_type'] for c in result['candidates']}=={'filter_proposal','unresolved_intent'}


def test_changed_context_invalidates_even_an_unchanged_evidence_span():
    model, rows, reviews = inputs()
    annotated=annotate_records(model,rows,reviews)
    annotated[0]['text'] += ' but not this kind'
    with pytest.raises(ValueError,match='source context'):
        benchmark(model,annotated)


def test_semantic_review_cli_round_trip_and_hash_rejection(tmp_path, monkeypatch, capsys):
    from pilon.cli import main
    from pilon import wands
    from pilon.loop.store import Queue
    model, rows, reviews = inputs()
    monkeypatch.setattr(wands, 'import_wands', lambda *a,**k:(model,rows,{'attribute_values':1}))
    path=tmp_path/'decisions.json'
    decision_file=dict(model_hash=fingerprint(model),records_hash=fingerprint(rows),reviews=reviews)
    path.write_text(json.dumps(decision_file),encoding='utf8')
    args=['benchmark','review','--reviews',str(path),'--db',str(tmp_path/'queue.sqlite')]
    assert main(args)==0
    result=json.loads(capsys.readouterr().out)
    stored=Queue(tmp_path/'queue.sqlite').get(result['job_id'])['result']
    assert stored['benchmark']['analysis']['reviewed_records']==1
    assert stored['metrics']['provider']=='imported_agent_decisions'
    assert stored['candidates'][0]['gap_type']=='filter_proposal'
    assert main(args)==0
    assert json.loads(capsys.readouterr().out)['job_id']==result['job_id']
    decision_file['model_hash']='changed'
    path.write_text(json.dumps(decision_file),encoding='utf8')
    with pytest.raises(SystemExit) as failure:
        main(args)
    assert failure.value.code==2
