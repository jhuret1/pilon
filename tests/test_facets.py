import csv
import json
import subprocess
import sys
from copy import deepcopy

import pytest

from pilon.facets import STAGES, Spec, explore
from pilon.facets.commands import EXAMPLE
from pilon.facets.io import read_signals


@pytest.fixture
def feed():
    return (json.loads((EXAMPLE / "model.json").read_text(encoding="utf-8")),
            list(read_signals(EXAMPLE / "signals.jsonl")))


def test_discovery_forecast_induction_usage(feed):
    model, rows = feed
    by_id = {r["id"]: r for r in rows}
    for index, stage in enumerate(STAGES):
        report = explore(model, rows + rows, through=stage, horizon_days=60)
        candidate, = report["candidates"]
        assert candidate["key"] == "toe_box"
        assert candidate["demand_events"] == 34
        assert len(candidate["external_records"]) == 1
        assert all((name in candidate) == (i <= index) for i, name in enumerate(STAGES) if i)
    assert candidate["forecast"]["projected_demand_events"] == 68
    assert candidate["forecast"]["assignable_products"] == 4
    for item in candidate["induction"]["assignments"]:
        for proof in item["evidence"]:
            row = by_id[proof["record_id"]]
            assert row["product_id"] == item["product_id"]
            assert proof["quote"] == row["text"][proof["start"]:proof["end"]]
    assert candidate["usage"]["product_ids_by_value"]["wide"] == ["Pace 01", "Tempo 03"]
    assert candidate["induction"]["unknown_products"] == ["Cloud 05"]
    conflict, = candidate["induction"]["conflicts"]
    assert conflict["product_id"] == "Peak 06"
    assert set(conflict["competing_values"]) == {"tapered", "wide"}


def test_new_facet_reacts_to_inputs(feed):
    model, rows = feed
    model["existing_facets"].append("toe_box")
    assert not explore(model, rows)["candidates"]
    rows += [dict(id="a", role="demand", source="chat", text="Do you have a removable insole?",
                  category=model["category"], date=model["window_end"]),
             dict(id="b", role="catalog", source="pim", text="Removable insole: yes",
                  product_id="Pace 01", category=model["category"])]
    candidate, = explore(model, rows)["candidates"]
    assert candidate["key"] == "removable_insole"
    rows[-2]["date"] = "2026-08-31"
    assert not explore(model, rows)["candidates"]
    rows[-2].update(role="external", date=model["window_end"])
    outside, = explore(model, rows)["candidates"]
    assert outside["signal_origin"] == "external_only"
    assert outside["demand_events"] == 0
    assert outside["forecast"]["projected_demand_events"] is None


def test_duplicates_and_custom_extractor(feed):
    model, rows = feed
    copy = deepcopy(rows[0])
    copy["count"] += 1
    with pytest.raises(ValueError, match="Conflicting records"):
        explore(model, rows + [copy])
    # Custom extraction can work on prose containing a Unicode character.
    rows = [rows[0], dict(rows[-1], text="Édition route. Room at the front.")]
    def extractor(text):
        start = text.index("Room")
        yield Spec("Toe box", "wide", start, len(text))
    result = explore(model, rows, extract_specs=extractor)
    proof = result["candidates"][0]["induction"]["assignments"][0]["evidence"][0]
    assert proof["quote"] == "Room at the front."
    with pytest.raises(ValueError, match="Invalid evidence span"):
        explore(model, rows, extract_specs=lambda text: [Spec("Toe box", "wide", 0, 999)])


def test_csv_and_jsonl_cli_match_and_escape_user_text(feed, tmp_path):
    model, rows = feed
    rows[0]["text"] += "<script>untrusted()</script>"
    model_path = tmp_path / "model.json"
    model_path.write_text(json.dumps(model), encoding="utf-8")
    csv_path = tmp_path / "signals.csv"
    fields = sorted(set().union(*(r.keys() for r in rows)))
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        writer.writerows(rows)
    command = [sys.executable, "-m", "pilon", "discover", "--model", str(model_path), "--signals"]
    html_path = tmp_path / "preview.html"
    via_csv = subprocess.run(command + [str(csv_path), "--html", str(html_path)],
                             capture_output=True, check=True)
    payload = "\n".join(json.dumps(row) for row in rows).encode()
    via_pipe = subprocess.run(command + ["-"], input=payload, capture_output=True, check=True)
    assert json.loads(via_csv.stdout) == json.loads(via_pipe.stdout) == explore(model, rows)
    assert "&lt;script&gt;" in html_path.read_text(encoding="utf-8")
    assert "<script>untrusted" not in html_path.read_text(encoding="utf-8")
