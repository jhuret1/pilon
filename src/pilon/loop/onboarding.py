"""Read-only onboarding. Configuration and downloads stay in the browser."""

from collections.abc import Mapping
from html import escape
import json
from pathlib import Path
from urllib.parse import quote


_MODEL = 'src/pilon/facets/example/benchmark-model.json'
_SIGNALS = 'src/pilon/facets/example/benchmark-requests.jsonl'
_RUN = (f'pilon benchmark run --model {_MODEL} --signals {_SIGNALS} '
        '--config pilon.config.json --output-dir runtime/my-benchmark --db runtime/background.sqlite')
_PROVIDERS = {
    'openrouter': dict(base_url='https://openrouter.ai/api/v1', api_key_env='OPENROUTER_API_KEY'),
    'openai_compatible': dict(base_url='https://api.openai.com/v1', api_key_env='OPENAI_API_KEY'),
    'ollama': dict(base_url='http://localhost:11434/v1', api_key_env=''),
}
_NUMBERS = {
    'max_requests': (25, 'Maximum requests', 1, 1),
    'max_input_chars': (120000, 'Maximum input characters', 1, 1),
    'max_estimated_cost_usd': (1, 'Estimated budget (USD)', 0.01, 0.01),
    'input_price_per_million': (0.1, 'Input price / million tokens (USD)', 0, 'any'),
    'output_price_per_million': (0.4, 'Output price / million tokens (USD)', 0, 'any'),
    'max_records': (20, 'Maximum demand records', 1, 1),
    'max_model_chars': (60000, 'Maximum model characters', 1, 1),
    'max_output_tokens': (3000, 'Maximum output tokens / request', 1, 1),
    'timeout_seconds': (60, 'Request timeout (seconds)', 1, 1),
}


def _e(value):
    return escape(str(value), quote=True)


def _command(identifier, title, command, description):
    return (f'<article class="command"><div class="command-head"><h3>{_e(title)}</h3>'
            f'<button type="button" data-copy="{_e(identifier)}" hidden aria-label="Copy {_e(title)} command">Copy</button>'
            f'</div><p>{_e(description)}</p><pre id="{_e(identifier)}"><code>{_e(command)}</code></pre></article>')


def _recent(jobs):
    cards = []
    for job in jobs if isinstance(jobs, (list, tuple)) else ():
        if not isinstance(job, Mapping):
            continue
        jid = job.get('id')
        if not isinstance(jid, str) or not jid.strip() or jid in {'.', '..'}:
            continue
        name = job.get('label') or job.get('category') or 'Benchmark run'
        cards.append('<a class="recent-job" href="/jobs/' + _e(quote(jid, safe='')) + '"><span><strong>'
                     + _e(name) + '</strong><small>' + _e(jid) + '</small></span><span>'
                     + _e(job.get('status', 'Status unavailable')) + ' <span aria-hidden="true">↗</span></span></a>')
        if len(cards) == 5:
            break
    if not cards:
        return '<p class="empty">No local runs yet. Start with the demo or prepare your first benchmark below.</p>'
    return '<h2 class="recent-heading">Recent local runs</h2><div class="recent-list">' + ''.join(cards) + '</div>'


_CONFIG_JS = 'const PROVIDERS = ' + json.dumps(_PROVIDERS) + ';\nconst DEFAULTS = ' + json.dumps(
    {name: value[0] for name, value in _NUMBERS.items()}) + r""";
function buildConfig(input) {
  const kind = input.kind;
  if (!Object.prototype.hasOwnProperty.call(PROVIDERS, kind)) throw new Error('Choose a model provider.');
  let url;
  const base = String(input.base_url || '').trim();
  try { url = new URL(base); }
  catch (_) { throw new Error('Enter a complete HTTP or HTTPS base URL.'); }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash
      || /[^\x21-\x7e]|[\\?#]/.test(base) || !/^[/A-Za-z0-9._~-]*$/.test(url.pathname)
      || url.pathname.replace(/\/$/, '').endsWith('/chat/completions')) {
    throw new Error('Use an HTTP or HTTPS base URL without credentials, query parameters or fragments.');
  }
  const local = url.hostname === 'localhost' || url.hostname === '[::1]' || /^127\./.test(url.hostname);
  if (url.protocol === 'http:' && !local) throw new Error('Use HTTPS for remote endpoints. HTTP is supported on loopback only.');
  const model = String(input.model || '').trim();
  if (!model || /\s|[\x00-\x1f]/.test(model)) throw new Error('Enter an available model ID without whitespace.');
  const env = String(input.api_key_env || '').trim();
  if ((!local && !env) || (env && !/^[A-Za-z_][A-Za-z0-9_]*$/.test(env))) {
    throw new Error('Enter an environment variable name, such as OPENROUTER_API_KEY. Never enter the key itself.');
  }
  const numbers = {};
  for (const [key, fallback] of Object.entries(DEFAULTS)) {
    const raw = input[key] === undefined ? fallback : input[key];
    const value = Number(raw);
    const price = key === 'input_price_per_million' || key === 'output_price_per_million';
    const decimal = price || key === 'max_estimated_cost_usd';
    if (String(raw).trim() === '' || !Number.isFinite(value) || (price ? value < 0 : value <= 0)
        || (!decimal && !Number.isSafeInteger(value))) {
      throw new Error('Use positive whole numbers for limits and nonnegative prices; the budget must be positive.');
    }
    numbers[key] = value;
  }
  if (!local && (!numbers.input_price_per_million || !numbers.output_price_per_million)) {
    throw new Error('Set positive estimated input and output prices for a remote endpoint.');
  }
  const provider = {kind, base_url: url.href.replace(/\/$/, ''), model,
    response_format: 'json_object', temperature: 0,
    max_output_tokens: numbers.max_output_tokens, timeout_seconds: numbers.timeout_seconds};
  if (env) provider.api_key_env = env;
  return {version: 1, provider, limits: {
    max_requests: numbers.max_requests, max_input_chars: numbers.max_input_chars,
    max_estimated_cost_usd: numbers.max_estimated_cost_usd,
    input_price_per_million: numbers.input_price_per_million,
    output_price_per_million: numbers.output_price_per_million
  }, benchmark: {max_records: numbers.max_records, max_model_chars: numbers.max_model_chars}};
}
"""

_UI_JS = r"""
(() => {
  'use strict';
  const byId = id => document.getElementById(id);
  const status = byId('config-status');
  const preview = byId('config-preview');
  const download = byId('download-config');
  const configCopy = byId('copy-config');
  const radios = Array.from(document.querySelectorAll('input[name="provider"]'));
  let configText = '';
  const selected = () => radios.find(radio => radio.checked).value;
  function update() {
    const offline = selected() === 'offline';
    byId('provider-fields').hidden = offline;
    byId('provider-fields').disabled = offline;
    byId('offline-note').hidden = !offline;
    byId('offline-commands').hidden = !offline;
    byId('model-commands').hidden = offline;
    byId('config-actions').hidden = offline;
    byId('config-detail').hidden = offline;
    configText = '';
    if (!offline) {
      try {
        const input = {kind: selected()};
        for (const id of ['base_url', 'model', 'api_key_env', ...Object.keys(DEFAULTS)]) input[id] = byId(id).value;
        configText = JSON.stringify(buildConfig(input), null, 2) + '\n';
        status.textContent = 'Config ready to download. Endpoint not tested.';
        preview.textContent = configText;
      } catch (error) {
        status.textContent = error.message;
        preview.textContent = 'Complete the settings above to preview your configuration.';
      }
    } else { status.textContent = 'Offline demo selected. No configuration file or API key needed.'; }
    download.disabled = !configText;
    configCopy.disabled = !configText;
  }
  function choose() {
    if (selected() !== 'offline') {
      const defaults = PROVIDERS[selected()];
      byId('base_url').value = defaults.base_url;
      byId('api_key_env').value = defaults.api_key_env;
      byId('model').value = '';
    }
    update();
  }
  radios.forEach(radio => radio.addEventListener('change', choose));
  byId('provider-fields').addEventListener('input', update);
  download.addEventListener('click', () => {
    update();
    if (!configText) return;
    const url = URL.createObjectURL(new Blob([configText], {type: 'application/json'}));
    const link = document.createElement('a');
    link.href = url; link.download = 'pilon.config.json';
    document.body.appendChild(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    status.textContent = 'Configuration download requested. Save pilon.config.json in your working directory.';
  });
  async function copy(text, element) {
    try {
      await navigator.clipboard.writeText(text);
      byId('copy-status').textContent = 'Copied. Run commands yourself in a terminal.';
    } catch (_) {
      const range = document.createRange(); range.selectNodeContents(element);
      const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
      byId('copy-status').textContent = 'Text selected. Use your usual copy shortcut.';
    }
  }
  document.querySelectorAll('[data-copy]').forEach(button => {
    button.hidden = false;
    button.addEventListener('click', () => {
      const code = byId(button.dataset.copy);
      copy(code.textContent, code);
    });
  });
  configCopy.addEventListener('click', () => { update(); if (configText) copy(configText, preview); });
  if (document.body.dataset.focus === 'connectors') byId('provider-openrouter').checked = true;
  choose();
  if (document.body.dataset.focus === 'connectors') {
    byId('connectors-title').focus({preventScroll: true});
    byId('connectors').scrollIntoView();
  }
})();
"""

_CSS = (Path(__file__).parent / 'ui' / 'onboarding.css').read_text(encoding='utf-8')


def render_onboarding(jobs=(), *, focus=None):
    """Render supplied job metadata only; no database, environment or provider I/O."""
    focus = 'connectors' if focus == 'connectors' else ''
    numbers = ''.join(
        f'<label class="field" for="{name}">{label}<input id="{name}" type="number" '
        f'value="{value}" min="{minimum}" step="{step}" required></label>'
        for name, (value, label, minimum, step) in _NUMBERS.items())
    modes = ''.join(
        f'<label class="mode" for="provider-{kind}"><input type="radio" name="provider" '
        f'id="provider-{kind}" value="{kind}"' + (' checked' if kind == 'offline' else '')
        + f'><span><strong>{title}</strong><small>{detail}</small></span></label>'
        for kind, title, detail in (
            ('offline', 'Offline demo', 'Bundled synthetic example · no API key'),
            ('openrouter', 'OpenRouter', 'Your hosted model and account'),
            ('openai_compatible', 'OpenAI-compatible endpoint', 'A hosted or self-managed server'),
            ('ollama', 'Ollama · local', 'A model already installed on your machine')))
    body = '''<a class="skip" href="#main">Skip to setup</a>
<header class="topbar"><a class="brand" href="/start"><span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></span>PILON</a>
<nav aria-label="Main navigation"><a href="/start" aria-current="page">Get started</a><a href="/connectors#connectors">Connectors</a><a href="/">Workspace ↗</a></nav><small>LOCAL / ALPHA</small></header>
<main id="main"><section class="hero" aria-labelledby="hero-title"><div class="hero-copy"><p class="eyebrow">Customer demand → product knowledge</p>
<h1 id="hero-title">Your catalog<br>has <em>blind spots.</em></h1>
<p class="lead">Turn what customers ask for into missing attributes, missing values and evidence-backed catalog changes.</p>
<div class="hero-actions"><a class="cta" href="#quickstart">Try the demo <span aria-hidden="true">↗</span></a><a class="text-link" href="#setup">Bring your catalog →</a></div>
<p class="hero-note">Open source. Runs locally. No API key for the demo.</p></div>
<aside class="example" aria-label="Worked example from Home Depot">
<div class="example-label"><span>ONE REQUEST. TWO GAPS.</span><span>HOME DEPOT EXAMPLE</span></div>
<div class="example-query"><span class="search-glyph" aria-hidden="true"></span>gnat killer</div>
<div class="example-row"><div><small>EXISTING ATTRIBUTE</small><strong>Pest Type</strong></div><span class="arrow" aria-hidden="true">→</span><div class="addition"><small>ADD A VALUE</small><strong>+ Gnats</strong></div></div>
<div class="example-row"><div><small>MISSING DISTINCTION</small><strong>Kill, repel or trap?</strong></div><span class="arrow" aria-hidden="true">→</span><div class="addition"><small>ADD AN ATTRIBUTE</small><strong>+ Control action</strong></div></div>
<details class="example-evidence"><summary>See the product evidence</summary><blockquote>“Raid 15 oz. Ready-to-Use Flying Insect Killer exterminates flies, mosquitoes, gnats and other flying insects as they fly through the mist.”</blockquote><p>Product 143379 · source characters 0–138 · supports the value “kill”.</p></details>
<p class="example-caption">Worked example · agent-reviewed · proposed, not published.</p></aside></section>
<div class="usecases" aria-label="Three ways to use PILON">
<a class="usecase" href="#model-step"><span>01 / BENCHMARK</span><h2>Find the gap. <b aria-hidden="true">↗</b></h2><p>Compare customer requests with your attributes and values. Keep what is already covered.</p><small>Discover attributes · Extend values</small></a>
<a class="usecase" href="#evidence-input"><span>02 / EXTRACT</span><h2>Find the evidence. <b aria-hidden="true">↗</b></h2><p>Check selected gaps against product sources. Keep the exact passages that support a value.</p><small>Find product evidence</small></a>
<a class="usecase" href="#output-guide"><span>03 / INDUCT</span><h2>Review the change. <b aria-hidden="true">↗</b></h2><p>Inspect new attributes, values and product assignments as a concrete before/after.</p><small>Preview the model diff</small></a></div>
<section class="quickstart" id="quickstart" aria-labelledby="quickstart-title"><div><span class="section-label">Start here / no key needed</span><h2 id="quickstart-title">See a complete loop.</h2><p>From an installed checkout, run the synthetic demo. Explore the requests, evidence and proposed model.</p></div><div>''' + _command('quick-demo-command', 'Run at the repository root', 'pilon start --demo',
    'First install with python -m pip install -e .') + '''</div></section>
<div class="setup-title" id="setup"><div><span class="section-label">Your data / your model</span><h2>Make it your own.</h2></div><p>Four steps from your catalog export to a reviewable benchmark.</p></div>
<div class="layout"><aside class="steps"><nav aria-label="Setup steps"><ol>
<li><a href="#model-step"><b>1</b>Catalog model</a></li><li><a href="#demand-step"><b>2</b>Demand feed</a></li>
<li><a href="#connectors"><b>3</b>Choose a provider</a></li><li><a href="#run-step"><b>4</b>Run &amp; review</a></li></ol></nav>
<p>This page prepares commands and a local configuration file. It does not upload inputs, test models or start jobs.</p></aside><div>
<section class="step" id="model-step" aria-labelledby="model-title"><div class="step-head"><span class="step-number">01</span><div>
<h2 id="model-title">Start with one catalog model</h2><p>Include your existing attributes <strong>and their values</strong>.</p></div></div>
<div class="file-pair"><div class="file"><strong>Attributes</strong><p>Stable keys, readable labels and category scope.</p></div><div class="file"><strong>Values</strong><p>The vocabulary already present for each attribute.</p></div></div>
<p class="small">Existing product assignments can add coverage context. An attribute’s presence alone does not establish coverage for every product.</p>
<details><summary>Use the included sample or your own export</summary><p>The command cards below use a bundled synthetic model with three attributes and values.</p>
<pre><code>''' + _e(_MODEL) + '''</code></pre><p class="small">For your catalog, replace the <code>--model</code> path with your exported JSON model. Keep its original keys, values and category references.</p></details></section>
<section class="step" id="demand-step" aria-labelledby="demand-title"><div class="step-head"><span class="step-number">02</span><div>
<h2 id="demand-title">Add the questions customers ask</h2><p>Use a JSONL or CSV export of searches, support messages or feedback.</p></div></div>
<p class="small">Keep the original text and a stable record ID. Identify demand records with <code>role: demand</code>; retain source, dates and category context.</p>
<details><summary>Start with four synthetic requests</summary><pre><code>''' + _e(_SIGNALS) + '''</code></pre>
<p class="small">Replace the <code>--signals</code> path with your own export when ready. These files stay on disk; this page has no upload step.</p></details>
<details id="evidence-input"><summary>Product evidence is a separate input</summary><p>Demand explains why a fact matters. Product descriptions, specifications and other source records establish evidence for a product value. Add those sources when moving a selected proposal into Extract.</p></details></section>
<section class="step" id="connectors" aria-labelledby="connectors-title"><div class="step-head"><span class="step-number">03</span><div>
<h2 id="connectors-title" tabindex="-1">Choose how to interpret requests</h2><p>Try the offline example, or prepare a provider for your benchmark.</p></div></div>
<fieldset><legend>Interpretation mode</legend><div class="mode-grid">''' + modes + '''</div></fieldset>
<p class="note" id="offline-note">The offline demo uses bundled synthetic inputs and deterministic rules. It demonstrates the full loop without calling a model.</p>
<fieldset id="provider-fields"><legend>Endpoint settings · configuration only</legend><div class="form-grid">
<label class="field wide" for="base_url">API base URL<input id="base_url" type="url" value="https://openrouter.ai/api/v1" autocomplete="off" spellcheck="false" required><small>Use the API base URL, including /v1 where required. No credentials or query parameters.</small></label>
<label class="field" for="model">Model ID<input id="model" type="text" placeholder="Your available model ID" autocomplete="off" spellcheck="false" required><small>Enter a model offered by your endpoint. Availability is not checked here.</small></label>
<label class="field" for="api_key_env">Environment variable name<input id="api_key_env" type="text" value="OPENROUTER_API_KEY" autocomplete="off" spellcheck="false" pattern="[A-Za-z_][A-Za-z0-9_]*" aria-describedby="env-help"><small id="env-help">Variable name only. Set the actual key in your terminal environment. Never paste a secret here. Optional for local endpoints.</small></label></div>
<details><summary>Run limits &amp; cost assumptions</summary><p>Starts with 20 records, at most 25 requests and a $1 estimated budget. Prices are planning inputs, not live provider rates; adjust them for your chosen model.</p>
<div class="form-grid">''' + numbers + '''</div><p>JSON-object responses · temperature 0. Limits are enforced by the command, not by this page.</p></details></fieldset>
<div class="actions" id="config-actions"><button type="button" id="download-config" disabled>Download pilon.config.json</button><button type="button" class="secondary" id="copy-config" disabled>Copy JSON</button></div>
<p class="status" id="config-status" role="status" aria-live="polite">Choose a provider and enter a model ID to prepare a configuration.</p>
<details id="config-detail"><summary>Preview configuration JSON</summary><pre id="config-preview">Complete the settings above to preview your configuration.</pre></details>
<noscript><p class="note">JavaScript enables local configuration generation, copy buttons and downloads. Commands below remain selectable. Enable JavaScript to prepare provider settings; no network request is made.</p></noscript></section>
<section class="step" id="run-step" aria-labelledby="run-title"><div class="step-head"><span class="step-number">04</span><div>
<h2 id="run-title">Run your first benchmark.</h2><p>Copy commands into a terminal at the repository root, with PILON installed.</p></div></div>
<div id="offline-commands">''' + _command('demo-command', 'Try the no-key demo', 'pilon start --demo',
    'Runs the bundled synthetic loop, then serves the local onboarding and results.') + '''
<details><summary>Generate the demo report without serving</summary>''' + _command('offline-command', 'Generate a demo report', 'pilon loop demo',
    'No API calls. Saves runtime/background-loop.html and runtime/background-loop.json.') + '''</details></div>
<div id="model-commands">''' + _command('dry-command', '1 · Inspect the dry run', _RUN,
    'Dry run is the default: inspect the planned run without model calls. Save the downloaded config beside your terminal’s working directory.') + _command(
    'execute-command', '2 · Execute when ready', _RUN + ' --execute',
    'This terminal command makes real calls to the configured endpoint. Hosted providers may charge your account; local Ollama uses your machine.') + '''</div>''' + _command(
    'start-command', 'Open the local workspace', 'pilon start',
    'Serves http://127.0.0.1:8473/start. It does not start a benchmark unless you request the bundled demo.') + '''
<p class="small">These commands share <code>runtime/background.sqlite</code>, the default queue for <code>pilon start</code>. To use another queue, pass the same <code>--db</code> path to both the run and <code>pilon start</code>.</p>
<details><summary>Existing server command</summary>''' + _command('serve-command', 'Serve existing jobs', 'pilon loop serve',
    'Also serves the read-only workspace. Open /start for setup or the job URL printed by the run.') + '''</details>
<div class="review-path" aria-label="Review stages"><span>Benchmark · demand gaps</span><span>Extract · product evidence</span><span>Induct · proposed diff</span></div>
<p class="small">The benchmark command handles demand comparison. Product evidence and model-change previews are subsequent review stages; a benchmark run alone does not populate them.</p>
<details id="output-guide"><summary>Read your output</summary><p>Inspect the files under <code>runtime/my-benchmark</code> and the job URL printed by the command. Saved benchmarks open at <code>/jobs/JOB_ID</code>. An enrichment job has separate <code>/extract/JOB_ID</code> and <code>/induct/JOB_ID</code> views.</p>
<p>Exact quotations establish provenance, not independent semantic accuracy. Review proposals and unresolved cases before accepting any change.</p></details></section>
''' + _recent(jobs) + '''</div></div><footer class="footer">PILON prepares reviewable proposals. This workspace does not publish a model, change a storefront or execute the commands shown here.</footer></main>
<p class="copy-status" id="copy-status" role="status" aria-live="polite"></p>'''
    if focus == 'connectors':
        body = body.replace('href="/start" aria-current="page"', 'href="/start"')
        body = body.replace('href="/connectors#connectors">Connectors',
                            'href="/connectors#connectors" aria-current="page">Connectors')
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Get started · PILON</title><style>' + _CSS + '</style></head>'
            '<body data-focus="' + focus + '">' + body + '<script>' + _CONFIG_JS + _UI_JS + '</script></body></html>')
