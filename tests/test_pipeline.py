import copy
import json
import socket
from pathlib import Path
import numpy as np
import pytest
from pilon.fixture import corpus, FixtureProvider
from pilon.corpus import rows
from pilon.service import execute, snapshot
from pilon.pipeline import ground
from pilon.streaming import grounded
from pilon.store import Store, Paused, digest
from pilon.identity import card, candidates
from pilon.providers import OpenRouter
from pilon.app import create_app


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*a, **kw):
        raise AssertionError('Tests must not contact external services.')
    monkeypatch.setattr(socket.socket, 'connect', blocked)


@pytest.fixture
def source():
    return corpus()


def test_offline_end_to_end_and_idempotency(tmp_path, source):
    db = tmp_path/'state.sqlite'
    run = execute(db, source)
    assert run['status'] == 'completed'
    assert run['processed'] == 24
    assert len(run['facts']) == 12
    assert run['metrics']['extractions'] == 32
    assert run['metrics']['routes']['not_applicable'] == 2
    assert run['metrics']['calls'] == run['metrics']['cost'] == 0
    assert run['metrics']['precision'] is None
    assert run['metrics']['recall'] is None
    assert all(f['status'] == 'experimental_concept_not_validated' for f in run['facts'])
    for e in run['extractions']:
        assert run['rows'][e['review_index']]['text'][e['start']:e['end']] == e['quote']
        if e['fact_id']:
            assert e['attributes']['subject'] == 'reviewed_item'
    repeat = execute(db, source)
    assert repeat['id'] == run['id']
    assert repeat['extractions'] == run['extractions']
    assert repeat['finished'] == run['finished']


def test_resume_preserves_committed_reviews(tmp_path, source, monkeypatch):
    original = FixtureProvider.enrich
    calls = []
    def fail_once(self, row, extraction, candidates, **kwargs):
        if row['review_id'] == 'synthetic-review-03':
            raise Paused('Simulated interruption')
        return original(self, row, extraction, candidates, **kwargs)
    monkeypatch.setattr(FixtureProvider, 'enrich', fail_once)
    db = tmp_path/'resume.sqlite'
    run = execute(db, source)
    assert run['status'] == 'paused'
    assert run['processed'] == 2
    committed = copy.deepcopy(run['extractions'])
    monkeypatch.setattr(FixtureProvider, 'enrich', original)
    extract = FixtureProvider.extract
    def capture(self, text):
        calls.append(text)
        return extract(self, text)
    monkeypatch.setattr(FixtureProvider, 'extract', capture)
    resumed = execute(db, source)
    assert resumed['status'] == 'completed'
    assert resumed['id'] == run['id']
    assert resumed['extractions'][:len(committed)] == committed
    assert not any(row['text'] in calls for row in run['rows'][:2])


def test_cache_contracts_never_mix(tmp_path):
    store = Store(tmp_path/'vectors.sqlite')
    v = np.zeros(1024); v[0] = 1
    fake = store.put_vector('same card', v, model=FixtureProvider.embedding_contract)
    real = store.put_vector('same card', v, model=OpenRouter.embedding_contract)
    assert fake != real
    assert np.array_equal(store.vector(fake), store.vector(real))
    with pytest.raises(ValueError):
        store.put_vector('bad', np.zeros(1024))


def test_exact_alignment_preserves_negation_and_context(source):
    text = source['items'][0]['reviews'][0]['text']
    e = source['items'][0]['reviews'][0]['expected_extractions'][1]
    assert ground(text, e)['usable']
    broken = copy.deepcopy(e); broken['attributes']['condition'] = 'working'
    assert not ground(text, broken)['usable']
    bad_context = copy.deepcopy(e); bad_context['attributes']['context'] = 'Invented context.'
    assert not ground(text, bad_context)['usable']
    bad = {**e, 'start': 0, 'end': 1}
    assert grounded(text, bad)['usable']
    assert not grounded(text+' '+text, bad)['usable']
    assert not grounded(text, {**e, 'quote': 'A cable was not supplied.'})['usable']


def test_no_mention_is_not_absence(source):
    f = FixtureProvider(None, '', '')
    text = source['items'][7]['reviews'][1]['text']
    assert f.extract(text) == []
    with pytest.raises(ValueError):
        f.extract('An unseen customer review.')


def test_name_collision_survives_outside_top_k():
    facts = [dict(id='same', name='cable.presence', definition='A different scope.'),
             dict(id='near', name='battery.runtime', definition='Battery duration.')]
    vectors = {'same': np.array([-1., 0.]), 'near': np.array([1., 0.])}
    matches = candidates(dict(concept='cable.presence', definition='Included cable.'), np.array([1.,0.]), facts, vectors, 1)
    assert [f['id'] for f in matches] == ['same','near']
    assert card(dict(concept='cable.presence', definition='Included cable.', value='absent')) == card(dict(concept='cable.presence', definition='Included cable.', value='present'))


def test_budget_and_uncertain_retry(tmp_path):
    s = Store(tmp_path/'budget.sqlite')
    run = s.create({'budget': .1}, [], 'budget-test', [])
    run['status'] = 'running'; s.save(run)
    cid, cached = s.reserve(run['id'], 'first', 'extraction', .08, {})
    assert cached is None
    with pytest.raises(Paused):
        s.reserve(run['id'], 'next', 'extraction', .03, {})
    s.finish_call(cid, None, 10, 'Unknown outcome')
    with pytest.raises(Paused):
        s.reserve(run['id'], 'first', 'extraction', .08, {})
    with pytest.raises(ValueError):
        s.set_status(run['id'], 'running')


def test_success_cache_and_idempotency_conflict(tmp_path):
    s = Store(tmp_path/'budget.sqlite')
    r = s.create({'budget': 1}, [], 'same-request', [])
    r['status'] = 'running'; s.save(r)
    cid,_ = s.reserve(r['id'], 'key', 'decision', .1, {})
    s.finish_call(cid, {'usage':{'cost':.01}, 'answers':{}}, 1)
    assert s.reserve(r['id'], 'key', 'decision', .1, {})[1]['usage']['cost'] == .01
    with pytest.raises(ValueError):
        s.create({'budget':2}, [], 'same-request', [])


@pytest.mark.parametrize('budget', [float('nan'), float('inf'), -1])
def test_invalid_budget(tmp_path, source, budget):
    with pytest.raises(ValueError):
        execute(tmp_path/'invalid.sqlite', source, budget=budget)


def test_no_paid_call_without_opt_in(tmp_path, source, monkeypatch):
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    with pytest.raises(ValueError, match='allow-paid'):
        execute(tmp_path/'paid.sqlite', source, provider='openrouter', budget=1)
    with pytest.raises(ValueError, match='OPENROUTER_API_KEY'):
        execute(tmp_path/'paid.sqlite', source, provider='openrouter', budget=1, allow_paid=True)


def test_viewer_is_read_only_and_local(tmp_path, source):
    db = tmp_path/'ui.sqlite'
    run = execute(db, source)
    client = create_app(db).test_client()
    assert client.get('/').status_code == 200
    assert client.get('/assets/app.js').status_code == 200
    assert client.get('/api/runs/'+run['id']).json['metrics']['calls'] == 0
    assert client.get('/api/runs/missing').status_code == 404
    assert client.post('/api/runs').status_code == 405
    assert client.get('/', headers={'Host':'attacker.example'}).status_code == 403
    assert 'frame-ancestors' in client.get('/').headers['Content-Security-Policy']
    assert Store(db).calls(run['id']) == []


def test_source_order_and_duplicates(source):
    original = rows(source)
    source['source_order'] = [r['review_id'] for r in reversed(original)]
    assert rows(source)[0]['review_id'] == original[-1]['review_id']
    source['items'][1]['reviews'][0]['id'] = source['items'][0]['reviews'][0]['id']
    with pytest.raises(ValueError):
        rows(source)
