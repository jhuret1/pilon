"""Read-only local cockpit over durable background jobs."""
import json
from wsgiref.simple_server import make_server
from .report import render_loop
from .worker import report


def create_app(queue):
    def app(environ,start_response):
        path=environ.get('PATH_INFO','/')
        host=environ.get('HTTP_HOST','').partition(':')[0].lower()
        method=environ.get('REQUEST_METHOD','GET')
        status,mime,body='200 OK','text/plain; charset=utf-8',b''
        try:
            if host not in ('localhost','127.0.0.1'):
                status='403 Forbidden'
            elif method not in ('GET','HEAD'):
                status='405 Method Not Allowed'
            elif path=='/api/jobs':
                mime='application/json';body=json.dumps(queue.jobs(),ensure_ascii=False).encode()
            elif path.startswith('/api/jobs/'):
                mime='application/json';body=json.dumps(report(queue,path[len('/api/jobs/'):]),ensure_ascii=False).encode()
            elif path=='/' or path.startswith('/jobs/'):
                jobs=queue.jobs()
                jid=path[len('/jobs/'):] if path.startswith('/jobs/') else (jobs[0]['id'] if jobs else None)
                snapshot=report(queue,jid) if jid else dict(status='empty',candidates=[],extractions=[],projection=None,metrics={},events=[])
                snapshot['jobs']=jobs
                mime='text/html; charset=utf-8';body=render_loop(snapshot).encode()
            else:
                status='404 Not Found'
        except ValueError:
            status='404 Not Found';body=b'Unknown job'
        headers=[('Content-Type',mime),('Content-Length',str(len(body))),('Cache-Control','no-store'),
                 ('X-Content-Type-Options','nosniff'),
                 ('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")]
        if status.startswith('405'):
            headers.append(('Allow','GET, HEAD'))
        start_response(status,headers)
        return [b'' if method=='HEAD' else body]
    return app


def serve(queue,port=8473):
    with make_server('127.0.0.1',port,create_app(queue)) as server:
        print(f'PILON background cockpit: http://127.0.0.1:{server.server_port}/',flush=True)
        server.serve_forever()
