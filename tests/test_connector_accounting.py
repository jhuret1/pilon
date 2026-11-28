from pilon.loop.benchmark_ui import build_view
from pilon.loop.demo import inputs
from pilon.loop.store import Queue
from pilon.loop.worker import run_once


def test_provider_usage_survives_replay_without_claiming_free_inference(tmp_path):
    model, records = inputs()
    queue = Queue(tmp_path / 'accounting.sqlite')
    baseline = queue.enqueue(model, records, options={'through': 'benchmark'})
    run_once(queue, job_id=baseline)
    usage = dict(provider='openrouter', model='test/model', calls=3, failed_calls=1,
                 input_tokens=500, output_tokens=100, provider_cost_usd=None,
                 estimated_cost_usd=.001, elapsed_seconds=3.2, authorization='never-display')
    jid = queue.enqueue(model, records, options={'through': 'benchmark', 'inference': usage})
    result = run_once(queue, job_id=jid)
    assert 'benchmark' in result['metrics']['reused_stages']
    assert result['metrics']['llm_calls'] == 3
    assert result['metrics']['api_cost_usd'] is None
    assert result['metrics']['estimated_cost_usd'] == .001
    assert 'authorization' not in result['metrics']['inference']
    assert result['benchmark']['analysis']['execution'] == 'model_connector'
    view = build_view(result, records=records)
    assert view['inference']['failed_calls'] == 1
    assert view['inference']['provider_cost_usd'] is None
    assert queue.get(baseline)['result']['metrics']['llm_calls'] == 0


def test_provider_reported_cost_is_distinct_from_estimate(tmp_path):
    model, records = inputs()
    queue = Queue(tmp_path / 'actual.sqlite')
    jid = queue.enqueue(model, records, options={'through': 'benchmark', 'inference': dict(
        provider='openrouter', calls=1, provider_cost_usd=.02, estimated_cost_usd=.03)})
    result = run_once(queue, job_id=jid)
    assert result['metrics']['api_cost_usd'] == .02
    assert result['metrics']['estimated_cost_usd'] == .03
