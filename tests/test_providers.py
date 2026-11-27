import json
import pytest
from pilon.providers import OpenRouter
from pilon.fixture import corpus
from pilon.pipeline import ground
from pilon.identity import FAMILIES


def test_decision_target_binding_and_closed_choices(monkeypatch):
    provider = OpenRouter(None, 'test', '')
    facts = [dict(name='battery.runtime', definition='Operating hours.'),
             dict(name='screen.brightness', definition='Screen brightness.')]
    def response(stage, payload, path):
        answers = {}
        for key,q in payload['questions'].items():
            assert key.startswith('family_')
            assert sum(f['definition'] in q['instructions'] for f in facts) == 1
            answers[key] = dict(choice='power' if facts[0]['definition'] in q['instructions'] else 'performance', confidence=.9)
        return {'answers':dict(reversed(list(answers.items())))}
    monkeypatch.setattr(provider, 'call', response)
    assert [a['choice'] for a in provider.classify_families(facts,FAMILIES)] == ['power','performance']
    monkeypatch.setattr(provider, 'call', lambda *a,**k: {'answers':{}})
    with pytest.raises(ValueError):
        provider.classify_families(facts,FAMILIES)


def test_invalid_embedding_response_is_rejected(monkeypatch):
    p = OpenRouter(None, '', '')
    monkeypatch.setattr(p, 'call', lambda *a,**k: {'data':[dict(index=0, embedding=[1.,0.])]})
    with pytest.raises(ValueError, match='1024'):
        p.embed(['concept card'])


def test_real_langextract_adapter_with_mocked_inference(monkeypatch):
    pytest.importorskip('langextract')
    p = OpenRouter(None, '', '')
    review = corpus()['items'][0]['reviews'][0]
    expected = review['expected_extractions']
    response = {'extractions':[{'fact': e['quote'], 'fact_attributes':e['attributes']} for e in expected]}
    monkeypatch.setattr(p, 'chat', lambda *args,**kwargs: json.dumps(response))
    result = p.extract(review['text'])
    assert len(result) == 2
    assert all(ground(review['text'], e)['usable'] for e in result)
    assert result[1]['attributes']['presence'] == 'absent'
