import json

from pilon.loop.app import create_app
from pilon.loop.store import Queue
from pilon.loop.demo import inputs
from pilon.loop.worker import run_once


def get(app,path='/',method='GET',host='127.0.0.1:8473'):
    result={}
    def start(status,headers):
        result.update(status=status,headers=dict(headers))
    result['body']=b''.join(app(dict(PATH_INFO=path,REQUEST_METHOD=method,HTTP_HOST=host),start))
    return result


def test_read_only_local_jobs_and_partial_report(tmp_path):
    q=Queue(tmp_path/'q.sqlite');app=create_app(q)
    assert get(app)['status']=='200 OK'
    m,r=inputs();jid=q.enqueue(m,r)
    assert json.loads(get(app,'/api/jobs')['body'])[0]['id']==jid
    api=get(app,'/api/jobs/'+jid)
    assert json.loads(api['body'])['status']=='queued'
    assert get(app,'/jobs/'+jid)['status']=='200 OK'
    assert get(app,'/jobs/missing')['status']=='404 Not Found'
    assert get(app,method='POST')['status']=='405 Method Not Allowed'
    assert get(app,host='example.com')['status']=='403 Forbidden'
    assert get(app,method='HEAD')['body']==b''
    assert q.get(jid)['status']=='queued'


def test_benchmark_workspace_uses_frozen_inputs_and_keeps_full_report_separate(tmp_path):
    q=Queue(tmp_path/'q.sqlite')
    m,r=inputs()
    jid=q.enqueue(m,r,synthetic=True)
    run_once(q,job_id=jid)
    app=create_app(q)
    before=q.get(jid)
    page=get(app,'/jobs/'+jid)
    assert page['status']=='200 OK'
    html=page['body'].decode()
    raw=html.split('<script type="application/json" id="benchmark-data">',1)[1].split('</script>',1)[0]
    data=json.loads(raw)
    assert data['model']==m
    assert data['summary']['demand_events']==62
    assert data['summary']['opportunity_count']==5
    assert len(data['demands'])==9
    assert 'extractions' not in data
    assert 'projection' not in data
    assert '<title>PILON Benchmark</title>' in html
    full=get(app,'/reports/'+jid)
    assert full['status']=='200 OK'
    assert 'id="extract"' in full['body'].decode()
    assert q.get(jid)==before


def test_display_translation_does_not_change_the_raw_report_or_job(tmp_path):
    q=Queue(tmp_path/'q.sqlite')
    model,records=inputs()
    jid=q.enqueue(model,records,synthetic=True)
    run_once(q,job_id=jid)
    original=q.get(jid)
    app=create_app(q)
    before=get(app,'/api/jobs/'+jid)['body']
    generated=original['result']['candidates'][0]['label']
    localized=create_app(q,display_translations={generated:'English display label'})
    html=get(localized,'/jobs/'+jid)['body'].decode()
    raw=html.split('<script type="application/json" id="benchmark-data">',1)[1].split('</script>',1)[0]
    data=json.loads(raw)
    assert any(c['label']=='English display label' for c in data['candidates'])
    assert data['model']==model
    assert get(localized,'/api/jobs/'+jid)['body']==before
    assert q.get(jid)==original


def test_extract_and_induct_are_separate_read_only_workspaces(tmp_path):
    q=Queue(tmp_path/'q.sqlite')
    model,records=inputs()
    jid=q.enqueue(model,records,synthetic=True)
    run_once(q,job_id=jid)
    before=q.get(jid)
    app=create_app(q)
    for stage in ('extract','induct'):
        response=get(app,'/'+stage+'/'+jid)
        assert response['status']=='200 OK'
        assert b'<html' in response['body'] and stage.encode() in response['body'].lower()
    assert q.get(jid)==before
