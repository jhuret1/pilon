"""Offline integration regressions for the Benchmark-to-enrichment handoff."""
from copy import deepcopy
import csv
from hashlib import sha256

import pytest

from pilon import home_depot_assets
from pilon.loop.app import create_app
from pilon.loop.enrichment import prepare_enrichment
from pilon.loop.semantic import annotate_records
from pilon.loop.store import Queue, fingerprint
from pilon.loop.worker import report, run_once
from pilon.loop.workspace import render_workspace


def reviewed_parent(queue, *, category='Tools', count=1, audited=False):
    model = dict(category=category, assessment_scope='schema_only',
                 observation_period='unknown', categories=[], assignments=[],
                 facets=[dict(key='Power_Mode', label='Power mode', values=['corded'])])
    records = [dict(id='q1', role='demand', source='search', category=category,
                    text='cordless drill', count=count)]
    reviews = [dict(record_id='q1', interpretation='A cordless drill', criteria=[dict(
        label='Power mode', value='cordless', assessment='value_gap', fact_key='Power_Mode',
        quote='cordless', start=0, end=8, rationale='Value not in the observed domain.',
        category_refs=[])])]
    records = annotate_records(model, records, reviews)
    options = dict(through='benchmark')
    if audited:
        options['audit'] = dict(model_hash=fingerprint(model),
            demand_hash=fingerprint([['q1', 'cordless drill']]), reviewed_record_ids=['q1'],
            sample_size=1, method='Local review', findings=[])
    parent = queue.enqueue(model, records, options=options)
    result = run_once(queue, job_id=parent)
    return parent, result['candidates'][0]['key']


def product(**overrides):
    return dict(dict(id='p1', role='catalog', source='description', category='Tools',
                     product_id='drill-1', text='Power mode: cordless'), **overrides)


@pytest.mark.parametrize('gap', ['schema_gap', 'coverage_gap'])
def test_default_benchmark_candidates_can_be_handed_off(tmp_path, gap):
    queue = Queue(tmp_path / 'jobs.sqlite')
    model = dict(category='Tools', observation_period='unknown', assignments=[],
                 facets=[] if gap == 'schema_gap' else [dict(key='power_mode', label='Power mode')])
    records = [dict(id='q1', role='demand', source='search', category='Tools',
                    text='filter by Power mode')]
    parent = queue.enqueue(model, records, options=dict(through='benchmark'))
    before = run_once(queue, job_id=parent)
    candidate = before['candidates'][0]
    assert candidate['gap_type'] == gap
    child = prepare_enrichment(queue, parent, [candidate['key']], [product()])
    result = run_once(queue, job_id=child)
    assert result['projection']['assignment_changes'][0]['fact_key'] == 'power_mode'


def test_enrichment_preserves_weighted_demand_events(tmp_path):
    queue = Queue(tmp_path / 'jobs.sqlite')
    parent, key = reviewed_parent(queue, count=23)
    child = prepare_enrichment(queue, parent, [key], [product()])
    result = run_once(queue, job_id=child)
    assert result['candidates'][0]['demand_events'] == 23


def test_existing_fact_id_and_reports_remain_detached(tmp_path):
    queue = Queue(tmp_path / 'jobs.sqlite')
    parent, key = reviewed_parent(queue, audited=True)
    original = queue.get(parent)
    catalog = [product()]
    child = prepare_enrichment(queue, parent, [key], catalog)
    catalog[0]['text'] = 'changed by caller'
    result = run_once(queue, job_id=child)
    projected = result['projection']['projected_model']
    assert len(projected['facets']) == 1
    assert projected['facets'][0]['key'] == 'Power_Mode'
    assert projected['assignments'][0]['fact_key'] == 'Power_Mode'
    result['projection']['projected_model']['facets'].clear()
    report(queue, parent)['benchmark']['audit']['findings'].append({'mutated': True})
    assert queue.get(parent) == original
    assert len(report(queue, child)['projection']['projected_model']['facets']) == 1


@pytest.mark.parametrize('invalid', ['quote', 'product_id', 'record_id', 'source'])
def test_product_annotations_require_exact_source_identity(tmp_path, invalid):
    queue = Queue(tmp_path / 'jobs.sqlite')
    parent, key = reviewed_parent(queue)
    annotation = dict(label='Power mode', value='cordless', quote='cordless', start=12, end=20,
                      product_id='drill-1', record_id='p1', source='description')
    annotation[invalid] = 'wrong'
    child = prepare_enrichment(queue, parent, [key], [product(extractions=[annotation])])
    with pytest.raises(ValueError):
        run_once(queue, job_id=child)
    assert queue.get(child)['result'] is None


def write_descriptions(path, text='Power mode: cordless'):
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['product_uid', 'product_description'])
        writer.writerow(['1', text])
        writer.writerow(['2', 'A red planter'])


def test_route_manifest_survives_enrichment_into_visible_counts(tmp_path):
    csv_path, index = tmp_path / 'sources.csv', tmp_path / 'sources.sqlite'
    write_descriptions(csv_path)
    home_depot_assets.index_descriptions(csv_path, index)
    records, routing = home_depot_assets.route_assets(index, ['cordless'], limit=1)
    queue = Queue(tmp_path / 'jobs.sqlite')
    parent, key = reviewed_parent(queue, category='Home Depot')
    child = prepare_enrichment(queue, parent, [key], records, routing=routing)
    result = run_once(queue, job_id=child)
    assert result['extractions'][0]['unknown_products'] == []
    main = render_workspace(result).split('<section id="snapshot">', 1)[0]
    assert '<dt>Unassessed outside shortlist</dt><dd>1</dd>' in main


def test_index_fingerprint_matches_bytes_actually_indexed(tmp_path, monkeypatch):
    csv_path, index = tmp_path / 'sources.csv', tmp_path / 'sources.sqlite'
    write_descriptions(csv_path, 'Old description')
    original_hash = home_depot_assets._hash

    def replace_after_fingerprint(path):
        digest = original_hash(path)
        write_descriptions(csv_path, 'Replacement description')
        return digest

    monkeypatch.setattr(home_depot_assets, '_hash', replace_after_fingerprint)
    try:
        manifest = home_depot_assets.index_descriptions(csv_path, index)
    except ValueError:
        assert not index.exists()
        return
    records, _ = home_depot_assets.route_assets(index, ['Replacement'])
    assert records[0]['text'] == 'Replacement description'
    assert manifest['source_sha256'] == sha256(csv_path.read_bytes()).hexdigest()


def test_asset_index_can_be_routed_under_a_hash_named_directory(tmp_path):
    directory = tmp_path / 'assets#1'
    directory.mkdir()
    csv_path, index = directory / 'sources.csv', directory / 'sources.sqlite'
    write_descriptions(csv_path)
    home_depot_assets.index_descriptions(csv_path, index)
    try:
        records, _ = home_depot_assets.route_assets(index, ['cordless'])
    finally:
        assert not (tmp_path / 'assets').exists(), 'Read-only routing created an unintended database'
    assert len(records) == 1


def test_workspace_routes_remain_read_only_for_all_methods(tmp_path):
    queue = Queue(tmp_path / 'jobs.sqlite')
    parent, key = reviewed_parent(queue)
    child = prepare_enrichment(queue, parent, [key], [product()])
    before = deepcopy(queue.get(child))
    app = create_app(queue)
    for route in ('extract', 'induct'):
        for method in ('GET', 'HEAD', 'POST', 'PUT', 'DELETE'):
            response = {}
            body = b''.join(app(dict(PATH_INFO='/' + route + '/' + child,
                                    REQUEST_METHOD=method, HTTP_HOST='127.0.0.1:8473'),
                               lambda status, headers: response.update(status=status)))
            assert response['status'] == ('200 OK' if method in ('GET', 'HEAD') else '405 Method Not Allowed')
            if method == 'HEAD':
                assert body == b''
    assert queue.get(child) == before
