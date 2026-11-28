"""Bounded, non-streaming chat JSON clients using only the standard library.

Loading a config and constructing a client never use the network. The optional
transport is a trusted callable ``(urllib.request.Request, timeout_seconds)``
returning ``(http_status, response_bytes)``; it must not retry or redirect.
"""
from copy import deepcopy
from decimal import Decimal
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class ConfigError(ValueError):
    """Invalid configuration, with no configuration values in the error."""


class ProviderError(RuntimeError):
    """Safe error that never includes a provider response body or credentials."""


class BudgetExceeded(ProviderError):
    """A local limit prevented a request; no transport call was made."""


_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_JSON_INSTRUCTION = 'Return only a valid JSON object, without Markdown fences or commentary.'
_PROVIDER_DEFAULTS = dict(response_format='json_object', temperature=0,
                          max_output_tokens=3000, timeout_seconds=60)
_LIMIT_FIELDS = {'max_requests', 'max_input_chars', 'max_estimated_cost_usd',
                 'input_price_per_million', 'output_price_per_million'}


def _object(value, required, optional=()):
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - set(optional):
        raise ConfigError('Configuration has missing or unsupported fields; use environment references for secrets.')


def _number(value, *, minimum=0, integer=False):
    if type(value) not in (int, float) or (integer and type(value) is not int):
        return False
    try:
        return math.isfinite(value) and value >= minimum
    except OverflowError:
        return False


def _base_url(value):
    if (not isinstance(value, str) or not value or not value.isascii()
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value)
            or any(c in value for c in '\\?#')):
        raise ConfigError('base_url must be a clean HTTP(S) API root without credentials, query or fragment.')
    try:
        parts = urlsplit(value)
        host, port = parts.hostname, parts.port
    except ValueError:
        raise ConfigError('Invalid provider base_url.') from None
    if (parts.scheme not in {'http', 'https'} or not host or parts.username is not None
            or parts.password is not None or (port is not None and not 1 <= port <= 65535)):
        raise ConfigError('Invalid provider base_url; embedded credentials are forbidden.')
    try:
        local = ipaddress.ip_address(host).is_loopback
    except ValueError:
        if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', host):
            raise ConfigError('Invalid provider hostname.') from None
        local = host.lower() == 'localhost'
    if parts.scheme == 'http' and not local:
        raise ConfigError('Remote providers require HTTPS; HTTP is allowed only on loopback.')
    if not re.fullmatch(r'[/A-Za-z0-9._~-]*', parts.path) or any(p in {'.', '..'} for p in parts.path.split('/')):
        raise ConfigError('Invalid provider API root path.')
    if parts.path.rstrip('/').endswith('/chat/completions'):
        raise ConfigError('base_url must be the API root, without /chat/completions.')
    return value.rstrip('/'), local


def _validate_config(config):
    _object(config, {'version', 'provider', 'limits', 'benchmark'})
    if type(config['version']) is not int or config['version'] != 1:
        raise ConfigError('Only configuration version 1 is supported.')
    provider = config['provider']
    _object(provider, {'kind', 'base_url', 'model'}, {'api_key_env', *_PROVIDER_DEFAULTS})
    if not isinstance(provider['kind'], str) or provider['kind'] not in {'openrouter', 'openai_compatible', 'ollama'}:
        raise ConfigError('Unsupported provider kind.')
    model = provider['model']
    if not isinstance(model, str) or not model.strip() or any(c.isspace() or ord(c) < 32 for c in model):
        raise ConfigError('A nonempty model identifier without whitespace is required.')
    base_url, local = _base_url(provider['base_url'])
    env = provider.get('api_key_env')
    if ('api_key_env' in provider and (not isinstance(env, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', env))) or (not local and env is None):
        raise ConfigError('Use api_key_env naming an environment variable; it is required for remote providers.')
    provider = dict(_PROVIDER_DEFAULTS, **provider)
    provider['base_url'] = base_url
    if not isinstance(provider['response_format'], str) or provider['response_format'] not in {'json_object', 'json_schema', 'none'}:
        raise ConfigError('Unsupported response_format.')
    if not _number(provider['temperature']) or provider['temperature'] > 2:
        raise ConfigError('temperature must be a finite number between 0 and 2.')
    if not _number(provider['max_output_tokens'], minimum=1, integer=True):
        raise ConfigError('max_output_tokens must be a positive integer.')
    if not _number(provider['timeout_seconds']) or provider['timeout_seconds'] == 0:
        raise ConfigError('timeout_seconds must be positive and finite.')
    limits, benchmark = config['limits'], config['benchmark']
    _object(limits, _LIMIT_FIELDS)
    _object(benchmark, {'max_records', 'max_model_chars'})
    if not _number(limits['max_requests'], integer=True):
        raise ConfigError('max_requests must be a nonnegative integer.')
    if not _number(limits['max_input_chars'], minimum=1, integer=True):
        raise ConfigError('max_input_chars must be a positive integer.')
    for field in ('max_estimated_cost_usd', 'input_price_per_million', 'output_price_per_million'):
        if not _number(limits[field]):
            raise ConfigError('Costs and prices must be finite nonnegative numbers.')
    if not local and any(limits[k] == 0 for k in ('input_price_per_million', 'output_price_per_million')):
        raise ConfigError('Remote providers require positive estimated input and output prices.')
    if any(not _number(benchmark[k], minimum=1, integer=True) for k in benchmark):
        raise ConfigError('Benchmark limits must be positive integers.')
    return dict(version=1, provider=provider, limits=deepcopy(limits), benchmark=deepcopy(benchmark))


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON member.')
        result[key] = value
    return result


def _finite_float(text):
    value = float(text)
    if not math.isfinite(value):
        raise ValueError('Nonfinite JSON number.')
    return value


def _reject_constant(_):
    raise ValueError('Nonstandard JSON constant.')


def _json_loads(text):
    return json.loads(text, object_pairs_hook=_pairs, parse_float=_finite_float, parse_constant=_reject_constant)


def load_config(path):
    """Return a validated, detached dict. Do not read secrets or make requests."""
    try:
        config = _json_loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError, TypeError, RecursionError):
        raise ConfigError('Cannot read a valid provider configuration JSON file.') from None
    return _validate_config(config)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _transport(request, timeout):
    # Do not inherit environment proxies: loopback traffic must remain local.
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, response.read(_MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        status = exc.code
        exc.close()
        return status, b''


class Client:
    """One client owns one cumulative, thread-safe request/estimate budget.

    ``messages`` is a nonempty list of text-only role/content objects. A schema
    is sent as strict JSON Schema in json_schema mode, or as an instruction in
    other modes. Callers remain responsible for validating their domain schema.
    """

    def __init__(self, config, transport=None):
        self._config = _validate_config(config)
        if transport is not None and not callable(transport):
            raise ConfigError('transport must be callable.')
        self._transport = transport if transport is not None else _transport
        self._lock = threading.RLock()
        self._calls = self._failed = self._input_tokens = self._output_tokens = 0
        self._token_calls = self._cost_calls = 0
        self._provider_cost = self._estimate = Decimal(0)
        self._elapsed = 0.0

    def _body(self, messages, schema):
        if not isinstance(messages, list) or not messages:
            raise ProviderError('messages must be a nonempty list of text role/content objects.')
        for message in messages:
            if (not isinstance(message, dict) or set(message) != {'role', 'content'}
                    or not isinstance(message['role'], str)
                    or message['role'] not in {'system', 'developer', 'user', 'assistant'}
                    or not isinstance(message['content'], str)):
                raise ProviderError('messages must contain only supported roles and text content.')
        provider = self._config['provider']
        mode = provider['response_format']
        if schema is not None and (not isinstance(schema, dict) or schema.get('type') != 'object'):
            raise ProviderError('schema must be a JSON Schema object with type object.')
        if mode == 'json_schema' and schema is None:
            raise ProviderError('json_schema response_format requires a schema.')
        instruction = _JSON_INSTRUCTION
        body = dict(model=provider['model'], temperature=provider['temperature'],
                    max_tokens=provider['max_output_tokens'], stream=False)
        try:
            if schema is not None:
                schema_text = json.dumps(schema, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
                if mode != 'json_schema':
                    instruction += '\nFollow this JSON Schema: ' + schema_text
            body['messages'] = [dict(role='system', content=instruction), *deepcopy(messages)]
            if mode == 'json_schema':
                body['response_format'] = dict(type=mode, json_schema=dict(name='pilon_response', strict=True, schema=schema))
            elif mode == 'json_object':
                body['response_format'] = dict(type=mode)
            if provider['kind'] == 'openrouter':
                body['provider'] = dict(allow_fallbacks=False, require_parameters=True)
            text = json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
            data = text.encode('utf-8')
        except (TypeError, ValueError, RecursionError):
            raise ProviderError('Request messages and schema must be valid UTF-8 JSON.') from None
        if len(text) > self._config['limits']['max_input_chars']:
            raise BudgetExceeded('Request exceeds max_input_chars, including JSON instructions and schema.')
        return data

    def _estimated_cost(self, data):
        limits, provider = self._config['limits'], self._config['provider']
        return (Decimal(len(data)) * Decimal(str(limits['input_price_per_million']))
                + Decimal(provider['max_output_tokens']) * Decimal(str(limits['output_price_per_million']))) / Decimal(1_000_000)

    def estimate_request(self, messages, schema=None):
        """Size one request without reading credentials, spending budget or I/O."""
        data = self._body(messages, schema)
        return dict(input_chars=len(data.decode('utf-8')), input_tokens_estimate=len(data),
                    max_output_tokens=self._config['provider']['max_output_tokens'],
                    estimated_cost_usd=float(self._estimated_cost(data)))

    def complete_json(self, messages, schema=None):
        """Make at most one HTTP attempt and return a strict parsed JSON object."""
        with self._lock:
            data = self._body(messages, schema)
            limits, provider = self._config['limits'], self._config['provider']
            # Full serialized UTF-8 bytes conservatively proxy input tokens. Keep
            # every reservation, even after timeout, missing usage or bad output.
            estimate = self._estimated_cost(data)
            if self._calls >= limits['max_requests']:
                raise BudgetExceeded('Request limit reached.')
            if self._estimate + estimate > Decimal(str(limits['max_estimated_cost_usd'])):
                raise BudgetExceeded('Estimated cost limit would be exceeded; this is not a provider billing cap.')
            headers = {'Content-Type':'application/json', 'Accept':'application/json'}
            env = provider.get('api_key_env')
            if env is not None:
                secret = os.environ.get(env)
                if not secret or not secret.isascii() or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in secret):
                    raise ConfigError('The configured API key environment variable is missing or invalid.')
                headers['Authorization'] = 'Bearer ' + secret
            request = Request(provider['base_url'] + '/chat/completions', data=data, headers=headers, method='POST')
            self._calls += 1
            self._estimate += estimate
            started = time.perf_counter()
            try:
                try:
                    status, raw = self._transport(request, provider['timeout_seconds'])
                except Exception:
                    raise ProviderError('Provider transport failed; no retry was attempted.') from None
                if type(status) is not int or not 100 <= status <= 599:
                    raise ProviderError('Provider transport returned an invalid HTTP status.')
                if not 200 <= status < 300:
                    raise ProviderError(f'Provider HTTP status {status}; no retry or redirect was attempted.')
                if not isinstance(raw, bytes) or len(raw) > _MAX_RESPONSE_BYTES:
                    raise ProviderError('Provider response has an invalid type or exceeds the size limit.')
                try:
                    response = _json_loads(raw.decode('utf-8'))
                except (ValueError, RecursionError):
                    raise ProviderError('Provider returned malformed JSON.') from None
                if not isinstance(response, dict):
                    raise ProviderError('Provider returned an invalid chat response.')
                self._usage(response.get('usage'))
                if 'error' in response:
                    raise ProviderError('Provider reported an error; response details are withheld.')
                choices = response.get('choices')
                if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
                    raise ProviderError('Provider response must contain exactly one completion.')
                choice = choices[0]
                if choice.get('finish_reason') != 'stop':
                    raise ProviderError('Provider completion is truncated, refused or incomplete.')
                message = choice.get('message')
                if (not isinstance(message, dict) or message.get('refusal') or message.get('tool_calls')
                        or not isinstance(message.get('content'), str)):
                    raise ProviderError('Provider did not return JSON text content.')
                try:
                    result = _json_loads(message['content'])
                except (ValueError, RecursionError):
                    raise ProviderError('Completion content is not valid JSON.') from None
                if not isinstance(result, dict):
                    raise ProviderError('Completion content must be a JSON object.')
                return result
            except BaseException:
                self._failed += 1
                raise
            finally:
                self._elapsed += time.perf_counter() - started

    def _usage(self, usage):
        if not isinstance(usage, dict):
            return
        input_tokens, output_tokens = usage.get('prompt_tokens'), usage.get('completion_tokens')
        if (_number(input_tokens, integer=True) and _number(output_tokens, integer=True)):
            self._input_tokens += input_tokens
            self._output_tokens += output_tokens
            self._token_calls += 1
        cost = usage.get('cost')
        if _number(cost):
            self._provider_cost += Decimal(str(cost))
            self._cost_calls += 1

    def report(self):
        """Return aggregate scalars only, never messages, bodies, URLs or keys.

        Token totals cover reported usage only. Billing is null unless every
        attempt reported cost; partial known cost is exposed separately.
        """
        with self._lock:
            provider = self._config['provider']
            return dict(provider=provider['kind'], model=provider['model'], calls=self._calls,
                        failed_calls=self._failed, input_tokens=self._input_tokens,
                        output_tokens=self._output_tokens,
                        provider_cost_usd=float(self._provider_cost) if self._cost_calls == self._calls and self._calls else None,
                        estimated_cost_usd=float(self._estimate), elapsed_seconds=self._elapsed,
                        usage_reported_calls=self._token_calls, provider_cost_reported_calls=self._cost_calls,
                        known_provider_cost_usd=float(self._provider_cost) if self._cost_calls else None,
                        cost_basis='Conservative UTF-8 request bytes plus output caps at configured prices; not a billing cap.')
