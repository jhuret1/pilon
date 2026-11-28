"""Offline reproductions of the seven background-loop review findings."""
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest

from pilon.cli import main
from pilon.loop import commands
from pilon.loop.benchmark import benchmark
from pilon.loop.extraction import extract
from pilon.loop.projection import build_projection
from pilon.loop.store import LeaseLost, Queue
from pilon.loop.worker import run_once


def _inputs():
    model = dict(
        category="shoes", window_start="2026-09-01", window_end="2026-09-30",
        existing_facets=["shoe_toe_shape"],
        facets=[dict(key="shoe_toe_shape", label="Toe box", values=[],
                     aliases=["front space"])],
        aliases={"Toe box": ["room for toes"]}, assignments=[],
    )
    records = [
        dict(id="q", role="demand", source="search", category="shoes",
             date="2026-09-01", text="Toe box", count=3),
        dict(id="s", role="catalog", source="merchant", category="shoes",
             product_id="P1", text="Toe box: wide"),
    ]
    return model, records


def test_claim_never_returns_a_replacement_workers_token(tmp_path, monkeypatch):
    first = Queue(tmp_path / "jobs.sqlite")
    second = Queue(first.path)
    jid = first.enqueue({}, [])
    original_db = first.db
    reclaimed = []
    armed = True

    @contextmanager
    def reclaim_after_commit():
        nonlocal armed
        with original_db() as db:
            yield db
        # Schedule B precisely after A commits, before A returns. A fixed claim
        # has already captured its own token; an out-of-transaction get has not.
        if armed:
            armed = False
            with second.db() as db:
                db.execute("UPDATE jobs SET lease_until=0 WHERE id=?", (jid,))
            reclaimed.append(second.claim(owner="worker-B", job_id=jid))

    monkeypatch.setattr(first, "db", reclaim_after_commit)
    claimed = first.claim(owner="worker-A", job_id=jid)
    assert reclaimed[0]["owner"] == "worker-B"
    assert reclaimed[0]["attempts"] == 2
    assert claimed["owner"] == "worker-A"
    assert claimed["attempts"] == 1
    with pytest.raises(LeaseLost):
        first.save_stage(jid, claimed["owner"], "benchmark", "input", {"stale": True})
    assert second.checkpoint(jid, "benchmark") is None
    second.save_stage(jid, reclaimed[0]["owner"], "benchmark", "input", {"current": True})
    assert second.checkpoint(jid, "benchmark")["data"] == {"current": True}


@pytest.mark.parametrize("intent", [
    pytest.param(dict(label="Toe box"), id="display-label"),
    pytest.param(dict(key="toe_box", label="Toe box"), id="display-key"),
    pytest.param(dict(key="proposed_toe_room", label="Toe room", aliases=["Toe box"]),
                 id="alias"),
])
def test_supplied_intents_reuse_schema_identity_and_preserve_proof(intent):
    model, records = _inputs()
    records[0]["intents"] = [dict(intent, quote="Toe box", start=0, end=7)]
    before = deepcopy((model, records))
    result = benchmark(model, records)
    candidate, = result["candidates"]
    assert candidate["key"] == "shoe_toe_shape"
    assert candidate["label"] == intent["label"]
    assert candidate["gap_type"] == "coverage_gap"
    assert candidate["demand_records"] == [dict(
        record_id="q", source="search", quote="Toe box", start=0, end=7, count=3,
    )]
    extraction = extract(candidate, records, model)
    projection = build_projection(model, [candidate], [extraction])
    assert [facet["key"] for facet in projection["projected_model"]["facets"]] == ["shoe_toe_shape"]
    assert all(change["op"] != "add" for change in projection["schema_changes"])
    assignment, = projection["assignment_changes"]
    assert assignment["fact_key"] == "shoe_toe_shape"
    assert assignment["after"]["value"] == "wide"
    assert {proof["record_id"] for proof in assignment["after"]["evidence"]} == {"s"}
    assert (model, records) == before


@pytest.mark.parametrize("once", [False, True], ids=["continuous", "once"])
def test_worker_continues_after_failed_job_but_once_reports_failure(tmp_path, monkeypatch, once):
    queue = Queue(tmp_path / "jobs.sqlite")
    model, records = _inputs()
    invalid = dict(model)
    invalid.pop("window_start")
    bad = queue.enqueue(invalid, records)
    good = queue.enqueue(model, records)
    with queue.db() as db:
        db.execute("UPDATE jobs SET created=0 WHERE id=?", (bad,))
        db.execute("UPDATE jobs SET created=1 WHERE id=?", (good,))
    calls = []
    real_run_once = commands.run_once

    class StopPolling(BaseException):
        """End the test after two real attempts, even if no job completes."""

    def bounded_run_once(*args, **kwargs):
        if len(calls) == 2:
            raise StopPolling()
        calls.append(True)
        return real_run_once(*args, **kwargs)

    monkeypatch.setattr(commands, "run_once", bounded_run_once)
    monkeypatch.setattr(commands, "time", SimpleNamespace(sleep=lambda seconds: None))
    argv = ["loop", "work", "--db", str(queue.path), "--poll-seconds", "0.001"]
    if once:
        with pytest.raises(SystemExit) as exc:
            main(argv + ["--once"])
        assert exc.value.code == 2
    else:
        with pytest.raises(StopPolling):
            main(argv)
    assert queue.get(bad)["status"] == "failed"
    assert queue.get(good)["status"] == ("queued" if once else "completed")
    assert len(calls) == (1 if once else 2)


@pytest.mark.parametrize("case", [
    "null", "empty", "whitespace", "contradiction", "model-only-product",
    "explicit-false", "explicit-zero",
])
def test_coverage_requires_known_values_for_every_known_product(case):
    model, records = _inputs()
    values = {
        "null": [None], "empty": [""], "whitespace": ["   "],
        "contradiction": ["wide", "narrow"], "model-only-product": ["wide"],
        "explicit-false": [False], "explicit-zero": [0],
    }[case]
    model["assignments"] = [dict(fact_key="shoe_toe_shape", product_id="P1", value=value)
                            for value in values]
    if case == "model-only-product":
        model["assignments"].append(dict(fact_key="size", product_id="P2", value="10"))
    result = benchmark(model, records)
    if case in {"explicit-false", "explicit-zero"}:
        assert result["candidates"] == []
        assert result["already_represented"] == [dict(
            record_id="q", fact_key="shoe_toe_shape", status="already_represented",
        )]
    else:
        candidate, = result["candidates"]
        assert candidate["key"] == "shoe_toe_shape"
        assert candidate["gap_type"] == "coverage_gap"
        assert candidate["demand_events"] == 3
        assert result["already_represented"] == []
        if case == "model-only-product":
            assert result["metrics"]["inventory_products"] == 2


@pytest.mark.parametrize("asset_type", ["image", "document"])
def test_empty_catalog_asset_survives_as_unanalysed_without_product_facts(tmp_path, asset_type):
    model, records = _inputs()
    records[1].update(asset_type=asset_type, text="")
    queue = Queue(tmp_path / "jobs.sqlite")
    jid = queue.enqueue(model, records)
    result = run_once(queue, job_id=jid)
    assert result["status"] == "completed"
    assert queue.get(jid)["payload"]["records"] == records
    extraction, = result["extractions"]
    assert extraction["assignments"] == []
    assert extraction["unknown_products"] == ["P1"]
    assert extraction["unanalysed_products"] == ["P1"]
    unsupported, = extraction["routing"]["unsupported"]
    assert unsupported["record_id"] == "s"
    assert unsupported["analysis_status"] == "unanalysed"
    assert result["projection"]["assignment_changes"] == []
    assert result["projection"]["schema_changes"] == []


@pytest.mark.parametrize("origin", ["supplied", "extractor"])
def test_empty_intents_remain_unresolved_even_when_a_configured_alias_matches(origin):
    model, records = _inputs()
    kwargs = {}
    if origin == "supplied":
        records[0]["intents"] = []
    else:
        kwargs["intent_extractor"] = lambda row: []
    result = benchmark(model, records, **kwargs)
    candidate, = result["candidates"]
    assert candidate["gap_type"] == "unresolved_intent"
    assert candidate["status"] == "needs_definition"
    assert candidate["key"].startswith("unresolved_")
    assert candidate["aliases"] == []
    assert candidate["demand_events"] == result["metrics"]["demand_events"] == 3
    assert candidate["demand_records"] == [dict(
        record_id="q", source="search", quote="Toe box", start=0, end=7, count=3,
    )]
    assert result["already_represented"] == []


@pytest.mark.parametrize("operation,value", [
    pytest.param(operation, value, id=f"{operation}-{name}")
    for operation in ("claim-lease", "claim-now", "heartbeat")
    for name, value in (("nan", float("nan")), ("inf", float("inf")), ("negative-inf", -float("inf")))
] + [pytest.param("cli", float("nan"), id="cli-nan")])
def test_nonfinite_lease_inputs_are_rejected_before_mutating_jobs(tmp_path, operation, value):
    queue = Queue(tmp_path / "jobs.sqlite")
    model, records = _inputs()
    jid = queue.enqueue(model, records)
    if operation == "heartbeat":
        queue.claim(owner="worker", job_id=jid)
    before = queue.get(jid)
    if operation == "cli":
        with pytest.raises(SystemExit) as exc:
            main(["loop", "work", "--once", "--db", str(queue.path),
                  "--lease-seconds", "nan"])
        assert exc.value.code == 2
    else:
        with pytest.raises(ValueError):
            if operation == "claim-lease":
                queue.claim(owner="worker", job_id=jid, lease_seconds=value)
            elif operation == "claim-now":
                queue.claim(owner="worker", job_id=jid, now=value)
            else:
                queue.heartbeat(jid, "worker", lease_seconds=value)
    assert queue.get(jid) == before
    if operation != "heartbeat":
        assert queue.claim(owner="recovery", job_id=jid)["id"] == jid
