from copy import deepcopy
import csv
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import socket

import pytest

SPEC = importlib.util.spec_from_file_location(
    'home_depot_replay', Path(__file__).resolve().parents[1] / 'scripts/replay_home_depot.py')
replay_script = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay_script)

from pilon.home_depot import import_home_depot
from pilon.home_depot_assets import index_descriptions, route_assets
from pilon.loop.benchmark import benchmark
from pilon.loop.review_bundle import detach_reviews
from pilon.loop.semantic import annotate_records
from pilon.loop.store import Queue


def write_csv(path, header, rows):
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)


def detached_extraction(text, label, value, quote):
    start = text.index(quote)
    return dict(label=label, value=value, start=start, end=start+len(quote),
                quote_sha256=sha256(quote.encode('utf-8')).hexdigest())


@pytest.fixture
def local_example(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError('The replay must stay offline')
    monkeypatch.setattr(socket, 'create_connection', no_network)
    monkeypatch.setattr(socket.socket, 'connect', no_network)
    raw = tmp_path / 'raw'
    raw.mkdir()
    write_csv(raw / 'train.csv', ['id', 'search_term'],
              enumerate(['water lily', 'mountain laurel', 'citron', 'open house sign']))
    write_csv(raw / 'attributes.csv', ['product_uid', 'name', 'value'],
              [['unused-product-association', 'Botanical Name', 'Rose']])
    descriptions = {
        '1': '🌿 Nymphaea: a water lily. Open House',
        '2': 'Botanical Name: water lily',
        '3': 'Open House on the front.',
        '4': 'Unselected rose.',
    }
    write_csv(raw / 'product_descriptions.csv', ['product_uid', 'product_description'], descriptions.items())
    model, demands, _ = import_home_depot(raw, tmp_path / 'fixture-prepared', sample_size=4)
    botanical = model['facets'][0]['key']
    reviews = []
    for record in demands:
        text = record['text']
        criterion = dict(label='Botanical Name', value=text, assessment='value_gap',
            fact_key=botanical, quote=text, start=0, end=len(text),
            rationale='The supplied domain contains Rose only.', category_refs=[])
        if text == 'open house sign':
            criterion.update(label='Sign message', value='Open House', assessment='attribute_gap',
                             proposed_key='sign_message', rationale='Displayed sign text is not modeled.')
            del criterion['fact_key']
        reviews.append(dict(record_id=record['id'], interpretation=text, criteria=[criterion]))
    decisions = detach_reviews(model, demands, reviews)
    bp = benchmark(model, annotate_records(model, demands, reviews))
    by_value = {c['requested_value']:c for c in bp['candidates']}
    index = tmp_path / 'fixture-index.sqlite'
    index_descriptions(raw / 'product_descriptions.csv', index)
    groups, sources, records = [], {}, {}
    for name, phrases, value, target in [
        ('plants', ['water lily'], 'water lily', botanical),
        ('signs', ['Open House'], 'Open House', 'sign_message'),
    ]:
        selected, _ = route_assets(index, phrases, limit=10)
        groups.append(dict(name=name, phrases=phrases, limit=10,
            target_keys=[target], candidate_keys=[by_value[value]['key']],
            selected_record_ids=[r['id'] for r in selected]))
        for record in selected:
            records[record['id']] = record
            annotations = []
            if record['product_id'] == '1':
                annotations.append(detached_extraction(record['text'], 'Botanical Name', 'water lily', 'water lily'))
            if record['product_id'] in ('1', '3'):
                annotations.append(detached_extraction(record['text'], 'Sign message', 'Open House', 'Open House'))
            # Product 2 deliberately has no reviewed extraction despite its labeled text.
            sources[record['id']] = dict(id=record['id'], product_id=record['product_id'],
                content_sha256=record['content_sha256'], extractions=annotations)
    evidence = dict(schema_version=1, groups=groups, sources=list(sources.values()))
    decisions_path, evidence_path = tmp_path/'decisions.json', tmp_path/'evidence.json'
    decisions_path.write_text(json.dumps(decisions), encoding='utf-8')
    evidence_path.write_text(json.dumps(evidence), encoding='utf-8')
    return dict(raw=raw, output=tmp_path/'output', decisions_path=decisions_path,
        evidence_path=evidence_path, evidence=evidence, decisions=decisions,
        benchmark=bp, botanical=botanical, records=records, index=index)


def run_example(example, **kwargs):
    return replay_script.replay(example['raw'], example['output'],
        decisions_path=example['decisions_path'], evidence_path=example['evidence_path'], **kwargs)


def test_offline_csv_replay_preserves_exact_candidate_and_source_scope(local_example):
    example = local_example
    before = deepcopy(example['evidence'])
    summary = run_example(example, port=9137)
    assert summary['status'] == 'completed'
    assert summary['api_calls'] == 0 and not summary['independent_accuracy_evaluation']
    assert summary['selected_sources'] == 3 and summary['selected_candidates'] == 2
    assert summary['db'] == str(example['output']/'replay.sqlite')
    assert summary['benchmark_url'] == f"http://127.0.0.1:9137/jobs/{summary['benchmark_job']}#opportunities"
    assert summary['extract_url'] == f"http://127.0.0.1:9137/extract/{summary['enrichment_job']}"
    assert summary['induct_url'] == f"http://127.0.0.1:9137/induct/{summary['enrichment_job']}"
    queue = Queue(summary['db'])
    parent, child = queue.get(summary['benchmark_job']), queue.get(summary['enrichment_job'])
    assert parent['payload']['options'] == {'through':'benchmark'}
    assert parent['result']['benchmark']['analysis']['reviewed_criteria'] == 4
    assert len(parent['result']['candidates']) == 4  # Three proposals share Botanical Name.
    selected = {c['key']:c for c in child['result']['candidates']}
    assert set(selected) == {example['botanical'], 'sign_message'}
    assert selected[example['botanical']]['source_candidate_keys'] == before['groups'][0]['candidate_keys']
    assert selected[example['botanical']]['demand_events'] == 1
    for extraction in child['result']['extractions']:
        if extraction['candidate_key'] == example['botanical']:
            assert [a['product_id'] for a in extraction['assignments']] == ['1']
            assert extraction['unknown_products'] == ['2']
            proof = extraction['assignments'][0]['evidence'][0]
            assert proof['quote'] == 'water lily'
            assert proof['start'] == example['records'][proof['record_id']]['text'].index('water lily')
        else:
            assert {a['product_id'] for a in extraction['assignments']} == {'1', '3'}
            assert extraction['unknown_products'] == []
    assert child['result']['projection'] is not None
    assert all(not j['payload']['synthetic'] for j in (parent, child))
    assert example['evidence'] == before
    repeated = run_example(example, port=8473)
    assert (repeated['benchmark_job'], repeated['enrichment_job']) == (summary['benchmark_job'], summary['enrichment_job'])
    assert len(queue.jobs()) == 2


@pytest.mark.parametrize('change', ['negative_span', 'past_end', 'empty_span', 'boolean_span',
                                   'quote_hash', 'content_hash', 'product_id'])
def test_bad_source_spans_hashes_and_identity_fail_before_enrichment(local_example, change):
    example = local_example
    bundle = deepcopy(example['evidence'])
    source = next(s for s in bundle['sources'] if s['product_id'] == '1')
    extraction = source['extractions'][0]
    if change == 'negative_span': extraction['start'] = -1
    elif change == 'past_end': extraction['end'] = 10000
    elif change == 'empty_span': extraction['end'] = extraction['start']
    elif change == 'boolean_span': extraction['start'] = True
    elif change == 'quote_hash': extraction['quote_sha256'] = '0'*64
    elif change == 'content_hash': source['content_sha256'] = '0'*64
    else: source['product_id'] = 'wrong-product'
    example['evidence_path'].write_text(json.dumps(bundle), encoding='utf-8')
    with pytest.raises(ValueError, match='span|hash mismatch'):
        run_example(example)
    assert not (example['output']/'replay.sqlite').exists()


@pytest.mark.parametrize('change', ['ids', 'order', 'missing_source', 'extra_source', 'duplicate_source'])
def test_route_membership_must_match_bundle_exactly(local_example, change):
    example = local_example
    bundle = deepcopy(example['evidence'])
    if change == 'ids': bundle['groups'][0]['selected_record_ids'][0] = 'wrong-record'
    elif change == 'order': bundle['groups'][0]['selected_record_ids'].reverse()
    elif change == 'missing_source': bundle['sources'].pop()
    elif change == 'extra_source': bundle['sources'].append(dict(bundle['sources'][0], id='unselected'))
    else: bundle['sources'].append(deepcopy(bundle['sources'][0]))
    with pytest.raises(ValueError, match='shortlist|source|Source'):
        replay_script.route_evidence(example['index'], bundle)


@pytest.mark.parametrize('change', ['missing_key', 'wrong_target', 'extra_target', 'unresolved'])
def test_candidate_selection_rejects_wrong_ids_or_targets(local_example, change):
    example = local_example
    bp, groups = deepcopy(example['benchmark']), deepcopy(example['evidence']['groups'])
    _, manifests = replay_script.route_evidence(example['index'], example['evidence'])
    if change == 'missing_key': groups[0]['candidate_keys'] = ['review_nonexistent']
    elif change == 'wrong_target': groups[0]['target_keys'] = ['sign_message']
    elif change == 'extra_target': groups[0]['target_keys'].append('unused_target')
    else:
        next(c for c in bp['candidates'] if c['key'] == groups[0]['candidate_keys'][0])['gap_type'] = 'unresolved_intent'
    with pytest.raises(ValueError, match='candidate|Candidate|target'):
        replay_script.select_candidates(bp, groups, manifests)


def test_multiple_groups_union_sources_for_one_target_without_extra_candidates(local_example):
    example = local_example
    bundle = deepcopy(example['evidence'])
    group = deepcopy(bundle['groups'][0])
    group.update(name='plants-on-sign', phrases=['Open House'],
                 selected_record_ids=bundle['groups'][1]['selected_record_ids'])
    bundle['groups'].append(group)
    catalog, manifests = replay_script.route_evidence(example['index'], bundle)
    keys, routing = replay_script.select_candidates(example['benchmark'], bundle['groups'], manifests)
    assert len(keys) == 2 and len(catalog) == 3
    target = routing[example['botanical']]
    assert target['method'] == 'union_of_group_shortlists'
    assert set(target['selected_record_ids']) == {r['id'] for r in catalog}
    assert target['selected_assets'] == 3 and target['unassessed_outside_shortlist'] == 1


def test_changed_detached_demand_hash_is_rejected(local_example):
    example = local_example
    bundle = deepcopy(example['decisions'])
    bundle['reviews'][0]['criteria'][0]['quote_sha256'] = '0'*64
    example['decisions_path'].write_text(json.dumps(bundle), encoding='utf-8')
    with pytest.raises(ValueError, match='fingerprint mismatch'):
        run_example(example)


def test_cli_defaults_and_db_override(tmp_path, monkeypatch, capsys):
    calls = []
    def fake_replay(*args, **kwargs):
        calls.append((args, kwargs))
        return {'status':'completed'}
    monkeypatch.setattr(replay_script, 'replay', fake_replay)
    assert replay_script.main(['--input-dir', str(tmp_path)]) == 0
    assert calls[0] == ((tmp_path, Path('runtime/home-depot-example')), dict(db=None, port=8473))
    assert json.loads(capsys.readouterr().out)['status'] == 'completed'
    replay_script.main(['--input-dir', str(tmp_path), '--output-dir', str(tmp_path/'out'),
                        '--db', str(tmp_path/'custom.sqlite'), '--port', '9001'])
    assert calls[1][1] == dict(db=tmp_path/'custom.sqlite', port=9001)
    assert json.loads(capsys.readouterr().out)['status'] == 'completed'
