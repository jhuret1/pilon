"""Dashboard contracts: truthful states, actual snapshot diffs and inert source text."""

from copy import deepcopy
from html import escape
from html.parser import HTMLParser

import pytest

from pilon.loop.report import render_loop


class Page(HTMLParser):
    """Small stdlib structural probe; no browser or network is needed by tests."""

    def __init__(self, markup):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.text = []
        self.tables = []
        self.table = None
        self.row = None
        self.cell = None
        self.in_caption = False
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        if tag == "table":
            self.table = {"caption": "", "rows": []}
        elif tag == "caption":
            self.in_caption = True
        elif tag == "tr":
            self.row = []
        elif tag in ("td", "th"):
            self.cell = ""

    def handle_data(self, data):
        self.text.append(data)
        if self.table is not None and self.in_caption:
            self.table["caption"] += data
        if self.cell is not None:
            self.cell += data

    def handle_endtag(self, tag):
        if tag == "table":
            self.tables.append(self.table)
            self.table = None
        elif tag == "caption":
            self.in_caption = False
        elif tag in ("td", "th") and self.row is not None:
            self.row.append(self.cell)
            self.cell = None
        elif tag == "tr" and self.table is not None:
            self.table["rows"].append(self.row)
            self.row = None

    def table_named(self, prefix):
        return next(t["rows"][1:] for t in self.tables if t["caption"].startswith(prefix))


def proof(quote="Removable insole: yes", record="source-1"):
    return dict(record_id=record, source="Fiche fournisseur", quote=quote,
                start=0, end=len(quote), asset_type="text")


@pytest.fixture
def snapshot_report():
    before = dict(category="Chaussures", version="v1", existing_facets=["width", "obsolete"],
                  facets=[dict(key="width", label="Largeur", definition="Largeur du chaussant", values=["regular"])],
                  assignments=[dict(fact_key="width", product_id="Pace 01", value="regular", evidence=[proof("Width: regular")]),
                               dict(fact_key="obsolete", product_id="Old 02", value="old", evidence=[])])
    after = dict(category="Chaussures", version="v2", existing_facets=["width", "removable_insole"],
                 facets=[dict(key="width", label="Largeur", definition="Largeur du chaussant", values=["regular", "wide"]),
                         dict(key="removable_insole", label="Semelle amovible", definition="Semelle pouvant être retirée", values=[True, False])],
                 assignments=[dict(fact_key="width", product_id="Pace 01", value="wide", evidence=[proof("Width: wide", "source-2")]),
                              dict(fact_key="removable_insole", product_id="Tempo 03", value=False, evidence=[proof("Removable insole: no")])])
    return dict(schema_version=1, id="job-1", status="completed", model=before,
                candidates=[dict(key="removable_insole", label="Semelle amovible", definition="Une semelle retirable",
                                 gap_type="schema_gap", status="needs_extraction", demand_events=12,
                                 demand_records=[proof("Je cherche une semelle amovible", "demand-1")])],
                extractions=[dict(candidate_key="removable_insole", status="needs_review",
                                  assignments=[dict(product_id="Tempo 03", value=False, evidence=[proof("Removable insole: no")])],
                                  unknown_products=["Cloud 05"], unanalysed_products=["Image 07"],
                                  conflicts=[dict(product_id="Peak 06", competing_values={
                                      "yes": [proof("Removable insole: yes", "conflict-yes")],
                                      "no": [proof("Removable insole: no", "conflict-no")]})],
                                  routing=dict(method="lexical", selected=[dict(record_id="source-1", reason="lexical_match")],
                                               unselected=[dict(record_id="source-3", reason="budget_limit")],
                                               unsupported=[dict(record_id="image-7", product_id="Image 07", asset_type="image", reason="explicit_extractor_required", analysis_status="unanalysed")]),
                                  metrics=dict(retrieval=dict(selected_assets=1, unsupported_assets=1, elapsed_seconds=0.0042),
                                               extraction=dict(analyzed_assets=1, assigned_products=1, elapsed_seconds=0.0083)))],
                projection=dict(base_model=before, projected_model=after,
                                schema_changes=[], assignment_changes=[],  # deliberately not authoritative
                                blocked=[dict(candidate_key="removable_insole", product_id="Cloud 05", reason="no_evidence")],
                                summary=dict(status="proposed")),
                metrics={}, events=[], synthetic=True)


@pytest.mark.parametrize("report", [None, {}, [], {"model": None, "candidates": None, "extractions": None,
                                                   "projection": None, "events": None, "metrics": None, "jobs": None}])
def test_empty_reports_have_accessible_navigation_and_honest_unavailable_states(report):
    markup = render_loop(report)
    page = Page(markup)
    assert markup.startswith('<!doctype html><html lang="fr">')
    ids = [attrs["id"] for _, attrs in page.tags if "id" in attrs]
    assert len(ids) == len(set(ids))
    assert {"main", "benchmark", "extract", "ingest"} <= set(ids)
    assert {attrs["href"] for tag, attrs in page.tags if tag == "a"} == {
        "#main", "#benchmark", "#extract", "#ingest"}
    assert "Aucun besoin candidat disponible" in markup
    assert "Aucun résultat d’extraction disponible" in markup
    assert "Comparaison incomplète" in markup
    assert "Ce rapport ne renseigne pas l’état de publication" in markup
    assert not any(tag in {"script", "img", "iframe", "link", "form"} for tag, _ in page.tags)
    assert "@media(max-width:740px)" in markup
    assert ":focus-visible" in markup


def test_candidate_without_product_sources_survives_and_is_not_negative_evidence():
    markup = render_loop(dict(status="running", candidates=[dict(key="insole", label="Semelle amovible",
        demand_events=7, demand_records=[proof("Je veux une semelle amovible")], gap_type="schema_gap")]))
    benchmark = markup.split('id="benchmark"', 1)[1].split('id="extract"', 1)[0]
    assert "Semelle amovible" in benchmark
    assert "Besoin conservé · extraction non disponible" in benchmark
    assert "ils ne prouvent aucune propriété produit" in benchmark
    assert "Besoins en attente de preuves" in markup
    assert "Une source non sélectionnée ou non prise en charge ne prouve pas l’absence" in markup


def test_actual_snapshots_drive_schema_and_assignment_diff(snapshot_report):
    page = Page(render_loop(snapshot_report))
    schema = {row[0]: row for row in page.table_named("Schéma")}
    assert schema["obsolete"][3] == "Retrait"
    assert schema["width"][3] == "Modification"
    assert "regular" in schema["width"][1] and "wide" in schema["width"][2]
    assert schema["removable_insole"][3] == "Ajout"
    assert "Semelle pouvant être retirée" in schema["removable_insole"][2]
    assignments = page.table_named("Affectations")
    pace = next(row for row in assignments if "Pace 01" in row[0])
    assert "regular" in pace[1] and "Width: regular" in pace[1]
    assert "wide" in pace[2] and "Width: wide" in pace[2]
    assert pace[3] == "Modification"
    old = next(row for row in assignments if "Old 02" in row[0])
    assert "old" in old[1] and "Aucune affectation" in old[2] and old[3] == "Retrait"
    new = next(row for row in assignments if "Tempo 03" in row[0])
    assert "Non (valeur explicite)" in new[2] and new[3] == "Ajout"
    assert "Removable insole: no" in new[2]
    assert "À vérifier" in new[2]


def test_missing_after_snapshot_does_not_fake_removals(snapshot_report):
    snapshot_report["projection"].pop("projected_model")
    rows = Page(render_loop(snapshot_report)).table_named("Schéma")
    assert rows
    assert all(row[3] == "Comparaison indisponible" for row in rows)
    assert all("Instantané indisponible" in row[2] for row in rows)


def test_missing_base_snapshot_does_not_fake_additions(snapshot_report):
    snapshot_report.pop("model")
    snapshot_report["projection"].pop("base_model")
    rows = Page(render_loop(snapshot_report)).table_named("Affectations")
    assert rows
    assert all(row[3] == "Comparaison indisponible" for row in rows)


def test_empty_after_snapshot_is_a_real_diff_and_projection_base_takes_precedence(snapshot_report):
    snapshot_report["model"] = {"existing_facets": ["wrong_base"]}
    snapshot_report["projection"]["projected_model"] = {}
    rows = Page(render_loop(snapshot_report)).table_named("Schéma")
    assert {row[0] for row in rows} == {"width", "obsolete"}
    assert all(row[3] == "Retrait" for row in rows)


def test_evidence_only_changes_and_duplicate_assignments_remain_visible():
    before = dict(assignments=[dict(product_id="A", fact_key="width", value="wide", evidence=[proof("old")])])
    after = deepcopy(before)
    after["assignments"][0]["evidence"] = [proof("new")]
    after["assignments"].append(dict(product_id="A", fact_key="width", value="regular", evidence=[proof("conflict")]))
    row, = Page(render_loop(dict(model=before, projection=dict(projected_model=after)))).table_named("Affectations")
    assert "old" in row[1]
    assert all(value in row[2] for value in ("wide", "regular", "new", "conflict"))
    assert row[3] == "Modification"


def test_extraction_is_honest_about_routing_unknowns_conflicts_and_measured_metrics(snapshot_report):
    markup = render_loop(snapshot_report)
    extract = markup.split('id="extract"', 1)[1].split('id="ingest"', 1)[0]
    assert "Routage lexical" in extract
    assert "Adaptateur explicite requis pour cette source" in extract
    assert "Non analysé" in extract
    assert "Produits non analysés ou partiellement analysés" in extract
    assert "Sélection des sources" in extract and "Extraction des valeurs" in extract
    assert "0.0042" in extract and "0.0083" in extract
    assert "Non (valeur explicite)" in extract
    assert "Cloud 05" in extract and "Peak 06" in extract and "Image 07" in extract
    assert "Valeur en conflit : yes" in extract and "Valeur en conflit : no" in extract
    assert "Removable insole: yes" in extract and "Removable insole: no" in extract
    ingest = markup.split('id="ingest"', 1)[1]
    assert all(product in ingest for product in ("Cloud 05", "Peak 06", "Image 07"))
    assert "sans estimation de gain ni de rappel" in markup
    assert "ne mesurent ni la précision ni la couverture" in markup


def test_errors_and_partial_results_are_readable_without_discarding_results(snapshot_report):
    snapshot_report.update(status="failed", error="Adaptateur indisponible", events=[dict(stage="extract", error="Interrupted")])
    snapshot_report["extractions"][0]["error"] = "Source inaccessible"
    markup = render_loop(snapshot_report)
    assert "Le traitement a rencontré une erreur" in markup
    assert "Adaptateur indisponible" in markup and "Source inaccessible" in markup
    assert "Les résultats déjà disponibles restent consultables" in markup
    assert "Tempo 03" in markup


@pytest.mark.parametrize("publication,expected", [(None, "Ce rapport ne renseigne pas l’état de publication"),
    ({"status": "published", "revision": 2}, ">Publié</span>"),
    ({"status": "not_published"}, ">Non publié</span>"),
    ("rolled_back", ">Publication annulée</span>")])
def test_publication_requires_explicit_state_and_never_uses_job_completion(publication, expected):
    report = dict(status="completed", publication=publication)
    markup = render_loop(report)
    publication_panel = markup.split('<div class="publication">', 1)[1].split('<article class="card">', 1)[0]
    assert expected in publication_panel
    assert "Traitement terminé" not in publication_panel


def test_every_untrusted_field_is_inert_even_inside_proofs_models_events_and_job_links(snapshot_report):
    attack = '\"><script>alert(1)</script><img src=x onerror=alert(2)><svg onload=alert(3)>&\''

    def poison(value):
        if isinstance(value, dict):
            return {key: poison(item) for key, item in value.items()}
        if isinstance(value, list):
            return [poison(item) for item in value]
        return attack if isinstance(value, str) else value

    data = poison(snapshot_report)
    data.update(error=attack, events=[dict(message=attack)], metrics={attack: attack},
                jobs=[dict(id=attack, status=attack, error=attack, updated=attack)])
    markup = render_loop(data)
    assert attack not in markup
    assert escape(attack, quote=True) in markup
    page = Page(markup)
    assert not any(tag in {"script", "img", "svg", "iframe", "object", "embed"} for tag, _ in page.tags)
    for tag, attrs in page.tags:
        assert not any(key.startswith("on") for key in attrs)
        if "href" in attrs:
            assert attrs["href"].startswith(("#", "/jobs/"))
            assert "<" not in attrs["href"] and '"' not in attrs["href"]


def test_local_job_navigation_has_real_safe_links_and_current_job():
    markup = render_loop(dict(id="job-1", jobs=[dict(id="job-1", status="completed", stage="done", updated="2026-11-27"),
        dict(id="job/2?x#y", status="failed", stage="extract", error="Source manquante"), dict(id="..", status="queued")]))
    links = {attrs["href"]: attrs for tag, attrs in Page(markup).tags if tag == "a"}
    assert links["/jobs/job-1"]["aria-current"] == "page"
    assert "/jobs/job%2F2%3Fx%23y" in links
    assert "/jobs/.." not in links
    assert "Source manquante" in markup and "2026-11-27" in markup


def test_keyed_checkpoint_shapes_extra_fields_and_immutability(snapshot_report):
    snapshot_report["benchmark"] = dict(candidates={"insole": {"label": "Semelle", "demand_events": 0}})
    snapshot_report.pop("candidates")
    snapshot_report["extractions"] = {"insole": {"status": "needs_extraction", "assignments": [], "routing": None}}
    snapshot_report["projection"] = {"summary": {"status": "backlog"}, "future_field": {"meaning": "preserved"}}
    snapshot_report["future_field"] = ["also preserved"]
    original = deepcopy(snapshot_report)
    markup = render_loop(snapshot_report)
    assert render_loop(snapshot_report) == markup
    assert snapshot_report == original
    assert "Semelle" in markup and "Besoin conservé · aucune valeur produit disponible" in markup
    assert "Besoins en attente" in markup
    assert "also preserved" in markup


def test_optional_geometry_is_unavailable_without_vectors_and_never_fakes_a_chart():
    assert "Diagnostic géométrique facultatif" not in render_loop({})
    markup = render_loop(dict(geometry=[dict(candidate_key="insole", status="not_available",
        reason="candidate_missing_embedding", points=[], metrics=dict(embedding_calls=0, external_calls=0))]))
    assert "Diagnostic indisponible" in markup
    assert "Aucun vecteur fourni pour ce besoin" in markup
    assert "Aucun résultat géométrique exploitable" in markup
    assert "ne modifie pas le routage" in markup
    assert not any(tag in {"svg", "canvas", "img"} for tag, _ in Page(markup).tags)
    assert '<details><summary>Diagnostic géométrique facultatif</summary>' in markup


def test_supplied_geometry_displays_only_reported_scope_and_counts():
    markup = render_loop(dict(geometry=[dict(candidate_key="insole", status="available",
        scope=dict(eligible_record_count=21, landmark_count=9),
        metrics=dict(pairwise_distance_evaluations=36, external_calls=0),
        persistence=dict(method="zero_dimensional_mst"))]))
    assert "Diagnostic disponible" in markup
    assert "Sources repères examinées" in markup
    assert ">9</dd>" in markup and ">21</dd>" in markup and ">36</dd>" in markup
    assert "ne mesure pas la précision" in markup


def test_real_offline_demo_new_source_changes_proposal_but_preserves_unknown_needs():
    from pilon.loop.benchmark import benchmark
    from pilon.loop.demo import inputs
    from pilon.loop.extraction import extract
    from pilon.loop.projection import build_projection

    pages = []
    for with_new_source in (False, True):
        model, records = inputs(with_new_source=with_new_source)
        candidates = benchmark(model, records)["candidates"]
        extractions = [extract(c, records, model) for c in candidates if c["gap_type"] != "unresolved_intent"]
        projection = build_projection(model, candidates, extractions)
        markup = render_loop(dict(model=model, candidates=candidates, extractions=extractions,
                                  projection=projection, synthetic=True))
        assert "Intention à qualifier" in markup
        assert "Adaptateur explicite requis pour cette source" in markup
        assert "Produits non analysés ou partiellement analysés" in markup
        pages.append(Page(markup))
    first_schema = {row[0] for row in pages[0].table_named("Schéma")}
    second_schema = {row[0] for row in pages[1].table_named("Schéma")}
    assert "removable_insole" not in first_schema
    assert "removable_insole" in second_schema
    new_rows = [row for row in pages[1].table_named("Affectations") if "removable_insole" in row[0]]
    assert new_rows and "Removable insole: yes" in new_rows[0][2]
