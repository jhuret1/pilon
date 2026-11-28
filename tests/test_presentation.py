"""Display language cannot change evidence, matching decisions or the input model."""
from copy import deepcopy
import json

import pytest

from pilon.loop.benchmark_ui import build_view, render_benchmark
from pilon.loop.presentation import load_display_translations


def snapshot():
    evidence = dict(record_id='q1', quote='Queen', start=0, end=5, source='search',
                    interpretation='Un lit queen', rationale='Taille observée')
    criterion = dict(label='Taille de couchage', requested_value='grand lit', matched_value='queen',
                     fact_key='bedsize', record_id='q1', status='schema_represented',
                     value_status='observed_semantic', category_refs=['Beds'],
                     rationale='Taille observée', evidence=evidence)
    model = dict(assessment_scope='schema_only', observation_period='unknown', category='Furniture',
                 categories=['Beds'], facets=[dict(key='bedsize', label='Taille de couchage',
                                                  values=['queen'], scopes=['Beds'])])
    records = [dict(id='q1', role='demand', category='Furniture', query_class='Beds', text='Queen bed',
                    semantic_review=dict(interpretation='Un lit queen', criteria=[
                        dict(label='Taille de couchage', value='grand lit', matched_value='queen',
                             quote='Queen', start=0, end=5, rationale='Taille observée')]))]
    report = dict(model=model, benchmark=dict(
        already_represented=[criterion], candidates=[],
        analysis=dict(method='agent_semantic_review', status='reviewed')))
    return report, records


def test_translation_changes_display_only_after_grouping():
    report, records = snapshot()
    original = deepcopy((report, records))
    plain = build_view(report, records=records)
    translations = {'Taille de couchage':'Bed size', 'grand lit':'large bed',
                    'Un lit queen':'A queen bed', 'Taille observée':'Observed size',
                    'Queen':'DO NOT TRANSLATE SOURCE', 'queen':'DO NOT TRANSLATE CATALOG',
                    'Beds':'DO NOT TRANSLATE CATEGORY', 'q1':'DO NOT TRANSLATE ID'}
    view = build_view(report, records=records, display_translations=translations)
    assert (report, records) == original
    assert view['model'] == plain['model'] and view['attributes'] == plain['attributes']
    assert view['summary'] == plain['summary']
    assert view['product_view']['counts'] == plain['product_view']['counts']
    item = view['product_view']['covered'][0]
    assert item['id'] == plain['product_view']['covered'][0]['id']
    assert item['basis'] == 'existing_attribute' and item['record_ids'] == ['q1']
    assert item['label'] == 'Bed size'
    assert item['values'] == item['model_values'] == ['queen']
    assert item['category_refs'] == ['Beds']
    assert item['requested_values'] == ['large bed']
    assert item['rationales'] == ['Observed size']
    proof = item['proofs'][0]
    assert (proof['quote'], proof['start'], proof['end']) == ('Queen', 0, 5)
    assert proof['interpretation'] == 'A queen bed' and proof['rationale'] == 'Observed size'
    demand = view['demands'][0]
    assert demand['text'] == 'Queen bed'
    assert demand['semantic_review']['criteria'][0]['value'] == 'large bed'
    assert demand['semantic_review']['criteria'][0]['matched_value'] == 'queen'
    assert demand['represented'][0]['label'] == 'Bed size'
    assert view['presentation']['source_evidence_translated'] is False


def test_missing_translation_keeps_original_and_render_escapes_translation():
    report, records = snapshot()
    view = build_view(report, records=records, display_translations={})
    assert view['product_view']['covered'][0]['label'] == 'Taille de couchage'
    html = render_benchmark(report, records=records,
                            display_translations={'Taille de couchage':'</script><script>alert(1)</script>'})
    assert '</script><script>alert(1)</script>' not in html


@pytest.mark.parametrize('data', [[], {'language':'fr','strings':{}},
    {'language':'en','strings':{'a':None}}, {'language':'en','strings':{'':'x'}},
    {'language':'en','strings':{'a':' '}}])
def test_invalid_translation_bundle_is_rejected(tmp_path, data):
    path = tmp_path/'translations.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError):
        load_display_translations(path)


def test_translation_bundle_is_local_data(tmp_path):
    path = tmp_path/'translations.json'
    path.write_text(json.dumps(dict(language='en', strings={'Couleur':'Colour'})), encoding='utf-8')
    assert load_display_translations(path) == {'Couleur':'Colour'}
