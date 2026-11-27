import json
from pathlib import Path

import pytest

from pilon.cli import main
from pilon.loop.demo import inputs
from pilon.loop.store import Queue
from pilon.loop.worker import run_once
from pilon.loop.projection import read_published, read_history


def feed(tmp_path):
    model,records=inputs()
    m=tmp_path/'model.json';s=tmp_path/'signals.jsonl'
    m.write_text(json.dumps(model),encoding='utf-8')
    s.write_text('\n'.join(json.dumps(r) for r in records),encoding='utf-8')
    return m,s


def test_watch_unchanged_content_does_not_duplicate_jobs(tmp_path,capsys):
    m,s=feed(tmp_path);db=tmp_path/'jobs.sqlite'
    args=['loop','watch','--model',str(m),'--signals',str(s),'--db',str(db),'--once']
    assert main(args)==0
    first=json.loads(capsys.readouterr().out)['job_id']
    assert main(args)==0
    assert json.loads(capsys.readouterr().out)['job_id']==first
    assert len(Queue(db).jobs())==1


def test_publish_is_explicit_idempotent_and_rollback_restores_base(tmp_path,capsys):
    db=tmp_path/'jobs.sqlite';store=tmp_path/'models'
    q=Queue(db);m,r=inputs();jid=q.enqueue(m,r);run_once(q,job_id=jid)
    assert not store.exists()
    args=['loop','publish',jid,'--db',str(db),'--store',str(store),'--actor','test']
    assert main(args)==0
    assert json.loads(capsys.readouterr().out)['current_revision']==1
    assert read_published(store)['model']!=m
    assert main(args)==0
    assert json.loads(capsys.readouterr().out)['current_revision']==1
    assert main(['loop','rollback','--db',str(db),'--store',str(store),'--actor','test',
                 '--target','0','--expected-current','1'])==0
    assert read_published(store)['model']==m
    assert [a['operation'] for a in read_history(store)]==['initialize','publish','rollback']


def test_revisit_needs_only_new_sources_and_preserves_old_report(tmp_path,capsys):
    db=tmp_path/'jobs.sqlite';q=Queue(db);m,r=inputs();old=q.enqueue(m,r)
    before=run_once(q,job_id=old)
    _,r2=inputs(with_new_source=True)
    extra=next(x for x in r2 if x['id']=='new-pim-insole')
    newfile=tmp_path/'new-source.jsonl';newfile.write_text(json.dumps(extra),encoding='utf-8')
    main(['loop','revisit',old,'--signals',str(newfile),'--db',str(db)])
    jid=json.loads(capsys.readouterr().out)['job_id']
    after=run_once(q,job_id=jid)
    assert any(e['assignments'] for e in after['extractions'] if e['candidate_key']=='removable_insole')
    from pilon.loop.worker import report
    assert report(q,old)==before


def test_revisit_rejects_changed_source_under_same_id(tmp_path):
    db=tmp_path/'jobs.sqlite';q=Queue(db);m,r=inputs();jid=q.enqueue(m,r)
    path=tmp_path/'changed.jsonl';path.write_text(json.dumps({**r[0],'text':'changed'}),encoding='utf-8')
    with pytest.raises(SystemExit) as exc:
        main(['loop','revisit',jid,'--signals',str(path),'--db',str(db)])
    assert exc.value.code==2
    assert len(q.jobs())==1


def test_export_cannot_overwrite_database(tmp_path):
    db=tmp_path/'jobs.sqlite';q=Queue(db);m,r=inputs();jid=q.enqueue(m,r)
    before=db.read_bytes()
    with pytest.raises(SystemExit) as exc:
        main(['loop','report',jid,'--db',str(db),'--output',str(db)])
    assert exc.value.code==2
    assert db.read_bytes()==before


def test_publication_cannot_use_incomplete_job(tmp_path):
    db=tmp_path/'jobs.sqlite';q=Queue(db);m,r=inputs();jid=q.enqueue(m,r)
    with pytest.raises(SystemExit):
        main(['loop','publish',jid,'--db',str(db),'--store',str(tmp_path/'models'),'--actor','test'])
    assert not (tmp_path/'models').exists()
