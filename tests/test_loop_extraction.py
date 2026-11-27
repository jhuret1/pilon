"""Safety and retrieval contracts for the offline background extractor."""

from copy import deepcopy
import json
import math

import pytest

from pilon.facets import Spec
from pilon.loop.extraction import extract


@pytest.fixture
def candidate():
    return dict(key="toe_box", label="Toe box", definition="Space for toes at the front of the shoe",
                aliases=["avant-pied", "puntera"], demand_events=3, demand_records=[],
                gap_type="schema_gap", status="needs_extraction")


@pytest.fixture
def model():
    return dict(category="shoes", existing_facets=["width"],
                aliases={"toe box": ["room for toes", "Zehenraum"]})


def source(identifier="r1", product="p1", text="Toe box: wide", **extra):
    return dict(id=identifier, product_id=product, category="shoes", role="catalog",
                source="merchant", text=text, **extra)


def annotation(text, label="Toe box", value="wide", start=0, end=None):
    end = len(text) if end is None else end
    return dict(char_interval=dict(start_pos=start, end_pos=end), extraction_text=text[start:end],
                attributes=dict(label=label, value=value))


def stable(result):
    result = deepcopy(result)
    result["metrics"].pop("elapsed_seconds")
    result["metrics"]["retrieval"].pop("elapsed_seconds")
    result["metrics"]["extraction"].pop("elapsed_seconds")
    return result


def assert_grounded(result):
    by_id = {row["id"]: row for row in result["source_records"]}
    groups = [(item["product_id"], item["evidence"]) for item in result["assignments"]]
    groups += [(item["product_id"], evidence) for item in result["conflicts"]
               for evidence in item["competing_values"].values()]
    for product, evidence in groups:
        for proof in evidence:
            row = by_id[proof["record_id"]]
            assert row["product_id"] == product == proof["product_id"]
            assert row["text"][proof["start"]:proof["end"]] == proof["quote"]
            assert row["source"] == proof["source"]
            assert row.get("asset_type", "text") == proof["asset_type"]
            assert proof["grounding_status"] == "exact_source_verified"


def test_explicit_negative_values_are_not_missing_or_normalized_away(candidate, model):
    rows = [source("no", "negative", "Toe box: not wide"),
            source("zero", "zero", "Toe box: 0"),
            source("false", "false", "Toe box: false"),
            source("minus", "minus", "Toe box: -1"),
            source("missing", "missing", "No toe box specification was supplied."),
            source("prose", "prose", "This is not a wide toe box."),
            source("yes", "positive", "Toe box: wide")]
    result = extract(candidate, rows, model)
    assert {item["product_id"]: item["value"] for item in result["assignments"]} == {
        "negative": "not wide", "zero": "0", "false": "false", "minus": "-1", "positive": "wide"}
    assert result["unknown_products"] == ["missing", "prose"]
    assert result["unanalysed_products"] == []
    assert result["status"] == "needs_review"
    assert result["semantic_validation"] == "not_performed"
    assert_grounded(result)


def test_negation_in_label_does_not_become_a_positive_fact(candidate, model):
    rows = [source(text="No toe box: wide\nNot Toe box: wide\nToe box lining: wide")]
    result = extract(candidate, rows, model)
    assert result["assignments"] == []
    assert result["unknown_products"] == ["p1"]
    assert result["metrics"]["extraction"]["analyzed_assets"] == 1
    assert result["metrics"]["extraction"]["matching_claims"] == 0


def test_role_category_and_label_scope_do_not_bleed_into_product_evidence(candidate, model):
    rows = [source("wrong-label", "p1", "Toe box details\nWidth: wide"),
            dict(source("other-category", "foreign"), category="boots"),
            dict(source("demand", "request"), role="demand"),
            dict(source("external", "review"), role="external")]
    result = extract(candidate, rows, model, exhaustive=True)
    assert result["assignments"] == []
    assert result["unknown_products"] == ["p1"]
    assert [row["id"] for row in result["source_records"]] == ["wrong-label"]
    assert {row["reason"] for row in result["routing"]["excluded"]} == {"not_catalog", "outside_category"}


def test_category_can_be_inferred_but_cannot_silently_mix_catalogs(candidate, model):
    assert extract(candidate, [source()])["assignments"][0]["value"] == "wide"
    rows = [source(), dict(source("boots"), category="boots")]
    with pytest.raises(ValueError, match="category is required"):
        extract(candidate, rows)
    with pytest.raises(ValueError, match="category must match"):
        extract(dict(candidate, category="boots"), rows, model)


def test_multilingual_aliases_and_unicode_spans(candidate, model):
    model["aliases"]["toe box"].append("足先の空間")
    rows = [source("fr", "fr", "Édition 🥾\nAvant-pied: large"),
            source("es", "es", "Puntera: amplia"),
            source("de", "de", "Zehenraum: breit"),
            source("ja", "ja", "足先の空間: 広い"),
            source("nfkc", "nfkc", "Ｔｏｅ box: roomy")]
    result = extract(candidate, rows, model)
    assert len(result["assignments"]) == 5
    assert_grounded(result)
    french = next(item for item in result["assignments"] if item["product_id"] == "fr")
    assert french["evidence"][0]["start"] == len("Édition 🥾\n")
    assert french["evidence"][0]["quote"] == "Avant-pied: large"


def test_alias_can_resolve_back_to_canonical_model_name(candidate, model):
    candidate.update(key="zehenraum", label="Zehenraum", aliases=[])
    result = extract(candidate, [source()], model)
    assert result["assignments"][0]["value"] == "wide"


def test_lexical_routing_does_not_use_substring_word_matches(candidate, model):
    result = extract(candidate, [source(text="Toe boxing: wide")], model)
    assert result["routing"]["selected"] == []
    assert result["routing"]["unselected"][0]["reason"] == "no_lexical_match"
    assert result["unknown_products"] == result["unanalysed_products"] == ["p1"]


def test_existing_annotations_route_by_label_but_remain_semantic_proposals(candidate, model):
    text = "Été. Room at the front."
    row = source(text=text, extractions=[annotation(text, start=5)],
                 asset_type="document", vendor_metadata={"unchanged": [1, {"language": "fr"}]})
    before = deepcopy((candidate, model, row))
    result = extract(candidate, [row], model)
    assert result["source_records"] == [row]
    assert result["assignments"][0]["value"] == "wide"
    proof = result["assignments"][0]["evidence"][0]
    assert proof["quote"] == "Room at the front."
    assert proof["extraction_method"] == "supplied_annotation"
    assert result["semantic_validation"] == "not_performed"
    assert (candidate, model, row) == before
    result["source_records"][0]["vendor_metadata"]["unchanged"].append(2)
    assert (candidate, model, row) == before
    assert_grounded(result)


@pytest.mark.parametrize("start,end,quote", [(-1, 5, "Toe b"), (0, 999, "Toe box: wide"),
    (3, 3, ""), (5, 3, ""), (False, 13, "Toe box: wide"), (0, True, "T"),
    (0.0, 13, "Toe box: wide"), (0, 13, "Toe box: WIDE"), (0, 13, None)])
def test_malformed_annotation_spans_fail_closed(candidate, model, start, end, quote):
    supplied = annotation("Toe box: wide")
    supplied.update(char_interval=dict(start_pos=start, end_pos=end), extraction_text=quote)
    with pytest.raises(ValueError, match="Unverified source quotation"):
        extract(candidate, [source(extractions=[supplied])], model)


@pytest.mark.parametrize("bad", [None, {}, "Toe box: wide", [None], [{"attributes": {}}]])
def test_malformed_annotation_containers_fail_closed(candidate, model, bad):
    with pytest.raises(ValueError):
        extract(candidate, [source(extractions=bad)], model)


def test_changed_original_text_invalidates_precomputed_annotations(candidate, model):
    supplied = annotation("Toe box: wide")
    with pytest.raises(ValueError, match="Unverified source quotation"):
        extract(candidate, [source(text="Toe box: slim", extractions=[supplied])], model)


def test_supplied_annotations_replace_labeled_default_and_empty_is_not_absence(candidate, model):
    result = extract(candidate, [source(extractions=[])], model)
    assert result["assignments"] == []
    assert result["unknown_products"] == ["p1"]
    assert result["status"] == "needs_extraction"


def test_conflicting_values_keep_every_source_and_never_choose_a_winner(candidate, model):
    rows = [source("a", "conflict", "Toe box: wide"),
            source("b", "conflict", "Toe box: not wide"),
            source("c", "conflict", "Toe box: wide"),
            source("d", "ok", "Toe box: tapered"),
            source("e", "unknown", "Width: wide")]
    result = extract(candidate, rows, model, exhaustive=True)
    assert [item["product_id"] for item in result["assignments"]] == ["ok"]
    conflict, = result["conflicts"]
    assert conflict["product_id"] == "conflict"
    assert set(conflict["competing_values"]) == {"wide", "not wide"}
    assert [e["record_id"] for e in conflict["competing_values"]["wide"]] == ["a", "c"]
    assert result["unknown_products"] == ["unknown"]
    assert_grounded(result)


def test_two_conflicting_claims_in_one_asset_are_not_overwritten(candidate, model):
    result = extract(candidate, [source(text="Toe box: yes\nToe box: no")], model)
    assert result["assignments"] == []
    assert set(result["conflicts"][0]["competing_values"]) == {"yes", "no"}
    assert_grounded(result)


def test_duplicate_records_and_duplicate_annotations_do_not_duplicate_evidence(candidate, model):
    supplied = annotation("Toe box: wide")
    row = source(extractions=[supplied, supplied])
    result = extract(candidate, [row, deepcopy(row)], model)
    assert len(result["source_records"]) == 1
    assert len(result["assignments"][0]["evidence"]) == 1
    assert result["metrics"]["extraction"]["evidence_count"] == 1
    with pytest.raises(ValueError, match="Conflicting records"):
        extract(candidate, [row, dict(row, text="Toe box: tapered")], model)


def test_budget_is_per_asset_deterministic_and_partial_products_remain_unanalysed(candidate, model):
    rows = [source("c", "unknown"), source("b", "partial", "Toe box: no"), source("a", "partial")]
    result = extract(candidate, rows, model, top_k=1)
    assert [item["record_id"] for item in result["routing"]["selected"]] == ["a"]
    assert result["unknown_products"] == ["unknown"]
    assert result["unanalysed_products"] == ["partial", "unknown"]
    assert result["conflicts"] == []
    assert result["routing"]["truncated"] is True
    assert all(item["reason"] == "budget_limit" and item["analysis_status"] == "unanalysed"
               for item in result["routing"]["unselected"])
    assert result["metrics"]["retrieval"]["budget_skipped_assets"] == 2
    assert stable(result) == stable(extract(candidate, list(reversed(rows)), model, top_k=1))
    assert_grounded(result)


def test_zero_budget_does_not_invoke_extractor_or_validate_unanalysed_annotations(candidate, model):
    def unexpected(*args):
        pytest.fail("No source should be extracted at a zero budget")

    result = extract(candidate, [source(extractions=[{"attributes": {"label": "Toe box"}}])],
                     model, top_k=0, extractor=unexpected)
    assert result["status"] == "needs_extraction"
    assert result["source_records"] == result["assignments"] == []
    assert result["unknown_products"] == result["unanalysed_products"] == ["p1"]
    assert result["metrics"]["extraction"]["analyzed_assets"] == 0


@pytest.mark.parametrize("budget", [-1, 1.5, True, None, "2"])
def test_invalid_budgets_fail_early(candidate, budget):
    with pytest.raises(ValueError, match="top_k"):
        extract(candidate, [], top_k=budget)


def test_exhaustive_ignores_budget_and_retrieval_callback_for_benchmark(candidate, model):
    rows = [source("a", "p1"), source("b", "p2", "Width: standard"),
            source("c", "p3", "Toe box: wide", asset_type="image")]

    def unexpected(*args):
        pytest.fail("Exhaustive extraction must not call the embedding provider")

    result = extract(candidate, rows, model, top_k=0, exhaustive=True, embedding_provider=unexpected)
    assert [item["record_id"] for item in result["routing"]["selected"]] == ["a", "b"]
    assert result["routing"]["method"] == "exhaustive"
    assert result["routing"]["truncated"] is False
    assert result["metrics"]["retrieval"]["scored_assets"] == 0
    assert result["metrics"]["extraction"]["analyzed_assets"] == 2
    assert result["unknown_products"] == ["p2", "p3"]


def test_long_sources_are_not_truncated_and_late_proofs_retain_offsets(candidate, model):
    prefix = "Unrelated material. " * 20000 + "\n"
    row = source(text=prefix + "Toe box: wide")
    result = extract(candidate, [row], model)
    assert result["source_records"] == [row]
    proof = result["assignments"][0]["evidence"][0]
    assert proof["start"] == len(prefix)
    assert proof["end"] == len(row["text"])
    assert result["routing"]["truncated"] is False
    assert_grounded(result)


@pytest.mark.parametrize("asset_type", ["image", "audio", "video", "binary"])
def test_unsupported_modality_never_uses_labeled_text_or_annotations(candidate, model, asset_type):
    row = source(text="Toe box: wide", asset_type=asset_type,
                 extractions=[annotation("Toe box: wide")])
    result = extract(candidate, [row], model, exhaustive=True)
    assert result["assignments"] == result["source_records"] == []
    assert result["unknown_products"] == result["unanalysed_products"] == ["p1"]
    assert result["routing"]["unsupported"][0]["reason"] == "explicit_extractor_required"
    assert result["metrics"]["extraction"]["analyzed_assets"] == 0


def test_blank_document_is_unsupported_and_image_filename_proves_nothing(candidate, model):
    rows = [source("document", "doc", "", asset_type="document"),
            source("image", "img", "wide-toe-box.jpg", asset_type="image")]
    result = extract(candidate, rows, model)
    assert result["assignments"] == []
    assert result["unknown_products"] == ["doc", "img"]
    assert len(result["routing"]["unsupported"]) == 2


def test_explicit_image_adapter_still_requires_original_text_provenance(candidate, model):
    row = source(text="OCR transcription: ample room for toes", asset_type="image")
    calls = []

    def adapter(fact, record):
        calls.append((fact["key"], record["asset_type"]))
        return [annotation(record["text"], value="wide", start=19)]

    result = extract(candidate, [row], model, exhaustive=True, extractor=adapter)
    assert calls == [("toe_box", "image")]
    assert result["assignments"][0]["evidence"][0]["asset_type"] == "image"
    assert result["semantic_validation"] == "not_performed"
    assert_grounded(result)
    with pytest.raises(ValueError, match="Unverified source quotation"):
        extract(candidate, [source(text="", asset_type="image")], model, exhaustive=True,
                extractor=lambda fact, record: [annotation("Room for toes")])


def test_callback_receives_copies_and_cannot_rewrite_ground_truth(candidate, model):
    row = source()
    before = deepcopy((candidate, model, row))

    def adapter(fact, record):
        fact["aliases"].append("injected alias")
        record["source"] = "changed"
        return [Spec("Toe box", "wide", 0, len(record["text"]))]

    result = extract(candidate, [row], model, extractor=adapter)
    assert (candidate, model, row) == before
    assert result["source_records"] == [row]
    assert result["assignments"][0]["evidence"][0]["source"] == "merchant"
    assert_grounded(result)

    def rewritten(fact, record):
        record["text"] = "Toe box: slim"
        return [annotation(record["text"])]

    with pytest.raises(ValueError, match="Unverified source quotation"):
        extract(candidate, [row], model, extractor=rewritten)
    assert (candidate, model, row) == before


def test_flat_callback_annotations_validate_scope_and_quote(candidate, model):
    supplied = dict(label="Toe box", value="wide", start=0, end=13, quote="Toe box: wide",
                    record_id="r1", product_id="p1")
    result = extract(candidate, [source()], model, extractor=lambda fact, row: [supplied])
    assert_grounded(result)
    for field in ("product_id", "record_id"):
        bad = dict(supplied, **{field: "other"})
        with pytest.raises(ValueError, match=f"Wrong {field}"):
            extract(candidate, [source()], model, extractor=lambda fact, row: [bad])


def test_callback_label_must_match_candidate_even_when_quote_is_valid(candidate, model):
    result = extract(candidate, [source()], model,
                     extractor=lambda fact, row: [Spec("Width", "wide", 0, len(row["text"]))])
    assert result["assignments"] == []
    assert result["unknown_products"] == ["p1"]


def test_cosine_retrieval_uses_vectors_without_claiming_the_selected_text_is_true(candidate, model):
    candidate["embedding"] = [1, 0]
    rows = [source("a", "lexical", "Toe box: wide", embedding=[0, 1]),
            source("b", "semantic", "Unrelated sentence", embedding=[1, 0])]
    result = extract(candidate, rows, model, top_k=1)
    assert result["routing"]["method"] == "cosine"
    selected, = result["routing"]["selected"]
    assert selected["record_id"] == "b" and selected["score"] == pytest.approx(1)
    assert result["assignments"] == []
    assert result["unknown_products"] == ["lexical", "semantic"]
    assert result["unanalysed_products"] == ["lexical"]
    assert result["status"] == "needs_extraction"


def test_embedding_callback_uses_supplied_vectors_first_and_counts_actual_calls(candidate, model):
    candidate["embedding"] = [1, 0]
    rows = [source("a", "p1", embedding=[1, 0]), source("b", "p2", "Toe box: no")]
    calls = []

    def embed(text):
        calls.append(text)
        return [0, 1]

    result = extract(candidate, rows, model, embedding_provider=embed)
    assert calls == ["Toe box: no"]
    assert result["metrics"]["retrieval"]["embedding_calls"] == 1
    assert result["routing"]["method"] == "cosine"
    assert_grounded(result)


def test_embedding_provider_generates_candidate_and_asset_vectors_with_lexical_fallback(candidate, model):
    calls = []

    def embed(text):
        calls.append(text)
        return None if text == "Toe box: no" else [1, 2]

    rows = [source("b", "p2", "Toe box: no"), source("a", "p1")]
    result = extract(candidate, rows, model, embedding_provider=embed)
    assert candidate["definition"] in calls[0]
    assert calls[1:] == ["Toe box: wide", "Toe box: no"]
    assert result["routing"]["method"] == "cosine_then_lexical"
    assert [item["record_id"] for item in result["routing"]["selected"]] == ["a", "b"]
    assert result["metrics"]["retrieval"]["embedding_calls"] == 3


@pytest.mark.parametrize("bad", [[math.nan, 1], [math.inf, 1], [-math.inf, 1], [0, 0],
                                [], [True, 1], ["1", 0], "1,0", [10**400, 1]])
@pytest.mark.parametrize("location", ["candidate", "record", "provider"])
def test_invalid_vectors_are_rejected_instead_of_silently_scoring(candidate, model, bad, location):
    candidate["embedding"] = [1, 0]
    row = source(embedding=[1, 0])
    kwargs = {}
    if location == "candidate":
        candidate["embedding"] = bad
    elif location == "record":
        row["embedding"] = bad
    else:
        del row["embedding"]
        kwargs["embedding_provider"] = lambda text: bad
    with pytest.raises(ValueError, match="vector|finite"):
        extract(candidate, [row], model, **kwargs)


def test_dimension_mismatch_rejected_and_extreme_finite_vectors_are_stable(candidate, model):
    candidate["embedding"] = [1, 0]
    with pytest.raises(ValueError, match="dimensions must match"):
        extract(candidate, [source(embedding=[1])], model)
    for scale in (1e308, 1e-320):
        candidate["embedding"] = [scale, scale]
        result = extract(candidate, [source(embedding=[scale, scale])], model)
        assert result["routing"]["selected"][0]["score"] == pytest.approx(1.0)
        json.dumps(result, allow_nan=False)


@pytest.mark.parametrize('source_contract', [None, {'model':'different-model','dimensions':2},
                                          {'model':'same-model','dimensions':3}])
def test_declared_vector_spaces_must_match(candidate,model,source_contract):
    candidate.update(embedding=[1,0],embedding_contract={'model':'same-model','dimensions':2})
    row=source(embedding=[1,0],embedding_contract=source_contract)
    with pytest.raises(ValueError,match='contract'):
        extract(candidate,[row],model)


def test_matching_vector_contract_is_reported(candidate,model):
    contract={'model':'same-model','dimensions':2,'pooling':'mean'}
    candidate.update(embedding=[1,0],embedding_contract=contract)
    result=extract(candidate,[source(embedding=[1,0],embedding_contract=contract)],model)
    assert result['routing']['selected'][0]['embedding_contract_status']=='matched'


def test_no_sources_preserves_candidate_and_model_inventory_without_reusing_old_claims(candidate, model):
    model["assignments"] = [dict(product_id="existing", fact_key="toe_box", value="wide", evidence=[])]
    before = deepcopy((candidate, model))
    result = extract(candidate, [], model)
    assert result["candidate_key"] == candidate["key"]
    assert result["status"] == "needs_extraction"
    assert result["assignments"] == result["conflicts"] == result["source_records"] == []
    assert result["unknown_products"] == result["unanalysed_products"] == ["existing"]
    assert (candidate, model) == before
    assert extract(candidate, [dict(source(), role="demand")])["unknown_products"] == []
    assert extract(candidate, [])["status"] == "needs_extraction"


def test_output_schema_and_metrics_do_not_fabricate_recall_or_semantic_verification(candidate, model):
    result = extract(candidate, [source(), source("b", "p2", "Width: wide")], model)
    assert set(result) == {"candidate_key", "status", "assignments", "conflicts", "unknown_products",
                           "unanalysed_products", "source_records", "semantic_validation", "routing", "metrics"}
    metrics = result["metrics"]
    assert metrics["retrieval"]["selected_assets"] == metrics["extraction"]["analyzed_assets"] == 1
    assert metrics["retrieval"]["unselected_assets"] == 1
    assert metrics["extraction"]["assigned_products"] == 1
    assert metrics["extraction"]["unknown_products"] == 1
    assert metrics["elapsed_seconds"] >= metrics["retrieval"]["elapsed_seconds"] >= 0
    assert metrics["elapsed_seconds"] >= metrics["extraction"]["elapsed_seconds"] >= 0
    serialized = json.dumps(result, allow_nan=False)
    for unsupported_claim in ("recall", "savings", "semantic_verified", "ann", "tda"):
        assert unsupported_claim not in metrics
    assert "exact_source_verified" in serialized
