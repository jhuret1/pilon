import json
from pathlib import Path
from wsgiref.util import setup_testing_defaults

import pytest

from pilon import explore
from pilon.app import create_app
from pilon.cli import main
from pilon.facets.commands import EXAMPLE
from pilon.facets.io import read_signals


@pytest.mark.parametrize("args", [[], ["demo"], ["demo", "ecommerce-facets"], ["demo", "--no-serve"]])
def test_default_experience(args, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(args) == 0
    html = Path("runtime/ecommerce-facets.html").read_text(encoding="utf-8")
    assert all(label in html for label in ("Découverte", "Prévision", "Induction", "Usage", "Pace 01"))


def request(app, path, method="GET", host="127.0.0.1:8472"):
    env = {}
    setup_testing_defaults(env)
    env.update(PATH_INFO=path, REQUEST_METHOD=method, HTTP_HOST=host)
    response = []
    body = b"".join(app(env, lambda status, headers: response.append((status, dict(headers)))))
    return response[0], body


def test_serve_and_exports_show_the_same_snapshot(tmp_path, monkeypatch):
    from pilon import app as server

    json_path = tmp_path / "out.json"
    html_path = tmp_path / "out.html"
    assert main(["demo", "--output", str(json_path), "--html", str(html_path)]) == 0
    snapshots = []
    monkeypatch.setattr(server, "serve_report", lambda report, port: snapshots.append((report, port)))
    assert main(["serve"]) == 0
    data, port = snapshots[0]
    app = create_app(data)
    assert port == 8472
    (status, headers), body = request(app, "/")
    assert status == "200 OK" and headers["Cache-Control"] == "no-store"
    assert body.decode() == html_path.read_text(encoding="utf-8")
    assert json.loads(request(app, "/api/report")[1]) == json.loads(json_path.read_text("utf-8"))
    assert request(app, "/", "HEAD")[1] == b""
    assert request(app, "/", "POST")[0][0].startswith("405")
    assert request(app, "/missing")[0][0].startswith("404")
    assert request(app, "/", host="external.example")[0][0].startswith("403")


def test_precomputed_annotations_require_the_original_quote():
    model = json.loads((EXAMPLE / "model.json").read_text(encoding="utf-8"))
    rows = list(read_signals(EXAMPLE / "signals.jsonl"))
    row = {"id": "enriched-42", "category": model["category"], "role": "catalog",
           "source": "adapter", "product_id": "SKU-42", "text": "Été. Room for toes.",
           "extractions": [{"char_interval": {"start_pos": 5, "end_pos": 18},
                            "extraction_text": "Room for toes",
                            "attributes": {"label": "Toe box", "value": "wide"}}]}
    candidate, = explore(model, [*rows, row])["candidates"]
    assert "SKU-42" in candidate["usage"]["product_ids_by_value"]["wide"]
    row["text"] = "Editing this invalidates the offsets."
    with pytest.raises(ValueError, match="Unverified source quotation"):
        explore(model, [*rows, row])


def test_separate_source_exports_match_a_single_snapshot(tmp_path):
    rows = list(read_signals(EXAMPLE / "signals.jsonl"))
    paths = []
    for role in ("catalog", "demand", "external"):
        path = tmp_path / f"{role}.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in rows if r["role"] == role), encoding="utf-8")
        paths.extend(["--signals", str(path)])
    out = tmp_path / "report.json"
    model_path = EXAMPLE / "model.json"
    assert main(["discover", "--model", str(model_path), *paths, "--output", str(out)]) == 0
    assert json.loads(out.read_text("utf-8")) == explore(json.loads(model_path.read_text("utf-8")), rows)
