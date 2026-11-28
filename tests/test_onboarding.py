"""Read-only routes and the browser-side onboarding/configuration contract."""

from copy import deepcopy
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from pilon.loop.app import create_app
from pilon.loop.demo import inputs
from pilon.loop.onboarding import _CONFIG_JS, _UI_JS, _PROVIDERS, render_onboarding
from pilon.loop.store import Queue


class Page(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.tags = []
        self.pre = {}
        self.current = None
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append((tag, attrs))
        if tag == 'pre':
            self.current = attrs.get('id')
            if self.current:
                self.pre[self.current] = ''

    def handle_data(self, data):
        if self.current:
            self.pre[self.current] += data

    def handle_endtag(self, tag):
        if tag == 'pre':
            self.current = None


def request(app, path, method='GET', host='127.0.0.1:8473'):
    result = {}

    def start(status, headers):
        result.update(status=status, headers=dict(headers))

    result['body'] = b''.join(app(dict(PATH_INFO=path, REQUEST_METHOD=method, HTTP_HOST=host), start))
    return result


def node(source, payload):
    executable = shutil.which('node')
    if not executable:
        pytest.skip('Node is required to exercise browser-side JavaScript')
    result = subprocess.run([executable, '-e', source], input=json.dumps(payload),
                            text=True, capture_output=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def build_config(**overrides):
    kind = overrides.pop('kind', 'openrouter')
    values = dict(kind=kind, model='example/model', **_PROVIDERS.get(kind, {}))
    values.update(overrides)
    return node("""
const fs = require('node:fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
try {
  const config = new Function('input', input.source + ';return buildConfig(input);')(input.values);
  process.stdout.write(JSON.stringify({config}));
} catch (error) { process.stdout.write(JSON.stringify({error: error.message})); }
""", dict(source=_CONFIG_JS, values=values))


def test_onboarding_is_english_accessible_and_progressive():
    markup = render_onboarding()
    page = Page(markup)
    assert markup.startswith('<!doctype html><html lang="en">')
    assert 'Discover attributes' in markup and 'Extend values' in markup and 'Find product evidence' in markup
    assert 'does not publish a model' in markup and 'role="status"' in markup
    ids = [attrs['id'] for _, attrs in page.tags if 'id' in attrs]
    assert len(ids) == len(set(ids))
    labels = {attrs['for'] for tag, attrs in page.tags if tag == 'label' and 'for' in attrs}
    controls = [attrs for tag, attrs in page.tags if tag == 'input']
    assert all(control['id'] in labels for control in controls)
    assert not any(control.get('type') in {'password', 'file'} for control in controls)
    assert all(attrs.get('type') == 'button' for tag, attrs in page.tags if tag == 'button')
    assert not any(tag in {'form', 'iframe', 'img'} for tag, _ in page.tags)
    assert ':focus-visible' in markup and '@media(max-width:580px)' in markup
    assert '<noscript>' in markup and 'Commands below remain selectable.' in markup
    assert not any(tag == 'script' and 'src' in attrs for tag, attrs in page.tags)
    for tag, attrs in page.tags:
        if tag == 'a':
            assert attrs['href'].startswith(('/', '#'))
        if attrs.get('href', '').startswith('#'):
            assert attrs['href'][1:] in ids


def test_command_cards_use_real_samples_and_distinguish_execution():
    page = Page(render_onboarding())
    dry = page.pre['dry-command']
    assert dry.startswith('pilon benchmark run --model src/pilon/facets/example/benchmark-model.json ')
    assert '--signals src/pilon/facets/example/benchmark-requests.jsonl' in dry
    assert '--config pilon.config.json --output-dir runtime/my-benchmark' in dry
    assert '--execute' not in dry
    assert page.pre['execute-command'] == dry + ' --execute'
    assert page.pre['demo-command'] == 'pilon start --demo'
    assert page.pre['offline-command'] == 'pilon loop demo'
    assert page.pre['start-command'] == 'pilon start'
    assert page.pre['serve-command'] == 'pilon loop serve'
    root = Path(__file__).resolve().parents[1]
    assert len(json.loads((root / 'src/pilon/facets/example/benchmark-model.json').read_text())['facets']) == 3
    assert len((root / 'src/pilon/facets/example/benchmark-requests.jsonl').read_text().splitlines()) == 4


def test_jobs_are_escaped_bounded_and_only_link_to_local_benchmarks(monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'private-secret-never-render')
    hostile = '<script>alert("x")</script>'
    jobs = [dict(id='job/a?x#"<>', label=hostile, status=hostile)] + [dict(id=f'job_{i}') for i in range(8)]
    before = deepcopy(jobs)
    markup = render_onboarding(jobs)
    page = Page(markup)
    links = [attrs['href'] for tag, attrs in page.tags if tag == 'a' and attrs['href'].startswith('/jobs/')]
    assert len(links) == 5 and links[0] == '/jobs/job%2Fa%3Fx%23%22%3C%3E'
    assert hostile not in markup and '&lt;script&gt;' in markup
    assert 'private-secret-never-render' not in markup
    assert jobs == before
    assert 'No local runs yet.' in render_onboarding([None, {}, dict(id='..'), dict(id='')])
    assert 'No local runs yet.' in render_onboarding(None)


@pytest.mark.parametrize('path', ['/start', '/connectors', '/'])
def test_empty_queue_routes_are_read_only_and_head_matches_get(tmp_path, path):
    queue = Queue(tmp_path / 'jobs.sqlite')
    app = create_app(queue)
    get = request(app, path)
    head = request(app, path, 'HEAD')
    assert get['status'] == head['status'] == '200 OK'
    assert b'<title>Get started' in get['body'] and head['body'] == b''
    assert head['headers']['Content-Length'] == get['headers']['Content-Length']
    assert get['headers']['Cache-Control'] == 'no-store'
    assert "default-src 'none'" in get['headers']['Content-Security-Policy']
    assert b'data-focus="connectors"' in get['body'] if path == '/connectors' else b'data-focus=""' in get['body']
    assert request(app, path, 'POST')['status'] == '405 Method Not Allowed'
    assert request(app, path, 'PUT')['status'] == '405 Method Not Allowed'
    assert request(app, path, host='example.org')['status'] == '403 Forbidden'
    assert queue.jobs() == []


def test_existing_root_and_job_routes_still_render_benchmark_without_mutation(tmp_path):
    queue = Queue(tmp_path / 'jobs.sqlite')
    model, records = inputs()
    jid = queue.enqueue(model, records, synthetic=True)
    before = queue.get(jid)
    app = create_app(queue)
    for path in ('/', '/jobs/' + jid):
        result = request(app, path)
        assert result['status'] == '200 OK' and b'<title>PILON Benchmark</title>' in result['body']
    for path in ('/start', '/connectors'):
        assert ('href="/jobs/' + jid + '"').encode() in request(app, path)['body']
    assert request(app, '/jobs/missing')['status'] == '404 Not Found'
    assert request(app, '/unknown')['status'] == '404 Not Found'
    assert queue.get(jid) == before


@pytest.mark.parametrize('kind', ['openrouter', 'openai_compatible', 'ollama'])
def test_download_configuration_matches_provider_contract(kind):
    config = build_config(kind=kind)['config']
    assert config['version'] == 1
    assert config['provider'] == dict(kind=kind, base_url=_PROVIDERS[kind]['base_url'], model='example/model',
        response_format='json_object', temperature=0, max_output_tokens=3000, timeout_seconds=60,
        **({'api_key_env': _PROVIDERS[kind]['api_key_env']} if kind != 'ollama' else {}))
    assert config['limits'] == dict(max_requests=25, max_input_chars=120000, max_estimated_cost_usd=1,
                                    input_price_per_million=0.1, output_price_per_million=0.4)
    assert config['benchmark'] == dict(max_records=20, max_model_chars=60000)
    from pilon.providers import _validate_config
    assert _validate_config(config) == config


@pytest.mark.parametrize('overrides', [
    dict(kind='offline'), dict(model=''), dict(model='model name'), dict(api_key_env='sk-not-a-variable'),
    dict(api_key_env=''), dict(base_url='javascript:alert(1)'), dict(base_url='https://user:secret@example.org/v1'),
    dict(base_url='http://remote.example/v1'), dict(base_url='https://example.org/v1?key=secret'),
    dict(base_url='https://example.org/v1/chat/completions'), dict(max_requests=1.5),
    dict(max_records=''), dict(max_model_chars=-1), dict(max_output_tokens=0), dict(timeout_seconds='Infinity'),
    dict(input_price_per_million=0), dict(output_price_per_million=-1),
])
def test_invalid_configuration_is_not_downloadable(overrides):
    result = build_config(**overrides)
    assert 'error' in result and 'config' not in result


def test_local_compatible_endpoint_can_omit_credentials_and_use_zero_costs():
    config = build_config(kind='openai_compatible', base_url='http://127.0.0.1:8000/v1/',
                         api_key_env='', input_price_per_million=0, output_price_per_million=0)['config']
    assert config['provider']['base_url'] == 'http://127.0.0.1:8000/v1'
    assert 'api_key_env' not in config['provider']
    from pilon.providers import _validate_config
    assert _validate_config(config) == config


def test_client_download_and_copy_are_local_and_do_not_execute_commands():
    page = Page(render_onboarding())
    elements = {attrs['id']: dict(attrs, tag=tag) for tag, attrs in page.tags if 'id' in attrs}
    result = node(r"""
const fs = require('node:fs');
const {Blob} = require('node:buffer');
const data = JSON.parse(fs.readFileSync(0, 'utf8'));
const elements = {};
for (const [id, attrs] of Object.entries(data.elements)) {
  elements[id] = {value: attrs.value || '', hidden: 'hidden' in attrs, disabled: 'disabled' in attrs,
    checked: 'checked' in attrs, textContent: data.commands[id] || '', listeners: {}, dataset: {},
    addEventListener(event, fn) { this.listeners[event] = fn; },
    focus() {}, scrollIntoView() {}};
}
const radios = Object.entries(data.elements).filter(([,v]) => v.name === 'provider').map(([id]) => elements[id]);
let blob, download, revoked, copied;
const NativeURL = URL;
NativeURL.createObjectURL = value => { blob = value; return 'blob:local-config'; };
NativeURL.revokeObjectURL = value => { revoked = value; };
const document = {
  body: {dataset: {}, appendChild() {}},
  getElementById: id => elements[id],
  querySelectorAll: selector => selector === 'input[name="provider"]' ? radios : [],
  createElement: () => ({click() { download = {href: this.href, filename: this.download}; }, remove() {}})
};
const navigator = {clipboard: {async writeText(text) { copied = text; }}};
new Function('document', 'navigator', 'URL', 'Blob', 'setTimeout', data.source)(document, navigator, NativeURL, Blob, fn => fn());
const initial = {disabled: elements['download-config'].disabled, providerHidden: elements['provider-fields'].hidden};
radios.forEach(r => { r.checked = r.value === 'ollama'; });
elements['provider-ollama'].listeners.change();
elements.model.value = 'local-model';
elements['provider-fields'].listeners.input();
elements['download-config'].listeners.click();
elements['copy-config'].listeners.click();
blob.text().then(text => {
  const config = JSON.parse(text);
  elements.model.value = '';
  elements['provider-fields'].listeners.input();
  process.stdout.write(JSON.stringify({initial, config, download, revoked, copied: JSON.parse(copied),
    invalidDisabled: elements['download-config'].disabled}));
});
""", dict(source=_CONFIG_JS + _UI_JS, elements=elements, commands=page.pre))
    assert result['initial'] == dict(disabled=True, providerHidden=True)
    assert result['config']['provider']['kind'] == 'ollama'
    assert result['config']['provider']['model'] == 'local-model'
    assert 'api_key_env' not in result['config']['provider']
    assert result['download'] == dict(href='blob:local-config', filename='pilon.config.json')
    assert result['revoked'] == 'blob:local-config' and result['copied'] == result['config']
    assert result['invalidDisabled']
    for forbidden in ('fetch(', 'XMLHttpRequest', 'WebSocket', 'sendBeacon', 'localStorage', 'sessionStorage'):
        assert forbidden not in _UI_JS
