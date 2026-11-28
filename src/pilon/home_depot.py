"""Local Home Depot schema and distinct-query import, without judged products.

Only train.csv (id/search_term) and attributes.csv (name/value) are consumed.
BulletNN attributes are unstructured product assets, not facetable domains.
Product descriptions, titles, and bullets remain in the raw corpus for a separate
optional Extract import. No network, credentials, labels, taxonomy inference,
or product/query joins are involved here. Observed domains are not exhaustive.
"""

import codecs
from collections import Counter
from contextlib import closing, contextmanager
import csv
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from threading import RLock


FORMAT_VERSION = 1
DEFAULT_SEED = 'pilon-home-depot-v1'
DATASET = 'Home Depot'
_EXPORTS = {'model.json', 'queries.jsonl'}
_REQUIRED = {'train.csv': ('id', 'search_term'),
             'attributes.csv': ('product_uid', 'name', 'value')}
_BULLET = re.compile(r'Bullet\d+', re.IGNORECASE)
_BULLET_REASON = ('BulletNN fields are unstructured product text reserved for optional '
                  'Extract assets; they are not structured attribute value domains.')
_CSV_LIMIT_LOCK = RLock()


def _validate_sample(sample_size, seed):
    if type(sample_size) is not int or sample_size < 1:
        raise ValueError('sample_size must be a positive integer')
    if not isinstance(seed, str) or not seed:
        raise ValueError('seed must be a nonempty string')


def _digest_json(value):
    return sha256(json.dumps(value, ensure_ascii=False, separators=(',', ':'),
                             sort_keys=True).encode('utf-8')).hexdigest()


def _source_info(path):
    """Hash raw bytes and choose strict UTF-8 (with BOM) or lossless Latin-1."""
    digest, size = sha256(), 0
    decoder = codecs.getincrementaldecoder('utf-8-sig')('strict')
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
            size += len(chunk)
            if decoder is not None:
                try:
                    decoder.decode(chunk)
                except UnicodeDecodeError:
                    decoder = None
    if decoder is not None:
        try:
            decoder.decode(b'', final=True)
        except UnicodeDecodeError:
            decoder = None
    return dict(file=path.name, sha256=digest.hexdigest(), bytes=size,
                encoding='utf-8-sig' if decoder is not None else 'iso-8859-1')


@contextmanager
def _csv_field_capacity(size):
    # csv's default 128 KiB limit can reject otherwise valid quoted fields.
    # A decoded field cannot exceed the source byte count for these encodings.
    # Serialize our readers while temporarily changing this process-wide setting.
    with _CSV_LIMIT_LOCK:
        previous = csv.field_size_limit()
        try:
            csv.field_size_limit(max(previous, size))
            yield
        finally:
            csv.field_size_limit(previous)


def _csv_rows(path, source, stats):
    """Stream well-shaped rows; track malformed records without retaining cells.

    source_order is a zero-based CSV data-record attempt, including rejected and
    blank records. Physical line spans additionally disambiguate multiline cells.
    Syntax errors can consume multiple lines; no speculative row repair is made.
    """
    stats.update(rows_seen=0, valid_rows=0, malformed_rows=0, blank_rows=0,
                 wrong_column_count=0, csv_errors=0, malformed_examples=[])
    with _csv_field_capacity(source['bytes']), path.open(encoding=source['encoding'], newline='') as stream:
        reader = csv.reader(stream, strict=True)
        try:
            header = next(reader)
        except (StopIteration, csv.Error) as exc:
            raise ValueError('Missing or malformed CSV header: ' + path.name) from exc
        if (len(set(header)) != len(header) or any(not name.strip() for name in header)
                or not set(_REQUIRED[path.name]) <= set(header)):
            raise ValueError('Invalid or missing required CSV columns: ' + path.name)
        stats['columns'] = header
        while True:
            first_line = reader.line_num + 1
            reason = None
            try:
                values = next(reader)
            except StopIteration:
                break
            except csv.Error:
                values, reason = None, 'csv_errors'
            position = stats['rows_seen']
            stats['rows_seen'] += 1
            if reason is None:
                if not values:
                    reason = 'blank_rows'
                elif len(values) != len(header):
                    reason = 'wrong_column_count'
            if reason:
                stats[reason] += 1
                stats['malformed_rows'] += 1
                if len(stats['malformed_examples']) < 20:
                    stats['malformed_examples'].append(dict(
                        source_order=position, line_start=first_line,
                        line_end=reader.line_num, reason=reason))
                continue
            stats['valid_rows'] += 1
            yield position, first_line, reader.line_num, dict(zip(header, values))
        stats['physical_lines'] = reader.line_num


def schema_from_rows(rows):
    """Aggregate every valid labeled spec globally, excluding only BulletNN text.

    Product IDs never determine membership, scope, or query selection. Empty
    values still contribute a named key. Names and nonblank values keep their
    original spelling, whitespace, case, and units; no semantic merging occurs.
    """
    attributes, excluded = {}, Counter()
    scanned = invalid_names = empty_values = missing_product_ids = 0
    for row in rows:
        scanned += 1
        name, value = row.get('name', ''), row.get('value', '')
        if not row.get('product_uid', '').strip():
            missing_product_ids += 1
        if not isinstance(name, str) or not any(c.isalnum() for c in name):
            invalid_names += 1
            continue
        if _BULLET.fullmatch(name.strip()):
            excluded[name] += 1
            continue
        values = attributes.setdefault(name, set())
        if isinstance(value, str) and value.strip():
            values.add(value)
        else:
            empty_values += 1
    facets = [dict(key='home_depot_' + sha256(name.encode('utf-8')).hexdigest(),
                   label=name, definition='', scopes=[], scope_status='global',
                   values=sorted(values), value_scopes={},
                   values_status='observed_not_exhaustive',
                   schema_source='observed_attribute_names_and_values')
              for name, values in sorted(attributes.items())]
    model = dict(category=DATASET, category_role='dataset_label_not_product_category',
                 assessment_scope='schema_only', observation_period='unknown',
                 demand_unit='sampled_distinct_queries', facets=facets, categories=[],
                 category_paths=[], category_status='unavailable_not_supplied',
                 scope_status='global_observed_no_category_taxonomy', assignments=[],
                 schema_status='reconstructed_from_observed_structured_attributes_and_values')
    stats = dict(rows_streamed=scanned, attributes=len(facets), categories=0,
                 attribute_values=sum(len(f['values']) for f in facets),
                 invalid_attribute_names=invalid_names, empty_attribute_values=empty_values,
                 rows_without_product_uid=missing_product_ids,
                 excluded_unstructured_rows=sum(excluded.values()),
                 excluded_unstructured_names=sorted(excluded),
                 excluded_unstructured_counts=dict(sorted(excluded.items())),
                 exclusion_rationale=_BULLET_REASON, retained_product_records=0)
    return model, stats


def _sample_queries(rows, sample_size, seed):
    queries, ids = {}, {}
    stats = dict(valid_query_rows=0, empty_queries=0, missing_source_ids=0)
    for position, first_line, last_line, row in rows:
        text, source_id = row['search_term'], row['id']
        if not text.strip():
            stats['empty_queries'] += 1
            continue
        if not source_id.strip():
            stats['missing_source_ids'] += 1
            continue
        if source_id in ids and ids[source_id] != text:
            raise ValueError('Conflicting train.csv source ID: ' + source_id)
        ids[source_id] = text
        stats['valid_query_rows'] += 1
        queries.setdefault(text, []).append(dict(source_id=source_id, source_order=position,
                                                line_start=first_line, line_end=last_line))
    stats.update(distinct_queries=len(queries),
                 duplicate_query_rows=stats['valid_query_rows'] - len(queries))
    if len(queries) < sample_size:
        raise ValueError(f'Expected at least {sample_size} distinct nonempty queries; found {len(queries)}')
    selected = sorted(queries, key=lambda text: (_digest_json([seed, text]), text))[:sample_size]
    records = []
    for text in selected:
        origins = queries[text]
        records.append(dict(id='home_depot_query_' + sha256(text.encode('utf-8')).hexdigest(),
                            role='demand', source='home_depot_site_search', category=DATASET,
                            text=text, count=1, count_basis='one_sampled_distinct_query',
                            source_file='train.csv', source_order=origins[0]['source_order'],
                            source_id_kind='training_pair_row_id_not_query_id',
                            original_source_ids=[r['source_id'] for r in origins], source_rows=origins))
    return records, stats


def _sources(input_dir):
    sources = [_source_info(input_dir / name) for name in _REQUIRED]
    path = input_dir / 'source-manifest.json'
    provenance = None
    if path.exists():
        raw = path.read_bytes()
        try:
            supplied = json.loads(raw.decode('utf-8-sig'))
            entries = supplied['files']
            if not isinstance(entries, list) or any(not isinstance(e, dict) for e in entries):
                raise ValueError('files must be an array of objects')
            selected = {}
            for entry in entries:
                name = entry.get('file')
                if name in _REQUIRED:
                    if name in selected:
                        raise ValueError('Duplicate source declaration: ' + name)
                    selected[name] = entry
            for source in sources:
                entry = selected[source['file']]
                if entry.get('sha256') != source['sha256'] or entry.get('bytes') != source['bytes']:
                    raise ValueError('Source manifest hash/size mismatch: ' + source['file'])
            provenance = dict(file=path.name, sha256=sha256(raw).hexdigest(), bytes=len(raw),
                              validation='required_input_hashes_verified_locally',
                              upstream={k: supplied[k] for k in (
                                  'dataset', 'original_source', 'mirror_revision',
                                  'redistribution_license_verified', 'local_evaluation_only') if k in supplied},
                              files=[{k: selected[s['file']][k] for k in ('file', 'sha256', 'bytes', 'url')
                                      if k in selected[s['file']]} for s in sources])
        except (ValueError, KeyError, TypeError, UnicodeError) as exc:
            raise ValueError('Invalid source-manifest.json: ' + str(exc)) from exc
    return sources, provenance


def _cache_key(sources, provenance, sample_size, seed):
    return dict(format_version=FORMAT_VERSION, dataset=DATASET, sample_size=sample_size,
                seed=seed, sources=sources, source_manifest=provenance)


def _load_cache(root, expected):
    """Reject stale, partial, altered, or incompatible snapshots; never repair silently."""
    try:
        if (root / 'manifest.json').is_symlink():
            raise ValueError('Manifest must not be a symlink')
        manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
        if not isinstance(manifest, dict):
            raise ValueError('Manifest must be an object')
        if any(manifest.get(k) != v for k, v in expected.items()):
            raise ValueError('Input hashes, sampling configuration, or format changed')
        exports = manifest['exports']
        if not isinstance(exports, dict) or set(exports) != _EXPORTS:
            raise ValueError('Incomplete or unexpected exports')
        for name, digest in exports.items():
            if (root / name).is_symlink() or _source_info(root / name)['sha256'] != digest:
                raise ValueError('Changed or incomplete export: ' + name)
        with (root / 'model.json').open(encoding='utf-8') as stream:
            model = json.load(stream)
        with (root / 'queries.jsonl').open(encoding='utf-8') as stream:
            records = [json.loads(line) for line in stream]
        if (len(records) != expected['sample_size'] or manifest['queries'] != len(records)
                or len({r['text'] for r in records}) != len(records)
                or len({r['id'] for r in records}) != len(records)
                or model.get('assessment_scope') != 'schema_only'
                or model.get('categories') != [] or model.get('assignments') != []
                or model['provenance']['sources'] != expected['sources']
                or model['provenance']['source_manifest'] != expected['source_manifest']
                or manifest['sampling']['selected_texts_sha256'] != _digest_json([r['text'] for r in records])
                or manifest['attributes'] != len(model['facets'])
                or manifest['attribute_values'] != sum(len(f['values']) for f in model['facets'])):
            raise ValueError('Invalid cached schema or query sample')
        for flag in ('relevance_labels_used', 'query_product_associations_used',
                     'product_value_assignments_retained', 'category_taxonomy_available'):
            if manifest.get(flag) is not False or model['provenance'].get(flag) is not False:
                raise ValueError('Invalid cached provenance: ' + flag)
        record_fields = {'id', 'role', 'source', 'category', 'text', 'count', 'count_basis',
                         'source_file', 'source_order', 'source_id_kind', 'original_source_ids', 'source_rows'}
        for row in records:
            if (set(row) != record_fields or row['role'] != 'demand' or row['category'] != DATASET
                    or row['count'] != 1 or not row['text'].strip()
                    or row['id'] != 'home_depot_query_' + sha256(row['text'].encode('utf-8')).hexdigest()):
                raise ValueError('Invalid cached demand record')
        return model, records, manifest
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError('Invalid Home Depot cache; use a new or empty output directory: ' + str(exc)) from exc


def _write_json(path, objects, *, lines=False):
    """Stream UTF-8 bytes so the recorded hash matches exports on every platform."""
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True,
                               indent=None if lines else 2, allow_nan=False)
    digest = sha256()
    with path.open('wb') as stream:
        for obj in objects:
            for chunk in encoder.iterencode(obj):
                data = chunk.encode('utf-8')
                stream.write(data)
                digest.update(data)
            stream.write(b'\n')
            digest.update(b'\n')
        stream.flush()
        os.fsync(stream.fileno())
    return digest.hexdigest()


def _publish(root, model, records, manifest):
    """Publish a complete sibling directory in one rename, manifest included."""
    root.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.' + root.name + '-', dir=root.parent) as temporary:
        stage = Path(temporary) / 'snapshot'
        stage.mkdir()
        manifest['exports'] = {'model.json': _write_json(stage / 'model.json', [model]),
                               'queries.jsonl': _write_json(stage / 'queries.jsonl', records, lines=True)}
        _write_json(stage / 'manifest.json', [manifest])
        removed_empty = False
        if root.exists():
            # rmdir fails if another writer has populated the destination.
            root.rmdir()
            removed_empty = True
        try:
            os.replace(stage, root)
        except BaseException:
            if removed_empty and not root.exists():
                root.mkdir()
            raise


def import_home_depot(input_dir, output_dir, sample_size=1000, seed=DEFAULT_SEED):
    """Return (model, records, manifest) and atomically export a local snapshot.

    Exactly sample_size DISTINCT, nonempty, unmodified search_term strings are
    selected by ascending SHA-256 of compact UTF-8 JSON [seed, text]. Sample order
    and IDs are independent of pair-row order and repetition. All original row
    IDs/positions for selected strings survive separately as provenance; these
    are not query IDs or frequencies. Fewer distinct queries is an error.

    Reads all attributes.csv rows, excluding only malformed/unnamed specs and
    BulletNN free text. Empty scopes mean global observed domains, never product
    or category coverage. Optional product assets are deliberately not read.

    An existing snapshot is reused only after checking source bytes, optional
    source-manifest.json declarations, configuration, and every export hash.
    Invalid caches raise ValueError; use a new or empty output directory. No
    raw data, product instances, associations, or relevance scores are exported.
    """
    _validate_sample(sample_size, seed)
    input_dir, root = Path(input_dir), Path(output_dir)
    if root.is_symlink() or root.resolve() == input_dir.resolve():
        raise ValueError('Output must be a separate nonsymlink directory')
    sources, provenance = _sources(input_dir)
    expected = _cache_key(sources, provenance, sample_size, seed)
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        return _load_cache(root, expected)
    csv_stats = {name: {} for name in _REQUIRED}
    with closing(_csv_rows(input_dir / 'train.csv', sources[0], csv_stats['train.csv'])) as rows:
        records, query_stats = _sample_queries(rows, sample_size, seed)
    with closing(_csv_rows(input_dir / 'attributes.csv', sources[1], csv_stats['attributes.csv'])) as rows:
        model, schema_stats = schema_from_rows(row for _, _, _, row in rows)
    # Verify that files did not change between hashing and complete consumption.
    if _sources(input_dir) != (sources, provenance):
        raise ValueError('Home Depot input changed during import; retry with stable files')
    model.update(version='home-depot-schema-v1-' + _digest_json(sources[1])[:16],
                 provenance=dict(sources=sources, source_manifest=provenance,
                                 schema_population='all_attributes_rows_except_unstructured_bullets',
                                 official_production_ontology=False,
                                 relevance_labels_used=False, query_product_associations_used=False,
                                 product_value_assignments_retained=False,
                                 category_taxonomy_available=False,
                                 unstructured_attribute_exclusion=_BULLET_REASON))
    manifest = dict(**expected, queries=len(records), **schema_stats, query_stats=query_stats,
                    csv_stats=csv_stats, sampling=dict(
                        algorithm='sha256_compact_json_seed_and_exact_text_v1',
                        distinctness='exact_original_text_no_normalization',
                        order='ascending_sampling_hash_then_text',
                        source_order='zero_based_csv_data_record_attempt',
                        original_source_ids='train.csv pair row IDs, not query IDs or demand frequency',
                        selected_texts_sha256=_digest_json([r['text'] for r in records])),
                    relevance_labels_used=False, query_product_associations_used=False,
                    observed_value_domains_retained=True, product_value_assignments_retained=False,
                    query_dates_available=False, query_frequencies_available=False,
                    category_taxonomy_available=False, unstructured_product_text_retained=False,
                    optional_extract_sources_consumed=False, local_only=True,
                    limitations=[
                        'Observed structured values are not exhaustive or official allowed values.',
                        'No product category taxonomy or per-product coverage is supplied.',
                        'Training pair multiplicity is not customer query frequency.',
                        'Malformed CSV records are skipped and counted; no row repair is inferred.',
                        'BulletNN fields, titles, and descriptions belong to a separate optional Extract import.',
                        'Local source declarations are preserved, not remotely authenticated.'])
    _publish(root, model, records, manifest)
    return model, records, manifest
