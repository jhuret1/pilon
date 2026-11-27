"""Read-only loopback viewer for a single discovery result."""
import json
from wsgiref.simple_server import make_server

from .facets.report import render


def create_app(report):
    pages = {
        "/": ("text/html; charset=utf-8", render(report).encode("utf-8")),
        "/api/report": ("application/json", json.dumps(report, ensure_ascii=False).encode("utf-8")),
    }

    def app(environ, start_response):
        path = environ.get("PATH_INFO", "/")
        host = environ.get("HTTP_HOST", "").partition(":")[0].lower()
        method = environ["REQUEST_METHOD"]
        status = "200 OK"
        mime, body = "text/plain", b""
        if host not in {"localhost", "127.0.0.1"}:
            status = "403 Forbidden"
        elif method not in {"GET", "HEAD"}:
            status = "405 Method Not Allowed"
        elif path not in pages:
            status = "404 Not Found"
        else:
            mime, body = pages[path]
        headers = [
            ("Content-Type", mime), ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"),
            ("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'"),
        ]
        if status.startswith("405"):
            headers.append(("Allow", "GET, HEAD"))
        start_response(status, headers)
        return [b"" if method == "HEAD" else body]

    return app


def serve_report(report, port):
    with make_server("127.0.0.1", port, create_app(report)) as server:
        print(f"PILON Discovery: http://127.0.0.1:{server.server_port}/", flush=True)
        server.serve_forever()
