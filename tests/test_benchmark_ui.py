"""Offline contracts for Benchmark's counts, source fidelity and inert HTML data."""

from copy import deepcopy
from html.parser import HTMLParser
import json

import pytest

from pilon.loop.benchmark import benchmark
from pilon.loop.benchmark_ui import build_view, render_benchmark
from pilon.loop.demo import inputs


class Page(HTMLParser):
    """Inspect actual HTML elements and JSON without evaluating source content."""

    def __init__(self, markup):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.scripts = []
        self.title = ""
        self._script = None
        self._in_title = False
        self.feed(markup)
        self.close()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append((tag, attrs))
        if tag == "script":
            self._script = {"attrs": attrs, "text": ""}
            self.scripts.append(self._script)
        elif tag == "title":
            self._in_title = True

    def handle_data(self, data):
        if self._script is not None:
            self._script["text"] += data
        elif self._in_title:
            self.title += data

    def handle_endtag(self, tag):
        if tag == "script":
            self._script = None
        elif tag == "title":
            self._in_title = False

    def data(self):
        containers = [script for script in self.scripts
                      if script["attrs"].get("type") == "application/json"]
        assert len(containers) == 1, "Benchmark must embed one usable JSON snapshot"
        return json.loads(containers[0]["text"])


def make_report(model, bp, **overrides):
    report = dict(id="test", status="completed", synthetic=True, model=model,
                  candidates=bp["candidates"], metrics={"benchmark": bp["metrics"]},
                  extractions=[], projection=None,
                  jobs=[dict(id="test", status="completed", stage="done")])
    report.update(overrides)
    return report


@pytest.fixture
def demo():
    model, records = inputs()
    bp = benchmark(model, records)
    return make_report(model, bp), records, bp


def test_demo_summary_counts_demand_once_across_candidates(demo):
    report, records, bp = demo
    view = build_view(report, records=records, benchmark=bp)

    assert {"id", "status", "synthetic", "model", "candidates", "demands", "jobs", "summary"} <= view.keys()
    assert view["id"] == "test"
    assert view["status"] == "completed"
    assert view["synthetic"] is True
    assert view["jobs"] == report["jobs"]
    assert sum(c["demand_events"] for c in bp["candidates"]) == 63
    expected = dict(demand_events=62, demand_records=9, opportunity_count=5,
                    schema_gaps=3, inventory_products=6)
    assert {key: view["summary"][key] for key in expected} == expected
    assert {r["id"] for r in view["demands"]} == {
        r["id"] for r in records if r["role"] == "demand"
    }
    shared = next(r for r in view["demands"] if r["id"] == "c1")
    assert shared["text"] == "Standard width fits me. Which pair gives me room for my toes?"
    assert {p["candidate_key"] for p in shared["matches"]} == {"width", "toe_box"}


def test_candidates_preserve_exact_proof_text_offsets_and_counts(demo):
    report, records, bp = demo
    candidates = build_view(report, records=records, benchmark=bp)["candidates"]
    original = {c["key"]: c for c in bp["candidates"]}
    sources = {r["id"]: r for r in records}

    assert {c["key"] for c in candidates} == set(original)
    for candidate in candidates:
        raw = original[candidate["key"]]
        for field in ("label", "definition", "gap_type", "status", "demand_events", "known_assignment_count"):
            assert candidate[field] == raw[field]
        assert candidate["demand_records"] == raw["demand_records"]
        for proof in candidate["demand_records"]:
            source = sources[proof["record_id"]]
            assert proof["quote"] == source["text"][proof["start"]:proof["end"]]
            assert proof["source"] == source["source"]
            assert proof["count"] == source.get("count", 1)
    toe = next(c for c in candidates if c["key"] == "toe_box")
    assert "avant-pied" in {p["quote"] for p in toe["demand_records"]}


def test_demands_filter_role_category_and_both_inclusive_date_boundaries():
    model, _ = inputs()
    base = dict(role="demand", source="site_search", category=model["category"], text="toe box")
    records = [
        dict(base, id="first", date=model["window_start"], count=3),
        dict(base, id="last", date=model["window_end"], count=5),
        dict(base, id="middle", date="2026-09-15"),
        dict(base, id="before", date="2026-08-31", count=17),
        dict(base, id="after", date="2026-10-01", count=19),
        dict(base, id="other-category", category="hiking-boots", date="2026-09-15", count=23),
        dict(base, id="external", role="external", date="2026-09-15", count=101),
        dict(base, id="catalog", role="catalog", product_id="P1", date="2026-09-15", count=103),
    ]
    bp = benchmark(model, records)
    view = build_view(make_report(model, bp), records=records, benchmark=bp)

    assert {r["id"] for r in view["demands"]} == {"first", "last", "middle"}
    assert view["summary"]["demand_events"] == 9
    assert view["summary"]["demand_records"] == 3
    assert view["summary"]["inventory_products"] == 1


def test_already_covered_demand_still_counts_without_any_opportunity():
    model, _ = inputs()
    model["assignments"] = [dict(fact_key="width", product_id="P1", value="wide")]
    records = [dict(id="covered", role="demand", source="site_search", category=model["category"],
                    text="shoe width", date=model["window_start"], count=4),
               dict(id="product", role="catalog", source="pim", category=model["category"],
                    text="Width: wide", product_id="P1")]
    bp = benchmark(model, records)
    assert bp["candidates"] == []
    assert bp["already_represented"]

    view = build_view(make_report(model, bp), records=records, benchmark=bp)
    assert view["candidates"] == []
    assert view["summary"]["demand_events"] == 4
    assert view["summary"]["demand_records"] == 1
    assert view["summary"]["opportunity_count"] == 0
    assert view["summary"]["schema_gaps"] == 0
    assert view["demands"][0]["text"] == "shoe width"
    assert view["demands"][0]["matches"] == []


def test_inventory_without_metrics_counts_distinct_products_in_the_original_model():
    model, _ = inputs()
    model["assignments"] = [dict(fact_key="width", product_id="model-only", value="wide")]
    base = dict(role="catalog", source="pim", category=model["category"], text="Width: wide")
    records = [dict(base, id="source-one", product_id="P1"),
               dict(base, id="source-two", product_id="P1"),
               dict(base, id="source-three", product_id="P2"),
               dict(base, id="other-category", category="hiking-boots", product_id="excluded")]
    report = dict(id="inventory", status="completed", model=model, candidates=[],
                  extractions=[dict(assignments=[dict(product_id="extracted-only", value="wide")])])

    view = build_view(report, records=records)
    assert view["summary"]["inventory_products"] == 3
    assert view["summary"]["demand_events"] == 0
    assert view["model"] == model


@pytest.mark.parametrize("omit_facets", [False, True], ids=["explicit-facets", "legacy-model"])
def test_model_remains_the_original_snapshot_not_extracted_or_projected(demo, omit_facets):
    report, records, bp = demo
    if omit_facets:
        report["model"].pop("facets")
    original = deepcopy(report["model"])
    extracted = [dict(fact_key="width", product_id=f"P{i}", value="wide") for i in range(10)]
    report["extractions"] = [dict(candidate_key="width", assignments=extracted, status="completed")]
    projected = dict(category="projected-only", facets=[dict(key="new-facet")], assignments=extracted)
    report["projection"] = dict(base_model=projected, projected_model=projected)

    view = build_view(report, records=records, benchmark=bp)
    assert view["model"] == original
    width = next(c for c in view["candidates"] if c["key"] == "width")
    assert width["known_assignment_count"] == 0
    assert width["gap_type"] == "coverage_gap"
    assert view["summary"]["inventory_products"] == 6


def test_unresolved_and_unsupported_needs_remain_visible(demo):
    report, records, bp = demo
    view = build_view(report, records=records, benchmark=bp)
    unresolved, = [c for c in view["candidates"] if c["gap_type"] == "unresolved_intent"]
    assert unresolved["status"] == "needs_definition"
    assert unresolved["aliases"] == []
    assert unresolved["demand_events"] == 1
    assert unresolved["demand_records"][0]["quote"] == "Something comfortable for my unusual situation."
    insole = next(c for c in view["candidates"] if c["key"] == "removable_insole")
    assert insole["status"] == "needs_extraction"
    assert insole["demand_events"] == 7
    assert insole["known_assignment_count"] == 0


def test_report_only_fallback_deduplicates_proofs_and_marks_excerpts(demo):
    report, _, _ = demo
    view = build_view(report)
    assert view["summary"]["demand_events"] == 62
    assert view["summary"]["demand_records"] == 9
    assert view["summary"]["inventory_products"] == 6
    assert view["complete_inputs"] is False
    assert all(r["excerpt_only"] is True for r in view["demands"])
    for demand in view["demands"]:
        assert demand["text"] in {proof["quote"] for proof in demand["matches"]}


def test_explicit_empty_records_do_not_fabricate_full_demands_from_proofs(demo):
    report, _, bp = demo
    view = build_view(report, records=[], benchmark=bp)
    assert view["complete_inputs"] is True
    assert view["demands"] == []
    assert view["summary"]["demand_events"] == 0
    assert view["summary"]["demand_records"] == 0
    assert len(view["candidates"]) == 5


@pytest.mark.parametrize("status", ["queued", "running", "failed", "cancelled", "empty"])
def test_incomplete_jobs_are_not_relabelled_completed(status):
    report = dict(id="pending", status=status, candidates=[], model={}, jobs=[])
    view = build_view(report)
    assert view["status"] == status
    assert view["ready"] is False
    assert view["synthetic"] is False
    assert view["candidates"] == view["demands"] == []
    assert view["summary"]["demand_events"] == 0
    assert view["summary"]["opportunity_count"] == 0
    assert Page(render_benchmark(report)).data()["status"] == status


def test_running_job_keeps_available_benchmark_results_without_claiming_completion(demo):
    report, records, bp = demo
    report["status"] = "running"
    view = build_view(report, records=records, benchmark=bp)
    assert view["status"] == "running"
    assert view["ready"] is True
    assert view["summary"]["demand_events"] == 62
    assert view["summary"]["opportunity_count"] == 5


@pytest.mark.parametrize("report", [None, {}])
def test_empty_report_does_not_substitute_demo_data(report):
    view = build_view(report)
    assert view["status"] == "empty"
    assert view["ready"] is False
    assert view["synthetic"] is False
    assert view["candidates"] == view["demands"] == view["jobs"] == []
    assert view["summary"]["demand_events"] == 0
    assert view["summary"]["opportunity_count"] == 0
    assert view["summary"]["inventory_products"] is None
    assert Page(render_benchmark(report)).data() == view


def test_build_and_render_do_not_mutate_inputs_and_are_repeatable(demo):
    report, records, bp = demo
    original = deepcopy(demo)
    first = build_view(report, records=records, benchmark=bp)
    markup = render_benchmark(report, records=records, benchmark=bp)
    assert build_view(report, records=records, benchmark=bp) == first
    assert render_benchmark(report, records=records, benchmark=bp) == markup
    assert demo == original

    first["model"]["facets"][0]["label"] = "changed only in view"
    first["candidates"][0]["demand_records"][0]["quote"] = "changed only in view"
    first["demands"][0]["text"] = "changed only in view"
    first["jobs"][0]["status"] = "changed only in view"
    assert demo == original


def test_render_is_benchmark_only_and_embeds_the_actual_snapshot(demo):
    report, records, bp = demo
    markup = render_benchmark(report, records=records, benchmark=bp)
    page = Page(markup)
    assert page.title == "PILON Benchmark"
    assert page.data() == build_view(report, records=records, benchmark=bp)
    ids = [attrs["id"] for _, attrs in page.tags if "id" in attrs]
    assert len(ids) == len(set(ids))
    assert not {"extract", "ingest", "products"} & set(ids)
    for tag, attrs in page.tags:
        if tag == "a":
            assert attrs.get("href") not in {"#extract", "#ingest", "#products", "/extract", "/ingest", "/products"}
        if tag == "script":
            assert "src" not in attrs, "The portable report must use its local data"
    assert page.data()["model"]["category"] == "running-shoes"
    assert page.data()["summary"]["demand_events"] == 62


@pytest.mark.parametrize("attack", [
    '</script><img src=x onerror="alert(1)"><script>alert(2)</script>',
    '</ScRiPt><svg onload="alert(3)"></svg>&\"\' café\u2028\u2029',
])
def test_script_injection_is_inert_and_json_round_trips_exact_source_text(attack):
    model, _ = inputs()
    model["description"] = attack
    records = [dict(id="untrusted-demand", role="demand", source=attack, category=model["category"],
                    date=model["window_start"], count=11, text=attack)]
    bp = benchmark(model, records)
    bp["candidates"][0]["label"] = attack
    report = make_report(model, bp, id=attack, jobs=[dict(id=attack, status="queued")])
    markup = render_benchmark(report, records=records, benchmark=bp)
    page = Page(markup)
    data = page.data()

    assert attack not in markup
    assert not any(tag in {"img", "svg", "iframe", "object", "embed"} for tag, _ in page.tags)
    assert all(not key.lower().startswith("on") for _, attrs in page.tags for key in attrs)
    assert len(page.scripts) == 2, "Source text must not create executable script elements"
    assert data == build_view(report, records=records, benchmark=bp)
    assert data["id"] == attack
    assert data["model"]["description"] == attack
    assert data["candidates"][0]["label"] == attack
    assert data["candidates"][0]["demand_records"][0]["quote"] == attack
    assert data["demands"][0]["text"] == attack
    assert data["demands"][0]["source"] == attack
    assert data["jobs"][0]["id"] == attack
