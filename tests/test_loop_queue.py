import time
import pytest
from pilon.loop.store import Queue, LeaseLost, fingerprint


def test_immutable_inputs_and_idempotent_enqueue(tmp_path):
    q=Queue(tmp_path/'jobs.sqlite')
    m=dict(category='shoes');r=[dict(id='x',text='source')]
    jid=q.enqueue(m,r)
    assert q.enqueue(m,r)==jid
    r[0]['text']='edited'
    assert q.get(jid)['payload']['records'][0]['text']=='source'
    assert q.enqueue(m,r)!=jid


def test_lease_reclaim_fences_old_worker(tmp_path):
    q=Queue(tmp_path/'jobs.sqlite');jid=q.enqueue({},[])
    a=q.claim(owner='old',lease_seconds=60)
    assert a['id']==jid and q.claim(owner='other') is None
    with q.db() as db:
        db.execute('UPDATE jobs SET lease_until=? WHERE id=?',(time.time()-1,jid))
    b=q.claim(owner='new')
    assert b['attempts']==2
    with pytest.raises(LeaseLost):
        q.save_stage(jid,'old','benchmark','hash',{'old':True})
    q.save_stage(jid,'new','benchmark','hash',{'ok':True})
    assert q.checkpoint(jid,'benchmark')['data']=={'ok':True}
    assert q.cached('hash')=={'ok':True}


def test_completed_job_is_never_reclaimed(tmp_path):
    q=Queue(tmp_path/'jobs.sqlite');jid=q.enqueue({},[])
    q.claim(owner='worker')
    q.finish(jid,'worker',{'projection':{},'published':False})
    assert q.claim(owner='again',now=time.time()+100000) is None
    assert q.get(jid)['status']=='completed'


def test_corruption_and_checkpoint_overwrite_are_rejected(tmp_path):
    q=Queue(tmp_path/'jobs.sqlite');jid=q.enqueue({},[]);q.claim(owner='worker')
    q.save_stage(jid,'worker','step','key',{'ok':True})
    with pytest.raises(ValueError,match='overwrite'):
        q.save_stage(jid,'worker','step','key',{'different':True})
    with q.db() as db:
        db.execute("UPDATE checkpoints SET data='{}' WHERE job_id=?",(jid,))
    with pytest.raises(ValueError,match='Corrupt'):
        q.checkpoint(jid,'step')


def test_fail_retry_does_not_remove_completed_stages(tmp_path):
    q=Queue(tmp_path/'jobs.sqlite');jid=q.enqueue({},[]);q.claim(owner='worker')
    q.save_stage(jid,'worker','step','key',{'ok':True})
    q.fail(jid,'worker',ValueError('failed'))
    assert q.claim() is None
    q.retry(jid);assert q.claim(owner='again')['id']==jid
    assert q.checkpoint(jid,'step')['data']=={'ok':True}


def test_nonfinite_snapshot_is_rejected(tmp_path):
    q=Queue(tmp_path/'jobs.sqlite')
    with pytest.raises(ValueError):
        q.enqueue({'bad':float('nan')},[])
