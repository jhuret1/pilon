import json

from pilon.loop.app import create_app
from pilon.loop.store import Queue
from pilon.loop.demo import inputs


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
