from copy import deepcopy
import csv
from hashlib import sha256
import json
from pathlib import Path
import socket
import urllib.request

import pytest

from pilon import home_depot
from pilon.loop.benchmark import benchmark
from pilon.loop.semantic import annotate_records


TRAIN_HEADER = ['id', 'product_uid', 'product_title', 'search_term', 'relevance']
ATTRIBUTE_HEADER = ['product_uid', 'name', 'value']


def write_csv(path, header, rows, encoding='utf-8'):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding=encoding, newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)


def raw_corpus(root, queries=None, attributes=None, encoding='utf-8'):
    if queries is None:
        queries = ['color red', 'drill', 'sizes 2:1']
    rows = [[f'{i:05}', 'PRIVATE_PRODUCT', 'PRIVATE_TITLE', text, 'PRIVATE_LABEL']
            for i, text in enumerate(queries)]
    if attributes is None:
        attributes = [
            ['PRIVATE_PRODUCT', 'color', 'red'],
            ['UNMATCHED_PRODUCT', 'color', 'blue'],
            ['UNMATCHED_PRODUCT', 'sizes', '2:1'],
            ['ANOTHER_PRODUCT', 'Product Type', 'Drill'],
            ['ANOTHER_PRODUCT', 'Bullet01', 'PRIVATE_BULLET'],
        ]
    write_csv(root / 'train.csv', TRAIN_HEADER, rows, encoding)
    write_csv(root / 'attributes.csv', ATTRIBUTE_HEADER, attributes, encoding)
    return root


def load_fixture(tmp_path, **kwargs):
    return home_depot.import_home_depot(raw_corpus(tmp_path / 'raw'), tmp_path / 'out',
                                       sample_size=3, **kwargs)


def declare_sources(root):
    manifest = dict(dataset='Fixture', original_source='https://example.invalid/dataset',
                    mirror_revision='a' * 40, redistribution_license_verified=False,
                    local_evaluation_only=True, files=[])
    for name in ('train.csv', 'attributes.csv'):
        data = (root / name).read_bytes()
        manifest['files'].append(dict(file=name, sha256=sha256(data).hexdigest(), bytes=len(data),
                                     url='https://example.invalid/' + name))
    (root / 'source-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    return manifest


def test_default_sample_is_exactly_1000_distinct_strings_with_deterministic_bytes(tmp_path):
    queries = [f'customer query {i:04}' for i in range(1200)]
    raw = raw_corpus(tmp_path / 'raw', queries + queries[::3] + queries[:8] * 20)
    first = home_depot.import_home_depot(raw, tmp_path / 'one')
    second = home_depot.import_home_depot(raw, tmp_path / 'two')
    assert first == second
    model, records, manifest = first
    assert len(records) == len({r['text'] for r in records}) == 1000
    assert len({r['id'] for r in records}) == 1000
    expected = sorted(queries, key=lambda text: sha256(
        json.dumps([home_depot.DEFAULT_SEED, text], ensure_ascii=False,
                   separators=(',', ':'), sort_keys=True).encode('utf-8')).hexdigest())[:1000]
    assert [r['text'] for r in records] == expected
    assert manifest['query_stats']['distinct_queries'] == 1200
    assert all(r['count'] == 1 and r['count_basis'] == 'one_sampled_distinct_query' for r in records)
    assert set(manifest['exports']) == {'model.json', 'queries.jsonl'}
    for name in ('model.json', 'queries.jsonl', 'manifest.json'):
        assert (tmp_path / 'one' / name).read_bytes() == (tmp_path / 'two' / name).read_bytes()
    assert model['category_role'] == 'dataset_label_not_product_category'


def test_sample_membership_order_and_ids_ignore_pair_order_and_multiplicity(tmp_path):
    queries = [f'query {i}' for i in range(90)] + ['query 0'] * 30
    raw = raw_corpus(tmp_path / 'raw', queries)
    _, first, _ = home_depot.import_home_depot(raw, tmp_path / 'first', 40)
    with (raw / 'train.csv').open(newline='', encoding='utf-8') as stream:
        rows = list(csv.reader(stream))[1:]
    write_csv(raw / 'train.csv', TRAIN_HEADER, list(reversed(rows)))
    _, reordered, _ = home_depot.import_home_depot(raw, tmp_path / 'reordered', 40)
    assert [(r['id'], r['text']) for r in first] == [(r['id'], r['text']) for r in reordered]
    assert any(a['source_order'] != b['source_order'] for a, b in zip(first, reordered))
    for a, b in zip(first, reordered):
        assert sorted(a['original_source_ids']) == sorted(b['original_source_ids'])
        assert b['source_order'] == b['source_rows'][0]['source_order']
        assert [origin['source_id'] for origin in b['source_rows']] == b['original_source_ids']
        assert b['source_rows'] == sorted(b['source_rows'], key=lambda origin: origin['source_order'])
    write_csv(raw / 'train.csv', TRAIN_HEADER, rows + rows * 2)
    _, repeated, _ = home_depot.import_home_depot(raw, tmp_path / 'repeated', 40)
    assert [(r['id'], r['text']) for r in first] == [(r['id'], r['text']) for r in repeated]
    _, other_seed, _ = home_depot.import_home_depot(raw, tmp_path / 'other-seed', 40, 'another-seed')
    assert {r['text'] for r in first} != {r['text'] for r in other_seed}


@pytest.mark.parametrize('encoding', ['iso-8859-1', 'utf-8-sig'])
def test_preserves_exact_text_ids_whitespace_case_unicode_and_multiline_provenance(tmp_path, encoding):
    queries = [' Café? ', 'café?', 'Café?', 'line\nbreak', ' Café? ', 'NaN']
    raw = raw_corpus(tmp_path / 'raw', queries, [['1', 'Matière', 'Acier à 90°']], encoding)
    model, records, manifest = home_depot.import_home_depot(raw, tmp_path / 'out', 5)
    assert {r['text'] for r in records} == set(queries)
    assert model['facets'][0]['values'] == ['Acier à 90°']
    assert all(s['encoding'] == encoding for s in manifest['sources'])
    repeated = next(r for r in records if r['text'] == ' Café? ')
    assert repeated['original_source_ids'] == ['00000', '00004']
    assert repeated['source_order'] == 0
    assert repeated['source_rows'] == [
        dict(source_id='00000', source_order=0, line_start=2, line_end=2),
        dict(source_id='00004', source_order=4, line_start=7, line_end=7),
    ]
    multiline = next(r for r in records if r['text'] == 'line\nbreak')
    assert multiline['source_rows'][0] == dict(source_id='00003', source_order=3, line_start=5, line_end=6)
    assert all('date' not in r and 'query_class' not in r for r in records)
    assert all(r['source_id_kind'] == 'training_pair_row_id_not_query_id' for r in records)


def test_all_structured_attributes_survive_without_join_or_fabricated_categories(tmp_path):
    raw = raw_corpus(tmp_path / 'raw', ['color red'], [
        ['PRIVATE_PRODUCT', 'color', 'red'],
        ['UNMATCHED_PRODUCT', 'color', 'blue'],
        ['UNMATCHED_PRODUCT', 'Product Type', 'Drill'],
        ['', 'size', '2:1'],
        ['OTHER_PRODUCT', 'color', 'red'],
        ['OTHER_PRODUCT', 'empty domain', ' '],
        ['OTHER_PRODUCT', 'Original Value', '  Raw  Value  '],
        ['OTHER_PRODUCT', 'Category', 'Supplied attribute, not a taxonomy'],
        ['OTHER_PRODUCT', '', 'invalid'],
        ['OTHER_PRODUCT', '***', 'invalid'],
        *[['OTHER_PRODUCT', f'Bullet{i:02}', f'PRIVATE_BULLET_{i}'] for i in range(1, 23)],
        ['OTHER_PRODUCT', ' bullet03 ', 'PRIVATE_BULLET'],
        ['OTHER_PRODUCT', 'Bulletproof Rating', 'A genuine spec'],
    ])
    model, records, manifest = home_depot.import_home_depot(raw, tmp_path / 'out', 1)
    facets = {f['label']: f for f in model['facets']}
    assert facets['color']['values'] == ['blue', 'red']
    assert facets['Product Type']['values'] == ['Drill']
    assert facets['size']['values'] == ['2:1']
    assert facets['empty domain']['values'] == []
    assert facets['Original Value']['values'] == ['  Raw  Value  ']
    assert facets['Category']['values'] == ['Supplied attribute, not a taxonomy']
    assert facets['Bulletproof Rating']['values'] == ['A genuine spec']
    assert all(f['scopes'] == [] and f['value_scopes'] == {} for f in facets.values())
    assert all(f['values_status'] == 'observed_not_exhaustive' for f in facets.values())
    assert model['categories'] == model['category_paths'] == model['assignments'] == []
    assert model['category_status'] == 'unavailable_not_supplied'
    assert manifest['excluded_unstructured_rows'] == 23
    assert len(manifest['excluded_unstructured_names']) == 23
    assert manifest['excluded_unstructured_counts']['Bullet22'] == 1
    assert manifest['invalid_attribute_names'] == 2
    assert manifest['empty_attribute_values'] == 1
    assert manifest['rows_without_product_uid'] == 1
    assert manifest['rows_streamed'] == 34
    assert manifest['retained_product_records'] == 0
    assert 'PRIVATE' not in json.dumps([model, records, manifest])
    assert 'UNMATCHED_PRODUCT' not in json.dumps([model, records, manifest])


def test_labels_titles_and_product_associations_never_affect_benchmark(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Network and optional product assets must not be read')
    monkeypatch.setattr(urllib.request, 'urlopen', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    raw = raw_corpus(tmp_path / 'raw')
    for name in ('test.csv', 'product_descriptions.csv'):
        (raw / name).mkdir()  # Opening these as files would fail.
    model, records, manifest = home_depot.import_home_depot(raw, tmp_path / 'first', 3)
    before = deepcopy((model, records))
    result = benchmark(model, records)
    assert (model, records) == before
    assert result['metrics']['inventory_products'] is None
    assert next(r for r in result['already_represented'] if r.get('requested_value') == 'red')['value_status'] == 'observed_exact'
    write_csv(raw / 'train.csv', TRAIN_HEADER, [
        [f'{i:05}', f'CHANGED_PRODUCT_{i}', 'CHANGED_TITLE', text, 'CHANGED_RELEVANCE']
        for i, text in enumerate(['color red', 'drill', 'sizes 2:1'])])
    other_model, other_records, _ = home_depot.import_home_depot(raw, tmp_path / 'second', 3)
    assert other_model['facets'] == model['facets']
    assert other_records == records
    assert benchmark(other_model, other_records) == result
    assert not manifest['relevance_labels_used']
    assert not manifest['query_product_associations_used']
    assert not manifest['optional_extract_sources_consumed']
    assert not manifest['product_value_assignments_retained']
    assert 'CHANGED' not in json.dumps([other_model, other_records])


def test_global_value_domains_work_with_grounded_semantic_review(tmp_path):
    raw = raw_corpus(tmp_path / 'raw', ['color red'])
    model, records, _ = home_depot.import_home_depot(raw, tmp_path / 'out', 1)
    color = next(f for f in model['facets'] if f['label'] == 'color')
    reviews = [dict(record_id=records[0]['id'], interpretation='A red color is requested.', criteria=[
        dict(assessment='represented', label='color', start=0, end=9, quote='color red',
             fact_key=color['key'], matched_value='red', category_refs=[],
             rationale='The exact color value occurs in the global observed domain.')])]
    reviewed = annotate_records(model, records, reviews)
    result = benchmark(model, reviewed)
    assert result['analysis']['reviewed_records'] == 1
    assert result['already_represented'][0]['value_status'] == 'observed_semantic'
    assert result['metrics']['inventory_products'] is None


def test_csv_errors_empty_fields_and_source_positions_are_counted(tmp_path):
    raw = raw_corpus(tmp_path / 'raw')
    (raw / 'train.csv').write_text(
        'id,search_term\n1,first\n2,too,many\n3\n\n4,  \n,last\n5,"bad"tail\n6,last\n',
        encoding='utf-8')
    (raw / 'attributes.csv').write_text(
        'product_uid,name,value\np,color,red\np,color\np,extra,blue,unexpected\n\np,,value\np,size,\n',
        encoding='utf-8')
    model, records, manifest = home_depot.import_home_depot(raw, tmp_path / 'out', 2)
    train = manifest['csv_stats']['train.csv']
    assert train['rows_seen'] == 8
    assert train['valid_rows'] == 4
    assert train['malformed_rows'] == 4
    assert train['wrong_column_count'] == 2
    assert train['csv_errors'] == train['blank_rows'] == 1
    assert manifest['query_stats']['empty_queries'] == manifest['query_stats']['missing_source_ids'] == 1
    assert next(r for r in records if r['text'] == 'last')['source_order'] == 7
    assert all(set(e) == {'source_order', 'line_start', 'line_end', 'reason'} for e in train['malformed_examples'])
    attributes = manifest['csv_stats']['attributes.csv']
    assert attributes['malformed_rows'] == 3
    assert manifest['invalid_attribute_names'] == manifest['empty_attribute_values'] == 1
    assert {f['label'] for f in model['facets']} == {'color', 'size'}


def test_unterminated_csv_is_reported_without_fabricating_recovered_rows(tmp_path):
    raw = raw_corpus(tmp_path / 'raw')
    (raw / 'train.csv').write_text('id,search_term\n1,valid\n2,"unterminated\n3,not recovered\n', encoding='utf-8')
    _, records, manifest = home_depot.import_home_depot(raw, tmp_path / 'out', 1)
    assert [r['text'] for r in records] == ['valid']
    stats = manifest['csv_stats']['train.csv']
    assert stats['csv_errors'] == 1
    assert stats['malformed_examples'] == [dict(source_order=1, line_start=3, line_end=4, reason='csv_errors')]


def test_long_valid_fields_are_not_mistaken_for_malformed_csv_and_limit_is_restored(tmp_path):
    previous = csv.field_size_limit()
    value = 'x' * (previous + 100)
    raw = raw_corpus(tmp_path / 'raw', ['query'], [['1', 'Long specification', value]])
    model, _, manifest = home_depot.import_home_depot(raw, tmp_path / 'out', 1)
    assert model['facets'][0]['values'] == [value]
    assert manifest['csv_stats']['attributes.csv']['malformed_rows'] == 0
    assert csv.field_size_limit() == previous
    (raw / 'train.csv').write_text('wrong,header\n', encoding='utf-8')
    with pytest.raises(ValueError, match='CSV columns'):
        home_depot.import_home_depot(raw, tmp_path / 'other', 1)
    assert csv.field_size_limit() == previous


@pytest.mark.parametrize('name,header', [
    ('train.csv', ['search_term']), ('train.csv', ['id', 'id', 'search_term']),
    ('attributes.csv', ['product_uid', 'name']), ('attributes.csv', ['product_uid', 'name', 'value', '']),
])
def test_missing_or_duplicate_headers_are_fatal(tmp_path, name, header):
    raw = raw_corpus(tmp_path / 'raw')
    write_csv(raw / name, header, [])
    with pytest.raises(ValueError, match='CSV columns'):
        home_depot.import_home_depot(raw, tmp_path / 'out', 1)
    assert not (tmp_path / 'out').exists()


@pytest.mark.parametrize('sample_size', [0, -1, True, 1.5, '1000'])
def test_invalid_sample_size_rejected_before_io(tmp_path, sample_size):
    with pytest.raises(ValueError, match='positive integer'):
        home_depot.import_home_depot(tmp_path / 'missing', tmp_path / 'out', sample_size)


@pytest.mark.parametrize('seed', ['', None, 1])
def test_invalid_seed_rejected_before_io(tmp_path, seed):
    with pytest.raises(ValueError, match='seed'):
        home_depot.import_home_depot(tmp_path / 'missing', tmp_path / 'out', seed=seed)


def test_insufficient_distinct_queries_and_conflicting_ids_fail_without_export(tmp_path):
    raw = raw_corpus(tmp_path / 'raw', ['same'] * 1001)
    with pytest.raises(ValueError, match='1000 distinct.*found 1'):
        home_depot.import_home_depot(raw, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()
    write_csv(raw / 'train.csv', TRAIN_HEADER, [['001', 'a', 'x', 'first', '3'], ['001', 'b', 'y', 'second', '1']])
    with pytest.raises(ValueError, match='Conflicting train.csv source ID'):
        home_depot.import_home_depot(raw, tmp_path / 'out', 1)
    assert not (tmp_path / 'out').exists()


def test_verified_cache_reuse_and_local_source_manifest_provenance(tmp_path, monkeypatch):
    raw = raw_corpus(tmp_path / 'raw')
    upstream = declare_sources(raw)
    first = home_depot.import_home_depot(raw, tmp_path / 'out', 3)
    model, _, manifest = first
    assert manifest['source_manifest']['upstream']['mirror_revision'] == upstream['mirror_revision']
    assert manifest['source_manifest']['upstream']['redistribution_license_verified'] is False
    assert model['provenance']['source_manifest'] == manifest['source_manifest']
    for source in manifest['sources']:
        data = (raw / source['file']).read_bytes()
        assert source['sha256'] == sha256(data).hexdigest()
        assert source['bytes'] == len(data)
    for name, digest in manifest['exports'].items():
        assert sha256((tmp_path / 'out' / name).read_bytes()).hexdigest() == digest
    def forbidden(*args, **kwargs):
        raise AssertionError('Verified cache should not parse CSV again')
    monkeypatch.setattr(home_depot, '_csv_rows', forbidden)
    assert home_depot.import_home_depot(raw, tmp_path / 'out', 3) == first


@pytest.mark.parametrize('name', ['model.json', 'queries.jsonl', 'manifest.json'])
@pytest.mark.parametrize('operation', ['change', 'remove'])
def test_invalid_or_incomplete_cache_is_rejected_without_repair(tmp_path, name, operation):
    load_fixture(tmp_path)
    path = tmp_path / 'out' / name
    if operation == 'change':
        path.write_text('{}', encoding='utf-8')
    else:
        path.unlink()
    before = {p.name: p.read_bytes() for p in (tmp_path / 'out').iterdir()}
    with pytest.raises(ValueError, match='Invalid Home Depot cache'):
        home_depot.import_home_depot(tmp_path / 'raw', tmp_path / 'out', 3)
    assert before == {p.name: p.read_bytes() for p in (tmp_path / 'out').iterdir()}


@pytest.mark.parametrize('change', ['seed', 'sample_size', 'format', 'input', 'extra_export', 'source_manifest'])
def test_stale_or_unexpected_cache_identity_is_rejected(tmp_path, change):
    load_fixture(tmp_path)
    kwargs = dict(sample_size=3)
    path = tmp_path / 'out' / 'manifest.json'
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if change == 'seed':
        kwargs['seed'] = 'different'
    elif change == 'sample_size':
        kwargs['sample_size'] = 2
    elif change == 'format':
        manifest['format_version'] = 0
    elif change == 'extra_export':
        manifest['exports']['../unwanted.json'] = '0' * 64
    elif change == 'input':
        with (tmp_path / 'raw' / 'attributes.csv').open('a', encoding='utf-8') as stream:
            stream.write('other,color,green\n')
    else:
        declare_sources(tmp_path / 'raw')
    path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError, match='Invalid Home Depot cache'):
        home_depot.import_home_depot(tmp_path / 'raw', tmp_path / 'out', **kwargs)


def test_source_manifest_must_match_actual_inputs(tmp_path):
    raw = raw_corpus(tmp_path / 'raw')
    declare_sources(raw)
    with (raw / 'train.csv').open('a', encoding='utf-8') as stream:
        stream.write('99,p,title,new query,3\n')
    with pytest.raises(ValueError, match='source-manifest.json.*hash/size mismatch'):
        home_depot.import_home_depot(raw, tmp_path / 'out', 3)
    assert not (tmp_path / 'out').exists()


@pytest.mark.parametrize('change', ['sample_digest', 'provenance', 'attribute_count', 'record_role'])
def test_inconsistent_cache_metadata_or_product_records_are_rejected(tmp_path, change):
    load_fixture(tmp_path)
    path = tmp_path / 'out' / 'manifest.json'
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if change == 'sample_digest':
        manifest['sampling']['selected_texts_sha256'] = '0' * 64
    elif change == 'provenance':
        manifest['query_product_associations_used'] = True
    elif change == 'attribute_count':
        manifest['attributes'] += 1
    else:
        export = tmp_path / 'out' / 'queries.jsonl'
        records = [json.loads(line) for line in export.read_text(encoding='utf-8').splitlines()]
        records[0]['role'] = 'catalog'
        records[0]['product_id'] = 'FORBIDDEN_PRODUCT'
        data = ''.join(json.dumps(row) + '\n' for row in records).encode('utf-8')
        export.write_bytes(data)
        manifest['exports']['queries.jsonl'] = sha256(data).hexdigest()
    path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError, match='Invalid Home Depot cache'):
        home_depot.import_home_depot(tmp_path / 'raw', tmp_path / 'out', 3)


def test_changing_input_during_import_never_publishes_snapshot(tmp_path, monkeypatch):
    raw = raw_corpus(tmp_path / 'raw')
    original = home_depot.schema_from_rows
    def changing(rows):
        result = original(rows)
        with (raw / 'train.csv').open('a', encoding='utf-8') as stream:
            stream.write('99,p,title,new query,3\n')
        return result
    monkeypatch.setattr(home_depot, 'schema_from_rows', changing)
    with pytest.raises(ValueError, match='input changed during import'):
        home_depot.import_home_depot(raw, tmp_path / 'out', 3)
    assert not (tmp_path / 'out').exists()


@pytest.mark.parametrize('existing_empty', [False, True])
def test_atomic_publication_failure_cleans_stage_and_preserves_empty_destination(tmp_path, monkeypatch, existing_empty):
    raw = raw_corpus(tmp_path / 'raw')
    output = tmp_path / 'out'
    if existing_empty:
        output.mkdir()
    def fail_replace(source, destination):
        assert Path(source).is_dir()
        assert {p.name for p in Path(source).iterdir()} == {'model.json', 'queries.jsonl', 'manifest.json'}
        assert Path(destination) == output
        assert not output.exists()
        raise OSError('simulated publication failure')
    monkeypatch.setattr(home_depot.os, 'replace', fail_replace)
    with pytest.raises(OSError, match='simulated publication failure'):
        home_depot.import_home_depot(raw, output, 3)
    assert output.exists() == existing_empty
    assert not list(tmp_path.glob('.out-*'))
    if existing_empty:
        assert not list(output.iterdir())


def test_atomic_write_failure_does_not_publish_partial_exports(tmp_path, monkeypatch):
    raw = raw_corpus(tmp_path / 'raw')
    original = home_depot._write_json
    def fail_write(path, *args, **kwargs):
        if path.name == 'queries.jsonl':
            raise OSError('simulated write failure')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(home_depot, '_write_json', fail_write)
    with pytest.raises(OSError, match='simulated write failure'):
        home_depot.import_home_depot(raw, tmp_path / 'out', 3)
    assert not (tmp_path / 'out').exists()
    assert not list(tmp_path.glob('.out-*'))


def test_existing_empty_output_is_supported_but_raw_directory_cannot_be_output(tmp_path):
    raw = raw_corpus(tmp_path / 'raw')
    output = tmp_path / 'out'
    output.mkdir()
    assert len(home_depot.import_home_depot(raw, output, 3)[1]) == 3
    before = (raw / 'train.csv').read_bytes()
    with pytest.raises(ValueError, match='separate nonsymlink'):
        home_depot.import_home_depot(raw, raw, 3)
    assert (raw / 'train.csv').read_bytes() == before
