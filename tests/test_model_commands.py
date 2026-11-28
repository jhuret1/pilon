import json
from pathlib import Path
import socket

import pytest

from pilon.cli import main
from pilon import model_commands


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Live network is forbidden in command tests')
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)


def arguments(tmp_path):
    return ['benchmark', 'run', '--model', str(ROOT/'src/pilon/facets/example/benchmark-model.json'),
            '--signals', str(ROOT/'src/pilon/facets/example/benchmark-requests.jsonl'),
            '--config', str(ROOT/'configs/local-ollama.json'), '--db', str(tmp_path/'jobs.sqlite'),
            '--output-dir', str(tmp_path/'review')]


def test_public_cli_dry_run_validates_bundled_synthetic_inputs_without_writes(tmp_path, capsys):
    assert main(arguments(tmp_path)) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['dry_run'] and result['records'] == 4
    assert result['schema_attributes'] == 3 and result['observed_values'] == 6
    assert result['estimates']['requests'] == 4
    assert not list(tmp_path.iterdir())


def test_execute_flag_and_repeated_jsonl_feeds_are_forwarded(tmp_path, monkeypatch, capsys):
    args = arguments(tmp_path)
    extra = tmp_path/'extra.jsonl'
    extra.write_text(json.dumps(dict(id='extra', role='demand', source='test', category='running-shoes', text='trail shoes')))
    captured = {}
    def fake(model, records, config, **kwargs):
        captured.update(model=model, records=records, config=config, **kwargs)
        return {'status': 'completed'}
    monkeypatch.setattr(model_commands, 'run_benchmark', fake)
    assert main(args + ['--signals', str(extra), '--execute']) == 0
    assert captured['execute'] is True and len(captured['records']) == 5
    assert captured['model']['synthetic'] is True
    assert json.loads(capsys.readouterr().out)['status'] == 'completed'


def test_provider_runtime_errors_do_not_escape_or_echo_secrets(tmp_path, monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise RuntimeError('SECRET PROVIDER BODY')
    monkeypatch.setattr(model_commands, 'run_benchmark', fail)
    with pytest.raises(SystemExit) as exc:
        main(arguments(tmp_path) + ['--execute'])
    assert exc.value.code == 2
    output = capsys.readouterr()
    assert 'SECRET' not in output.err and 'Provider operation failed' in output.err


def test_input_output_collision_is_rejected_before_provider(tmp_path, capsys):
    args = arguments(tmp_path)
    args[args.index('--db') + 1] = args[args.index('--model') + 1]
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2 and 'distinct paths' in capsys.readouterr().err


def test_bad_config_rejected_in_dry_run(tmp_path, capsys):
    args = arguments(tmp_path)
    path = tmp_path/'bad.json'
    path.write_text('{"version":2}')
    args[args.index('--config') + 1] = str(path)
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2
    assert not (tmp_path/'review').exists() and not (tmp_path/'jobs.sqlite').exists()
    assert capsys.readouterr().err


def test_csv_and_default_database_work_without_writes(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / 'requests.csv'
    path.write_text('id,role,source,category,count,text\nq1,demand,test,running-shoes,3,wide trail shoes\n', encoding='utf-8')
    args = arguments(tmp_path)
    db_at = args.index('--db')
    del args[db_at:db_at + 2]
    args[args.index('--signals') + 1] = str(path)
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['records'] == 1 and result['dry_run'] is True
    assert result['db'] == str((tmp_path / 'runtime/background.sqlite').resolve())
    assert not (tmp_path / 'runtime').exists()
    assert not (tmp_path / 'review').exists()
