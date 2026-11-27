from copy import deepcopy
import pytest
from pilon.loop.store import Queue
from pilon.loop.worker import run_once,report
from pilon.loop.demo import inputs


def test_background_cycle_keeps_missing_evidence_and_never_publishes(tmp_path):
    q=Queue(tmp_path/'queue.sqlite');m,r=inputs();before=deepcopy(m)
    jid=q.enqueue(m,r,synthetic=True)
    result=run_once(q,job_id=jid)
    assert result['status']=='completed'
    assert m==before
    assert any(c['key']=='removable_insole' for c in result['candidates'])
    extraction=next(e for e in result['extractions'] if e['candidate_key']=='removable_insole')
    assert extraction['assignments']==[]
    assert result['projection'] is not None
    assert q.get(jid)['events'][-1]['detail']['published'] is False
    assert run_once(q,job_id=jid) is None


def test_new_source_satisfies_old_demand_without_modifying_old_job(tmp_path):
    q=Queue(tmp_path/'queue.sqlite');m,r=inputs()
    oldid=q.enqueue(m,r,synthetic=True);old=run_once(q,job_id=oldid)
    m,r=inputs(with_new_source=True)
    newid=q.enqueue(m,r,synthetic=True);new=run_once(q,job_id=newid)
    assert newid!=oldid
    assert report(q,oldid)==old
    assignment=next(e for e in new['extractions'] if e['candidate_key']=='removable_insole')['assignments']
    assert assignment and assignment[0]['product_id']=='Pace 01'


def test_restart_after_extract_failure_reuses_checkpoint(tmp_path):
    q=Queue(tmp_path/'queue.sqlite');m,r=inputs();jid=q.enqueue(m,r)
    def fail(*a,**k):
        raise RuntimeError('Simulated extractor failure')
    with pytest.raises(RuntimeError):
        run_once(q,job_id=jid,hooks={'extract':fail})
    assert q.checkpoint(jid,'benchmark')
    q.retry(jid)
    def no_benchmark(*a,**k):
        raise AssertionError('Benchmark must not run again')
    done=run_once(q,job_id=jid,hooks={'benchmark':no_benchmark})
    assert done['status']=='completed'
    assert 'benchmark' in done['metrics']['reused_stages']


def test_same_sources_new_demand_reuse_target_extraction(tmp_path):
    q=Queue(tmp_path/'queue.sqlite');m,r=inputs();old=q.enqueue(m,r);run_once(q,job_id=old)
    r[0]['count']+=1
    new=q.enqueue(m,r)
    out=run_once(q,job_id=new)
    assert any(x.startswith('extract:') for x in out['metrics']['reused_stages'])


def test_optional_geometry_is_inspection_only_and_checkpointed(tmp_path):
    q=Queue(tmp_path/'queue.sqlite');m,r=inputs()
    contract=dict(model='synthetic-test',dimensions=2)
    m['intent_hints'][0].update(embedding=[1,0],embedding_contract=contract)
    for row in r:
        if row['role']=='catalog':
            row.update(embedding=[1,0],embedding_contract=contract)
    plain=q.enqueue(m,r);before=run_once(q,job_id=plain)
    inspected=q.enqueue(m,r,options={'geometry':True});after=run_once(q,job_id=inspected)
    assert before['projection']==after['projection']
    diagnostic=next(g for g in after['geometry'] if g['candidate_key']=='toe_box')
    assert diagnostic['status']=='available'
    assert diagnostic['metrics']['external_calls']==0
    assert q.checkpoint(inspected,'geometry:toe_box')
    assert any(g['status']=='not_available' for g in after['geometry'])
