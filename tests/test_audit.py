from copy import deepcopy
import pytest

from pilon.loop.audit import validate_audit
from pilon.loop.store import fingerprint, Queue
from pilon.loop.worker import run_once


def fixture():
    model = dict(category='Tools', assessment_scope='schema_only', observation_period='unknown', facets=[], categories=[])
    records = [dict(id='q1', role='demand', category='Tools', source='search', text='cordless drill')]
    audit = dict(model_hash=fingerprint(model), demand_hash=fingerprint([['q1', 'cordless drill']]),
                 reviewed_record_ids=['q1'], sample_size=1, method='agent review of lexical disagreements',
                 independent=True, findings=[dict(id='f1', record_id='q1', kind='missed_criterion',
                    status='needs_review', summary='Power mode needs review', expected='Check the power-mode attribute',
                    observed='No decoded intent', quote='cordless', start=0, end=8)])
    return model, records, audit


def test_audit_validates_spans_without_claiming_independent_accuracy():
    model, records, audit = fixture()
    before = deepcopy(audit)
    result = validate_audit(audit, model, records)
    assert audit == before and result['independent'] is False
    assert result['findings'][0]['status'] == 'needs_review'


@pytest.mark.parametrize('change', ['hash', 'quote', 'record', 'denominator', 'status'])
def test_audit_rejects_changed_sources_and_invented_denominators(change):
    model, records, audit = fixture()
    if change == 'hash': audit['model_hash'] = 'wrong'
    if change == 'quote': audit['findings'][0]['quote'] = 'electric'
    if change == 'record': audit['findings'][0]['record_id'] = 'q2'
    if change == 'denominator': audit['sample_size'] = 100
    if change == 'status': audit['findings'][0]['status'] = 'automatic_truth'
    with pytest.raises(ValueError): validate_audit(audit, model, records)


def test_audit_is_separate_from_cached_benchmark_decisions(tmp_path):
    model, records, audit = fixture()
    queue = Queue(tmp_path/'jobs.sqlite')
    baseline = queue.enqueue(model, records, options={'through':'benchmark'})
    run_once(queue, job_id=baseline)
    audited = queue.enqueue(model, records, options={'through':'benchmark', 'audit':audit})
    result = run_once(queue, job_id=audited)
    assert 'benchmark' in result['metrics']['reused_stages']
    assert result['benchmark']['audit']['sample_size'] == 1
    assert 'audit' not in queue.get(baseline)['result']['benchmark']
    assert 'audit' not in queue.checkpoint(audited,'benchmark')['data']
