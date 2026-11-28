from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from email.message import Message
from io import BytesIO
import json
from pathlib import Path
import socket
import threading
from urllib.request import HTTPSHandler, ProxyHandler, build_opener
from urllib.response import addinfourl

import pytest

from pilon import providers
from pilon.providers import BudgetExceeded, Client, ConfigError, ProviderError, load_config


MESSAGES = [dict(role='user', content='Classify this demand as JSON.')]
SCHEMA = dict(type='object', properties={'ok':{'type':'boolean'}}, required=['ok'], additionalProperties=False)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Provider tests must never use the network')
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)


@pytest.fixture
def config():
    return dict(version=1,
                provider=dict(kind='openrouter', base_url='https://api.example.test/v1', model='test-model',
                              api_key_env='PILON_TEST_KEY', response_format='json_object', temperature=0,
                              max_output_tokens=3000, timeout_seconds=60),
                limits=dict(max_requests=25, max_input_chars=120000, max_estimated_cost_usd=1,
                            input_price_per_million=0.10, output_price_per_million=0.40),
                benchmark=dict(max_records=20, max_model_chars=60000))


@pytest.fixture
def key(monkeypatch):
    value = 'test-only-environment-secret'
    monkeypatch.setenv('PILON_TEST_KEY', value)
    return value


def completion(content='{"ok":true}', *, finish='stop', usage=None):
    response = dict(choices=[dict(finish_reason=finish, message=dict(role='assistant', content=content))])
    if usage is not None:
        response['usage'] = usage
    return json.dumps(response).encode('utf-8')


class FakeTransport:
    def __init__(self, body=None, status=200, error=None):
        self.body = completion() if body is None else body
        self.status, self.error = status, error
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        if self.error:
            raise self.error
        return self.status, self.body


def save(tmp_path, config):
    path = tmp_path/'config.json'
    path.write_text(json.dumps(config), encoding='utf-8')
    return path


def test_loading_and_construction_are_offline_and_do_not_resolve_keys(tmp_path, config, monkeypatch):
    monkeypatch.delenv('PILON_TEST_KEY', raising=False)
    del config['provider']['response_format']
    config['provider']['base_url'] += '/'
    validated = load_config(save(tmp_path, config))
    assert validated['provider']['response_format'] == 'json_object'
    assert validated['provider']['base_url'] == 'https://api.example.test/v1'
    client = Client(validated)
    estimate = client.estimate_request(MESSAGES)
    assert estimate['estimated_cost_usd'] > 0
    assert client.report()['calls'] == 0
    assert client.report()['provider_cost_usd'] is None
    assert 'api_key' not in validated['provider']
    assert 'response_format' not in config['provider']


@pytest.mark.parametrize('section,field,value', [
    ('provider', 'api_key', 'never-persist-this'),
    ('provider', 'apiKey', 'never-persist-this'),
    ('provider', 'headers', {'Authorization':'never-persist-this'}),
    ('limits', 'token', 'never-persist-this'),
    ('provider', 'api_key_env', 'not an env name'),
    ('provider', 'api_key_env', None),
    ('provider', 'kind', 'unsupported'),
    ('provider', 'kind', []),
    ('provider', 'model', ''),
    ('provider', 'model', 'bad\nmodel'),
    ('provider', 'response_format', 'markdown'),
    ('provider', 'response_format', {}),
    ('provider', 'temperature', True),
    ('provider', 'temperature', -1),
    ('provider', 'temperature', 3),
    ('provider', 'temperature', float('nan')),
    ('provider', 'max_output_tokens', 0),
    ('provider', 'max_output_tokens', 1.5),
    ('provider', 'timeout_seconds', 0),
    ('provider', 'timeout_seconds', float('inf')),
    ('limits', 'max_requests', -1),
    ('limits', 'max_requests', True),
    ('limits', 'max_input_chars', 0),
    ('limits', 'max_estimated_cost_usd', -1),
    ('limits', 'max_estimated_cost_usd', float('inf')),
    ('limits', 'input_price_per_million', 0),
    ('limits', 'output_price_per_million', '0.4'),
    ('benchmark', 'max_records', False),
    ('benchmark', 'max_model_chars', -1),
])
def test_unsafe_fields_and_numbers_are_rejected(config, section, field, value):
    config[section][field] = value
    with pytest.raises(ConfigError) as error:
        Client(config)
    assert 'never-persist-this' not in str(error.value)


@pytest.mark.parametrize('url', [
    'http://api.example.test/v1', 'http://192.168.1.1/v1', 'http://0.0.0.0/v1',
    'http://127.0.0.1.evil.test/v1', 'http://localhost.evil.test/v1',
    'http://127.1/v1', 'http://2130706433/v1', 'http://[::]/v1',
    'https://user:never-persist-this@api.example.test/v1',
    'https://api.example.test/v1?api_key=never-persist-this',
    'https://api.example.test/v1#never-persist-this',
    'https://api.example.test/v1?', 'https://api.example.test/v1#',
    'https://api.example.test:99999/v1', 'https://api.example.test:bad/v1',
    'https://api.example.test:0/v1', 'https://api.example.test/../v1',
    'https://api.example.test/%2e%2e/v1', 'https://api.example.test/v1/chat/completions',
    'https://api.example.test\\@evil.test/v1', 'https://%6cocalhost/v1',
    ' https://api.example.test/v1', 'https://api.example.test\n/v1',
    'ftp://api.example.test/v1', 'file:///secret', '//api.example.test/v1',
    'https:///v1', 'https://[::1/v1', '', None,
])
def test_unsafe_urls_are_rejected_without_network(config, url):
    config['provider']['base_url'] = url
    with pytest.raises(ConfigError) as error:
        Client(config)
    assert 'never-persist-this' not in str(error.value)


@pytest.mark.parametrize('url', ['http://localhost:11434/v1/', 'http://127.0.0.1:11434/v1', 'http://[::1]:11434/v1'])
def test_local_ollama_needs_no_dummy_key_and_accepts_zero_prices(config, url):
    config['provider'].update(kind='ollama', base_url=url)
    del config['provider']['api_key_env']
    config['limits'].update(input_price_per_million=0, output_price_per_million=0, max_estimated_cost_usd=0)
    fake = FakeTransport()
    client = Client(config, fake)
    assert client.complete_json(MESSAGES) == {'ok':True}
    request, _ = fake.requests[0]
    assert request.full_url == url.rstrip('/') + '/chat/completions'
    assert request.get_header('Authorization') is None
    assert client.report()['estimated_cost_usd'] == 0
    assert client.report()['provider_cost_usd'] is None


@pytest.mark.parametrize('mutation', [
    lambda c: c.update(version=True), lambda c: c.update(version=2),
    lambda c: c.update(api_key='never-persist-this'), lambda c: c.pop('limits'),
    lambda c: c.update(provider=[]), lambda c: c.update(benchmark=None),
    lambda c: c['provider'].pop('api_key_env'), lambda c: c['limits'].pop('max_requests'),
])
def test_config_shape_and_remote_key_reference_are_validated(config, mutation):
    mutation(config)
    with pytest.raises(ConfigError):
        Client(config)


@pytest.mark.parametrize('text', ['{"version":1,"version":1}', '{"value":NaN}', '{"value":1e999}', 'not json', '[]'])
def test_load_rejects_malformed_or_nonstandard_json(tmp_path, text):
    path = tmp_path/'config.json'
    path.write_text(text, encoding='utf-8')
    with pytest.raises(ConfigError):
        load_config(path)


def test_load_missing_file_is_safe(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path/'absent.json')


@pytest.mark.parametrize('kind', ['openrouter', 'openai_compatible', 'ollama'])
def test_request_wire_format_and_report(config, key, kind):
    config['provider']['kind'] = kind
    fake = FakeTransport(completion(usage=dict(prompt_tokens=13, completion_tokens=7, cost=0.0123)))
    client = Client(config, fake)
    before = deepcopy(MESSAGES)
    assert client.complete_json(MESSAGES) == {'ok':True}
    request, timeout = fake.requests[0]
    body = json.loads(request.data)
    assert request.full_url == 'https://api.example.test/v1/chat/completions'
    assert request.get_method() == 'POST'
    assert request.get_header('Authorization') == 'Bearer ' + key
    assert request.get_header('Content-type') == 'application/json'
    assert timeout == 60
    assert body['model'] == 'test-model' and body['temperature'] == 0
    assert body['max_tokens'] == 3000 and body['stream'] is False
    assert body['response_format'] == {'type':'json_object'}
    assert body['messages'][1:] == MESSAGES == before
    assert 'JSON' in body['messages'][0]['content']
    if kind == 'openrouter':
        assert body['provider'] == {'allow_fallbacks':False, 'require_parameters':True}
    else:
        assert 'provider' not in body
    report = client.report()
    expected_cost = (len(request.data)*0.10 + 3000*0.40)/1_000_000
    assert report['estimated_cost_usd'] == pytest.approx(expected_cost)
    assert report['provider_cost_usd'] == 0.0123
    assert report['calls'] == 1 and report['failed_calls'] == 0
    assert report['input_tokens'] == 13 and report['output_tokens'] == 7
    assert report['elapsed_seconds'] >= 0
    assert report['provider'] == kind and report['model'] == 'test-model'
    assert key not in json.dumps(report) and MESSAGES[0]['content'] not in json.dumps(report)
    report['calls'] = 999
    assert client.report()['calls'] == 1


@pytest.mark.parametrize('mode', ['json_object', 'json_schema', 'none'])
def test_schema_transmission_for_each_response_format(config, key, mode):
    config['provider']['response_format'] = mode
    fake = FakeTransport()
    client = Client(config, fake)
    schema = deepcopy(SCHEMA)
    estimate = client.estimate_request(MESSAGES, schema)
    assert client.complete_json(MESSAGES, schema) == {'ok':True}
    body = json.loads(fake.requests[0][0].data)
    if mode == 'json_schema':
        assert body['response_format'] == dict(type='json_schema', json_schema=dict(name='pilon_response', strict=True, schema=SCHEMA))
    else:
        assert json.dumps(SCHEMA, separators=(',', ':')) in body['messages'][0]['content']
        if mode == 'none':
            assert 'response_format' not in body
    assert schema == SCHEMA
    assert estimate['estimated_cost_usd'] == client.report()['estimated_cost_usd']


@pytest.mark.parametrize('messages,schema,mode', [
    ([], None, 'json_object'), ('text', None, 'json_object'),
    ([{'role':'tool', 'content':'text'}], None, 'json_object'),
    ([{'role':'user', 'content':[]}], None, 'json_object'),
    ([{'role':[], 'content':'text'}], None, 'json_object'),
    ([{'role':'user', 'content':'text', 'unknown':True}], None, 'json_object'),
    ([{'role':'user', 'content':'\ud800'}], None, 'json_object'),
    (MESSAGES, None, 'json_schema'), (MESSAGES, [], 'json_schema'),
    (MESSAGES, {'type':'array'}, 'json_schema'),
    (MESSAGES, {'type':'object', 'default':float('nan')}, 'json_object'),
])
def test_bad_messages_or_schema_never_reach_transport(config, messages, schema, mode):
    config['provider']['response_format'] = mode
    fake = FakeTransport()
    client = Client(config, fake)
    with pytest.raises(ProviderError):
        client.complete_json(messages, schema)
    assert fake.requests == [] and client.report()['calls'] == 0


def test_limits_use_utf8_bytes_and_output_cap_before_any_attempt(config, key):
    messages = [dict(role='user', content='é😀'*100)]
    estimate = Client(config).estimate_request(messages)
    assert estimate['input_tokens_estimate'] > estimate['input_chars']
    assert estimate['max_output_tokens'] == 3000
    fake = FakeTransport()
    config['limits']['max_estimated_cost_usd'] = estimate['estimated_cost_usd']/2
    client = Client(config, fake)
    with pytest.raises(BudgetExceeded):
        client.complete_json(messages)
    assert fake.requests == []
    assert client.report()['calls'] == 0 and client.report()['estimated_cost_usd'] == 0


def test_character_limit_includes_schema_and_json_framing(config, key):
    config['limits']['max_input_chars'] = 100
    fake = FakeTransport()
    client = Client(config, fake)
    with pytest.raises(BudgetExceeded):
        client.complete_json([dict(role='user', content='hi')], SCHEMA)
    assert fake.requests == []


def test_cumulative_estimate_is_not_released_after_small_success_or_failure(config, key):
    per_call = Client(config).estimate_request(MESSAGES)['estimated_cost_usd']
    config['limits']['max_estimated_cost_usd'] = per_call*2.5
    fake = FakeTransport(completion(usage=dict(prompt_tokens=1, completion_tokens=1, cost=0)))
    client = Client(config, fake)
    client.complete_json(MESSAGES)
    fake.error = TimeoutError('sensitive body')
    with pytest.raises(ProviderError):
        client.complete_json(MESSAGES)
    with pytest.raises(BudgetExceeded):
        client.complete_json(MESSAGES)
    assert len(fake.requests) == 2
    assert client.report()['estimated_cost_usd'] == pytest.approx(per_call*2)
    assert client.report()['provider_cost_usd'] is None
    assert client.report()['failed_calls'] == 1


@pytest.mark.parametrize('failure', [False, True])
def test_request_limit_includes_failed_attempts(config, key, failure):
    config['limits']['max_requests'] = 1
    fake = FakeTransport(error=OSError('private body') if failure else None)
    client = Client(config, fake)
    if failure:
        with pytest.raises(ProviderError):
            client.complete_json(MESSAGES)
    else:
        client.complete_json(MESSAGES)
    with pytest.raises(BudgetExceeded):
        client.complete_json(MESSAGES)
    assert len(fake.requests) == 1
    assert client.report()['failed_calls'] == int(failure)


def test_zero_request_budget_prevents_call(config):
    config['limits']['max_requests'] = 0
    fake = FakeTransport()
    with pytest.raises(BudgetExceeded):
        Client(config, fake).complete_json(MESSAGES)
    assert fake.requests == []


def test_concurrent_calls_cannot_bypass_the_shared_request_budget(config, key):
    config['limits']['max_requests'] = 1
    fake = FakeTransport()
    client = Client(config, fake)
    ready = threading.Barrier(2)
    def attempt():
        ready.wait(timeout=5)
        try:
            return client.complete_json(MESSAGES)
        except BudgetExceeded:
            return 'blocked'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result(timeout=5) for future in [pool.submit(attempt), pool.submit(attempt)]]
    assert results.count({'ok':True}) == 1 and results.count('blocked') == 1
    assert len(fake.requests) == client.report()['calls'] == 1


@pytest.mark.parametrize('secret', [None, '', 'test\nsecret', 'test\rsecret', 'test secret', 'é'])
def test_missing_or_invalid_environment_secret_does_not_spend_budget(config, monkeypatch, secret):
    if secret is None:
        monkeypatch.delenv('PILON_TEST_KEY', raising=False)
    else:
        monkeypatch.setenv('PILON_TEST_KEY', secret)
    fake = FakeTransport()
    client = Client(config, fake)
    with pytest.raises(ConfigError):
        client.complete_json(MESSAGES)
    assert fake.requests == []
    assert client.report()['calls'] == 0 and client.report()['estimated_cost_usd'] == 0


def test_client_owns_validated_config_snapshot(config, key):
    fake = FakeTransport()
    client = Client(config, fake)
    config['provider']['base_url'] = 'http://unsafe.example'
    config['limits']['max_requests'] = 0
    client.complete_json(MESSAGES)
    assert fake.requests[0][0].full_url == 'https://api.example.test/v1/chat/completions'


@pytest.mark.parametrize('finish', ['length', 'max_tokens', 'content_filter', 'tool_calls', None, ''])
def test_truncated_or_incomplete_content_is_rejected_even_if_json_parses(config, key, finish):
    fake = FakeTransport(completion(finish=finish, usage=dict(prompt_tokens=10, completion_tokens=3000, cost=0.01)))
    client = Client(config, fake)
    with pytest.raises(ProviderError, match='truncated'):
        client.complete_json(MESSAGES)
    report = client.report()
    assert report['failed_calls'] == 1 and report['calls'] == 1
    assert report['provider_cost_usd'] == 0.01 and report['output_tokens'] == 3000


@pytest.mark.parametrize('content', [
    '{"ok":', '```json\n{"ok":true}\n```', '[]', 'null', 'true', '"text"',
    '{"ok":true} trailing', '{"ok":1,"ok":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":1e999}',
])
def test_invalid_completion_json_is_not_repaired_or_retried(config, key, content):
    fake = FakeTransport(completion(content))
    client = Client(config, fake)
    with pytest.raises(ProviderError):
        client.complete_json(MESSAGES)
    assert len(fake.requests) == 1 and client.report()['failed_calls'] == 1


@pytest.mark.parametrize('raw', [
    b'not JSON', b'\xff', b'[]', b'{"choices":[],"choices":[]}', b'{"usage":{"cost":NaN}}',
    b'{}', b'{"choices":[]}', b'{"choices":[{}]}', b'{"error":{"message":"private provider message"}}',
    b'{"choices":[{"finish_reason":"stop","message":{"content":null}}]}',
    b'{"choices":[{"finish_reason":"stop","message":{"content":"{}","refusal":"private"}}]}',
])
def test_bad_response_envelopes_are_safe_failures(config, key, raw):
    fake = FakeTransport(raw)
    client = Client(config, fake)
    with pytest.raises(ProviderError) as error:
        client.complete_json(MESSAGES)
    assert 'private' not in str(error.value)
    assert client.report()['failed_calls'] == 1 and len(fake.requests) == 1


@pytest.mark.parametrize('status', [301, 302, 307, 308, 400, 401, 429, 500, 503])
def test_http_errors_are_not_retried_and_never_echo_bodies(config, key, status):
    fake = FakeTransport(b'private prompt, secret, provider body', status=status)
    client = Client(config, fake)
    with pytest.raises(ProviderError) as error:
        client.complete_json(MESSAGES)
    assert str(status) in str(error.value)
    assert 'private' not in str(error.value) and key not in str(error.value)
    assert len(fake.requests) == 1 and client.report()['provider_cost_usd'] is None


def test_transport_exceptions_are_redacted_and_counted(config, key):
    fake = FakeTransport(error=RuntimeError(key + MESSAGES[0]['content']))
    client = Client(config, fake)
    with pytest.raises(ProviderError) as error:
        client.complete_json(MESSAGES)
    assert key not in str(error.value) and MESSAGES[0]['content'] not in str(error.value)
    assert error.value.__suppress_context__
    assert client.report()['failed_calls'] == 1 and client.report()['estimated_cost_usd'] > 0


@pytest.mark.parametrize('cost', [None, -1, True, '0.25'])
def test_unknown_or_invalid_billing_remains_null(config, key, cost):
    fake = FakeTransport(completion(usage=dict(prompt_tokens=1, completion_tokens=2, cost=cost)))
    client = Client(config, fake)
    client.complete_json(MESSAGES)
    report = client.report()
    assert report['provider_cost_usd'] is None and report['known_provider_cost_usd'] is None
    assert report['estimated_cost_usd'] > 0


def test_partial_billing_and_token_reporting_are_marked(config, key):
    fake = FakeTransport(completion(usage=dict(prompt_tokens=3, completion_tokens=4, cost=0)))
    client = Client(config, fake)
    client.complete_json(MESSAGES)
    assert client.report()['provider_cost_usd'] == 0
    fake.body = completion()
    client.complete_json(MESSAGES)
    report = client.report()
    assert report['provider_cost_usd'] is None and report['known_provider_cost_usd'] == 0
    assert report['provider_cost_reported_calls'] == report['usage_reported_calls'] == 1
    assert report['calls'] == 2 and report['input_tokens'] == 3 and report['output_tokens'] == 4


@pytest.mark.parametrize('status', [301, 302, 303, 307, 308])
def test_default_urllib_transport_never_forwards_auth_to_redirect(config, key, monkeypatch, status):
    received = []
    class FakeHTTPS(HTTPSHandler):
        def https_open(self, request):
            received.append(request)
            headers = Message()
            headers['Location'] = 'https://other.example.test/steal'
            response = addinfourl(BytesIO(b'private redirect body'), headers, request.full_url, status)
            response.msg = 'Redirect'
            return response

    def opener(*handlers):
        assert any(isinstance(h, ProxyHandler) and h.proxies == {} for h in handlers)
        return build_opener(*handlers, FakeHTTPS())
    monkeypatch.setattr(providers, 'build_opener', opener)
    client = Client(config)
    with pytest.raises(ProviderError, match=str(status)):
        client.complete_json(MESSAGES)
    assert len(received) == 1
    assert received[0].full_url == 'https://api.example.test/v1/chat/completions'
    assert received[0].get_header('Authorization') == 'Bearer ' + key


def test_response_size_is_bounded_even_with_injected_transport(config, key, monkeypatch):
    monkeypatch.setattr(providers, '_MAX_RESPONSE_BYTES', 20)
    client = Client(config, FakeTransport(b'x'*21))
    with pytest.raises(ProviderError, match='size limit'):
        client.complete_json(MESSAGES)


@pytest.mark.parametrize('oversized', [False, True])
def test_default_transport_reads_only_bounded_bytes_and_closes_response(config, key, monkeypatch, oversized):
    read_sizes, responses = [], []
    cap = len(completion())
    monkeypatch.setattr(providers, '_MAX_RESPONSE_BYTES', cap)
    class TrackedBody(BytesIO):
        def read(self, size=-1):
            read_sizes.append(size)
            return super().read(size)
    class FakeHTTPS(HTTPSHandler):
        def https_open(self, request):
            stream = TrackedBody(b'x'*(cap+100) if oversized else completion())
            response = addinfourl(stream, Message(), request.full_url, 200)
            response.msg = 'OK'
            responses.append(response)
            return response
    monkeypatch.setattr(providers, 'build_opener', lambda *handlers: build_opener(*handlers, FakeHTTPS()))
    client = Client(config)
    if oversized:
        with pytest.raises(ProviderError, match='size limit'):
            client.complete_json(MESSAGES)
    else:
        assert client.complete_json(MESSAGES) == {'ok':True}
    assert read_sizes == [cap+1]
    assert responses[0].closed


def test_all_shipped_examples_validate_without_secrets_or_network(monkeypatch):
    root = Path(__file__).resolve().parents[1]/'configs'
    for name in ('openrouter.json', 'local-ollama.json', 'openai-compatible.json'):
        config = load_config(root/name)
        client = Client(config)
        assert client.report()['calls'] == 0 and client.report()['provider_cost_usd'] is None
        assert 'api_key' not in config['provider']
