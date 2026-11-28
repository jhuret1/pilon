from copy import deepcopy
import json
import socket

import pytest

from pilon import model_review
from pilon.loop.store import Queue
from pilon.providers import Client


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Live network is forbidden in connector tests')
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)


def inputs():
    model = dict(category='Tools', synthetic=True, facets=[
        dict(key='power', label='Power', aliases=['Power source'], values=['corded', 'cordless'])], categories=[])
    records = [dict(id='q1', role='demand', source='search', category='Tools', text='cordless drill', count=1)]
    config = dict(version=1, provider=dict(kind='ollama', base_url='http://127.0.0.1:11434/v1',
                  model='test-model', max_output_tokens=300),
                  limits=dict(max_requests=10, max_input_chars=120000, max_estimated_cost_usd=10,
                              input_price_per_million=1, output_price_per_million=1),
                  benchmark=dict(max_records=20, max_model_chars=60000))
    return model, records, config


def response(record):
    return dict(record_id=record['id'], interpretation='A drill powered without a cable.', criteria=[
        dict(label='Power', value='cordless', assessment='represented', fact_key='power',
             matched_value='cordless', proposed_key=None, category_refs=[], quote='cordless',
             start=0, end=8, rationale='The requested power source is an observed value.')])


class Transport:
    def __init__(self, handler=None, usage=True):
        self.requests = []
        self.handler = handler
        self.usage = usage

    def __call__(self, request, timeout):
        body = json.loads(request.data)
        content = body['messages'][-1]['content']
        record = json.loads(content.split('\nUnchanged demand record JSON:\n')[1])
        self.requests.append((record, body))
        answer = self.handler(record) if self.handler else response(record)
        payload = dict(choices=[dict(finish_reason='stop', message=dict(content=json.dumps(answer)))])
        if self.usage:
            payload['usage'] = dict(prompt_tokens=100, completion_tokens=30, cost=.002)
        return 200, json.dumps(payload).encode()


def run(tmp_path, model, records, config, **kwargs):
    return model_review.run_benchmark(model, records, config, output_dir=tmp_path/'out',
                                      db=tmp_path/'jobs.sqlite', **kwargs)


def test_dry_run_is_read_only_no_credentials_or_transport(tmp_path, monkeypatch):
    model, records, config = inputs()
    config['provider'].update(kind='openai_compatible', base_url='https://example.invalid/v1', api_key_env='UNSET_TEST_KEY')
    monkeypatch.delenv('UNSET_TEST_KEY', raising=False)
    transport = Transport()
    result = run(tmp_path, model, records, config, transport=transport)
    assert result['dry_run'] and result['pending_reviews'] == 1
    assert result['estimates']['estimated_cost_usd'] > 0
    assert result['destination']['base_url'] == 'https://example.invalid/v1'
    assert result['inference'] is None
    assert not transport.requests and not list(tmp_path.iterdir())


@pytest.mark.parametrize('problem', ['model_size', 'record_count', 'request_size', 'duplicate', 'category', 'role', 'empty'])
def test_all_inputs_preflight_before_any_call(tmp_path, problem):
    model, records, config = inputs()
    records.append(dict(records[0], id='q2'))
    if problem == 'model_size':
        config['benchmark']['max_model_chars'] = 10
    elif problem == 'record_count':
        config['benchmark']['max_records'] = 1
    elif problem == 'request_size':
        records[1]['text'] = 'x' * 120001
    elif problem == 'duplicate':
        records[1]['id'] = 'q1'
    elif problem == 'category':
        records[1]['category'] = 'Other'
    elif problem == 'role':
        records[1]['role'] = 'catalog'
    else:
        records[1]['text'] = ''
    transport = Transport()
    with pytest.raises(ValueError):
        run(tmp_path, model, records, config, execute=True, transport=transport)
    assert not transport.requests and not list(tmp_path.iterdir())


def test_full_context_enqueues_only_benchmark_and_replays_without_calls(tmp_path):
    model, records, config = inputs()
    model['facets'][0]['values'].extend(['mode_' + str(i) for i in range(200)])
    original = deepcopy((model, records, config))
    transport = Transport()
    result = run(tmp_path, model, records, config, execute=True, transport=transport)
    assert 'mode_199' in transport.requests[0][1]['messages'][-1]['content']
    job = Queue(tmp_path/'jobs.sqlite').get(result['job_id'])
    assert job['payload']['synthetic'] is True and job['payload']['options']['through'] == 'benchmark'
    assert job['payload']['options']['inference']['calls'] == 1
    assert job['payload']['options']['inference']['provider_cost_usd'] == .002
    assert job['stage'] == 'benchmark' and job['result']['projection'] is None
    assert job['result']['extractions'] == []
    assert job['result']['metrics']['llm_calls'] == 1
    assert job['result']['metrics']['api_cost_usd'] == .002
    assert job['payload']['options']['inference'] == result['inference']
    assert all(job['result']['metrics']['inference'][key] == value
               for key, value in result['inference'].items() if key != 'sessions')
    assert job['result']['benchmark']['analysis']['execution'] == 'model_connector'
    assert result['pending_reviews'] == 0 and result['completed_reviews'] == 1
    assert job['payload']['records'][0]['semantic_review']['criteria'][0]['matched_value'] == 'cordless'
    assert (model, records, config) == original
    def no_client(*args, **kwargs):
        pytest.fail('A complete replay must not construct another provider client')
    repeated = run(tmp_path, model, records, config, execute=True, client_factory=no_client)
    assert repeated['job_id'] == result['job_id'] and repeated['inference'] == result['inference']
    assert len(transport.requests) == 1


@pytest.mark.parametrize('change', [
    {'quote': 'rewritten'}, {'start': 1}, {'end': True}, {'fact_key': 'invented'},
    {'matched_value': 'Cordless'}, {'matched_value': None}, {'category_refs': ['unknown']},
    {'assessment': 'attribute_gap', 'fact_key': None, 'matched_value': None, 'proposed_key': 'new_power'},
    {'assessment': 'attribute_gap', 'fact_key': None, 'matched_value': None, 'label': 'New fact'},
    {'assessment': 'value_gap', 'matched_value': None},
])
def test_invalid_claims_become_unresolved_with_exact_full_source(change):
    model, records, _ = inputs()
    answer = response(records[0])
    answer['criteria'][0].update(change)
    reviewed, invalid = model_review.validate_response(model, records[0], answer)
    assert invalid == 1
    criterion = reviewed['criteria'][0]
    assert criterion['assessment'] == 'unresolved' and criterion['fact_key'] is None
    assert records[0]['text'][criterion['start']:criterion['end']] == criterion['quote']


def test_valid_new_value_new_attribute_and_ambiguity_are_distinct():
    model, records, _ = inputs()
    answer = response(records[0])
    base = answer['criteria'][0]
    answer['criteria'] = [
        dict(base, value='solar', assessment='value_gap', matched_value=None),
        dict(base, value='Yes', label='Repairability', assessment='attribute_gap', fact_key=None,
             matched_value=None, proposed_key='repairability'),
        dict(base, label='Product identity', value=None, assessment='unresolved', fact_key=None,
             matched_value=None, rationale='The product name has no unique model identity.'),
    ]
    reviewed, invalid = model_review.validate_response(model, records[0], answer)
    assert not invalid
    assert [c['assessment'] for c in reviewed['criteria']] == ['value_gap', 'attribute_gap', 'unresolved']


def test_unicode_offsets_and_valid_criteria_survive_invalid_sibling():
    model, records, _ = inputs()
    records[0]['text'] = '🔧 cordless drill'
    answer = response(records[0])
    answer['criteria'][0].update(start=2, end=10)
    answer['criteria'].append(dict(answer['criteria'][0], fact_key='imaginary'))
    reviewed, invalid = model_review.validate_response(model, records[0], answer)
    assert invalid == 1 and reviewed['criteria'][0]['assessment'] == 'represented'
    assert reviewed['criteria'][1]['assessment'] == 'unresolved'


def test_partial_failure_resumes_remaining_only_with_cumulative_budget_and_unknown_billing(tmp_path):
    model, records, config = inputs()
    records.append(dict(records[0], id='q2'))
    config['limits']['max_requests'] = 3
    def fail_second(record):
        if record['id'] == 'q2':
            raise RuntimeError('SECRET RAW PROVIDER BODY')
        return response(record)
    first = Transport(fail_second)
    with pytest.raises(ValueError, match='checkpointed') as failure:
        run(tmp_path, model, records, config, execute=True, transport=first)
    assert 'SECRET' not in str(failure.value)
    state = json.loads((tmp_path/'out/checkpoint.json').read_text())
    assert set(state['reviews']) == {'q1'} and state['sessions'][0]['calls'] == 2
    assert state['sessions'][0]['failed_calls'] == 1
    assert not (tmp_path/'jobs.sqlite').exists()
    assert 'SECRET' not in (tmp_path/'out/checkpoint.json').read_text()
    effective = []
    def factory(config, transport=None):
        effective.append(deepcopy(config))
        return Client(config, transport=transport)
    second = Transport()
    result = run(tmp_path, model, records, config, execute=True, client_factory=factory, transport=second)
    assert [r['id'] for r, _ in second.requests] == ['q2']
    assert effective[0]['limits']['max_requests'] == 1
    assert effective[0]['limits']['max_estimated_cost_usd'] < config['limits']['max_estimated_cost_usd']
    usage = result['inference']
    assert (usage['calls'], usage['failed_calls'], usage['usage_reported_calls']) == (3, 1, 2)
    assert usage['provider_cost_usd'] is None and usage['known_provider_cost_usd'] == .004
    assert usage['provider_cost_reported_calls'] == 2


@pytest.mark.parametrize('budget', ['requests', 'cost'])
def test_failed_attempts_cannot_reset_spending_guards_on_resume(tmp_path, budget):
    model, records, config = inputs()
    if budget == 'requests':
        config['limits']['max_requests'] = 1
    else:
        estimate = Client(config).estimate_request(model_review.review_messages(model_review.canonical(model), records[0]),
                                                  schema=model_review.review_schema(model, records[0]))
        config['limits']['max_estimated_cost_usd'] = estimate['estimated_cost_usd'] * 1.5
    def fail(record):
        raise TimeoutError('unknown remote charge')
    with pytest.raises(ValueError):
        run(tmp_path, model, records, config, execute=True, transport=Transport(fail))
    again = Transport()
    with pytest.raises(ValueError, match='[Bb]udget'):
        run(tmp_path, model, records, config, execute=True, transport=again)
    assert not again.requests


def test_inflight_reservation_is_durable_and_interrupt_does_not_auto_retry(tmp_path):
    model, records, config = inputs()
    def interrupt(record):
        state = json.loads((tmp_path/'out/checkpoint.json').read_text())
        assert state['inflight']['record_id'] == record['id']
        assert state['inflight']['reservation']['estimated_cost_usd'] > 0
        raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        run(tmp_path, model, records, config, execute=True, transport=Transport(interrupt))
    state = json.loads((tmp_path/'out/checkpoint.json').read_text())
    assert state['sessions'][0]['calls'] == 1 and state['inflight']
    assert not (tmp_path/'out/run.lock').exists()
    again = Transport()
    with pytest.raises(ValueError, match='unknown outcome'):
        run(tmp_path, model, records, config, execute=True, transport=again)
    assert not again.requests


@pytest.mark.parametrize('changed', ['model', 'source', 'config', 'prompt', 'prompt_text', 'schema', 'cache'])
def test_changed_or_corrupt_fingerprints_rejected_without_payment(tmp_path, monkeypatch, changed):
    model, records, config = inputs()
    run(tmp_path, model, records, config, execute=True, transport=Transport())
    if changed == 'model':
        model['facets'][0]['values'].append('battery')
    elif changed == 'source':
        records[0]['source'] = 'changed'
    elif changed == 'config':
        config['provider']['model'] = 'other'
    elif changed == 'prompt':
        monkeypatch.setattr(model_review, 'PROMPT_VERSION', 'next')
    elif changed == 'prompt_text':
        monkeypatch.setattr(model_review, 'SYSTEM_PROMPT', model_review.SYSTEM_PROMPT + '\nChanged instruction.')
    elif changed == 'schema':
        original = model_review.review_schema
        monkeypatch.setattr(model_review, 'review_schema', lambda m, r: dict(original(m, r), description='Changed contract'))
    else:
        path = tmp_path/'out/checkpoint.json'
        state = json.loads(path.read_text())
        state['reviews']['q1']['review']['criteria'][0]['matched_value'] = 'invented'
        path.write_text(json.dumps(state))
    transport = Transport()
    with pytest.raises(ValueError):
        run(tmp_path, model, records, config, execute=True, transport=transport)
    assert not transport.requests


def test_zero_priced_local_provider_keeps_unknown_bill_null(tmp_path):
    model, records, config = inputs()
    config['limits'].update(input_price_per_million=0, output_price_per_million=0, max_estimated_cost_usd=0)
    result = run(tmp_path, model, records, config, execute=True, transport=Transport(usage=False))
    assert result['inference']['provider_cost_usd'] is None
    assert result['inference']['estimated_cost_usd'] == 0
    assert result['inference']['usage_reported_calls'] == 0
    assert Queue(tmp_path/'jobs.sqlite').get(result['job_id'])['result']['metrics']['api_cost_usd'] is None


def test_invalid_response_is_checkpointed_once_as_unresolved(tmp_path):
    model, records, config = inputs()
    result = run(tmp_path, model, records, config, execute=True, transport=Transport(lambda r: {'criteria': []}))
    assert result['invalid_criteria'] == 1
    transport = Transport()
    repeated = run(tmp_path, model, records, config, execute=True, transport=transport)
    assert repeated['invalid_criteria'] == 1 and not transport.requests


@pytest.mark.parametrize('destination', ['same', 'database_ancestor', 'export_parent', 'file_parent'])
def test_unusable_destinations_fail_before_inference(tmp_path, destination):
    model, records, config = inputs()
    root, database = tmp_path/'out', tmp_path/'jobs.sqlite'
    if destination == 'same':
        database = root
    elif destination == 'database_ancestor':
        root = database/'out'
    elif destination == 'export_parent':
        database = root/'benchmark.json'/'jobs.sqlite'
    else:
        (tmp_path/'file').write_text('original')
        root = tmp_path/'file'/'out'
    transport = Transport()
    with pytest.raises(ValueError, match='distinct usable paths'):
        model_review.run_benchmark(model, records, config, output_dir=root, db=database,
                                   execute=True, transport=transport)
    assert not transport.requests
