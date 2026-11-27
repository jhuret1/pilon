"""Read-only, loopback experiment viewer. Opening it never starts inference."""
from pathlib import Path
from flask import Flask, jsonify, send_from_directory, request, abort
from .store import Store
from .service import snapshot


def create_app(db_path):
    web = Path(__file__).with_name('web')
    app = Flask(__name__, static_folder=str(web), static_url_path='/assets')
    app.config.update(MAX_CONTENT_LENGTH=1024 * 1024)
    store = Store(db_path)

    @app.before_request
    def local_only():
        if request.host.split(':')[0] not in ('localhost', '127.0.0.1'):
            abort(403)

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.get('/')
    def index():
        return send_from_directory(web, 'index.html')

    @app.get('/api/runs')
    def runs():
        return jsonify([dict(id=r['id'], status=r['status'], provider=r['config']['provider'], processed=r['processed'])
                        for r in store.runs()])

    @app.get('/api/runs/<rid>')
    def detail(rid):
        try:
            return jsonify(snapshot(store, rid))
        except ValueError:
            abort(404)

    return app
