"""Replay supplied Home Depot decisions and evidence against local CSVs only.

Run from a checkout; no installation, downloads, provider calls or server startup
are needed. Public bundles contain hashes and offsets, never source quotations.
"""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from pilon.home_depot import import_home_depot
from pilon.home_depot_assets import index_descriptions, route_assets
from pilon.loop.enrichment import prepare_enrichment
from pilon.loop.review_bundle import attach_reviews, attach_audit
from pilon.loop.semantic import annotate_records
from pilon.loop.store import Queue
from pilon.loop.worker import run_once

DECISIONS = ROOT / 'docs/examples/home-depot-decisions.json'
EVIDENCE = ROOT / 'docs/examples/home-depot-evidence.json'
DEFAULT_OUTPUT = Path('runtime/home-depot-example')


def _strings(value, field, *, allow_empty=False):
    if (not isinstance(value, list) or (not value and not allow_empty)
            or any(not isinstance(item, str) or not item.strip() for item in value)
            or len(set(value)) != len(value)):
        raise ValueError(field + ' must contain distinct nonempty strings')
    return value


def _groups(bundle):
    if (not isinstance(bundle, dict) or type(bundle.get('schema_version')) is not int
            or bundle['schema_version'] != 1):
        raise ValueError('Unsupported Home Depot evidence schema_version')
    groups = bundle.get('groups')
    if not isinstance(groups, list) or not groups:
        raise ValueError('Evidence requires nonempty groups')
    names = set()
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError('Each evidence group must be an object')
        name = group.get('name')
        if not isinstance(name, str) or not name.strip() or name in names:
            raise ValueError('Evidence group names must be distinct and nonempty')
        names.add(name)
        for field in ('phrases', 'target_keys', 'candidate_keys', 'selected_record_ids'):
            _strings(group.get(field), name + '.' + field, allow_empty=field == 'selected_record_ids')
        limit = group.get('limit')
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError(name + ': limit must be between 1 and 500')
    return groups


def hydrate_source(record, source):
    """Attach only verified Python-character spans to an unchanged routed source."""
    rid = record['id']
    digest = sha256(record['text'].encode('utf-8')).hexdigest()
    if (source.get('id') != rid or source.get('product_id') != record['product_id']
            or source.get('content_sha256') != digest or record.get('content_sha256') != digest):
        raise ValueError('Source identity/content hash mismatch: ' + rid)
    extractions = source.get('extractions')
    if not isinstance(extractions, list):
        raise ValueError('Source requires an explicit extractions array: ' + rid)
    hydrated = []
    for extraction in extractions:
        if not isinstance(extraction, dict):
            raise ValueError('Invalid detached extraction: ' + rid)
        start, end = extraction.get('start'), extraction.get('end')
        if (type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(record['text'])):
            raise ValueError('Invalid detached extraction span: ' + rid)
        for field in ('label', 'value'):
            if not isinstance(extraction.get(field), str) or not extraction[field].strip():
                raise ValueError('Detached extraction requires ' + field + ': ' + rid)
        quote = record['text'][start:end]
        if sha256(quote.encode('utf-8')).hexdigest() != extraction.get('quote_sha256'):
            raise ValueError('Detached extraction quote hash mismatch: ' + rid)
        hydrated.append(dict(label=extraction['label'], value=extraction['value'],
                             start=start, end=end, quote=quote))
    # An explicit empty array also prevents fallback extraction from unreviewed text.
    return dict(deepcopy(record), extractions=hydrated)


def route_evidence(database, bundle):
    groups = _groups(bundle)
    sources = bundle.get('sources')
    if not isinstance(sources, list):
        raise ValueError('Evidence sources must be an array')
    by_id = {}
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError('Each detached source must be an object')
        rid = source.get('id')
        if not isinstance(rid, str) or not rid.strip() or rid in by_id:
            raise ValueError('Detached source IDs must be distinct and nonempty')
        by_id[rid] = source
    catalog, manifests = {}, {}
    for group in groups:
        records, manifest = route_assets(database, group['phrases'], limit=group['limit'])
        if [r['id'] for r in records] != group['selected_record_ids']:
            raise ValueError('Source shortlist mismatch: ' + group['name'])
        for record in records:
            if record['id'] not in by_id:
                raise ValueError('Missing detached source: ' + record['id'])
            hydrated = hydrate_source(record, by_id[record['id']])
            catalog.setdefault(record['id'], hydrated)
        # Timings must not create a different enrichment job on every local replay.
        manifests[group['name']] = {k:v for k,v in manifest.items() if k != 'elapsed_seconds'}
    if set(catalog) != set(by_id):
        raise ValueError('Detached sources must exactly match the union of group shortlists')
    if not catalog:
        raise ValueError('Evidence shortlists contain no product sources')
    return [catalog[rid] for rid in sorted(catalog)], manifests


def select_candidates(benchmark, groups, manifests):
    """Select exact reviewed IDs, never every proposal sharing an attribute."""
    available = {c['key']:c for c in benchmark['candidates']}
    selected, by_target = {}, {}
    for group in groups:
        targets = set()
        for key in group['candidate_keys']:
            if key not in available:
                raise ValueError('Unknown reviewed candidate: ' + key)
            candidate = available[key]
            if candidate['gap_type'] not in {'schema_gap', 'value_gap', 'filter_proposal', 'coverage_gap'}:
                raise ValueError('Candidate is not ready for enrichment: ' + key)
            # Match prepare_enrichment: a derived filter uses its proposed identity.
            target = candidate.get('fact_key') if candidate['gap_type'] != 'filter_proposal' else None
            target = target or candidate.get('proposed_key')
            if not target or target not in group['target_keys']:
                raise ValueError('Candidate target mismatch: ' + key)
            targets.add(target)
            selected[key] = None
        if targets != set(group['target_keys']):
            raise ValueError('Group targets must match its selected candidates: ' + group['name'])
        for target in sorted(targets):
            by_target.setdefault(target, []).append(dict(manifests[group['name']], group_name=group['name']))
    routing = {}
    for target, parts in by_target.items():
        if len(parts) == 1:
            routing[target] = parts[0]
            continue
        ids = list(dict.fromkeys(rid for part in parts for rid in part['selected_record_ids']))
        indexed = parts[0]['indexed_assets']
        routing[target] = dict(method='union_of_group_shortlists', groups=parts,
            selected_record_ids=ids, selected_assets=len(ids), indexed_assets=indexed,
            unassessed_outside_shortlist=indexed-len(ids), selection_recall='not_measured',
            source_sha256=parts[0]['source_sha256'])
    return list(selected), routing


def _completed(queue, job_id):
    run_once(queue, job_id=job_id)
    job = queue.get(job_id)
    if job['status'] != 'completed':
        raise ValueError('Replay job did not complete: ' + job_id + ' (' + job['status'] + ')')
    return job['result']


def replay(input_dir, output_dir=DEFAULT_OUTPUT, *, db=None, port=8473,
           decisions_path=DECISIONS, evidence_path=EVIDENCE):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Display port must be between 1 and 65535')
    input_dir, output_dir = Path(input_dir), Path(output_dir)
    decisions = json.loads(Path(decisions_path).read_text(encoding='utf-8'))
    evidence = json.loads(Path(evidence_path).read_text(encoding='utf-8'))
    groups = _groups(evidence)
    if not isinstance(decisions, dict) or not isinstance(decisions.get('reviews'), list) or not decisions['reviews']:
        raise ValueError('Detached decisions require nonempty reviews')
    model, records, _ = import_home_depot(input_dir, output_dir / 'prepared',
                                         sample_size=len(decisions['reviews']))
    records = annotate_records(model, records, attach_reviews(decisions, model, records))
    database = output_dir / 'descriptions.sqlite'
    index_descriptions(input_dir / 'product_descriptions.csv', database)
    catalog, manifests = route_evidence(database, evidence)
    db = Path(db) if db is not None else output_dir / 'replay.sqlite'
    queue = Queue(db)
    options = {'through':'benchmark'}
    if decisions.get('audit'):
        options['audit'] = attach_audit(decisions['audit'], model, records)
    parent = queue.enqueue(model, records, options=options, synthetic=False)
    benchmark = _completed(queue, parent)['benchmark']
    candidate_keys, routing = select_candidates(benchmark, groups, manifests)
    child = prepare_enrichment(queue, parent, candidate_keys, catalog, routing=routing)
    _completed(queue, child)
    base = 'http://127.0.0.1:' + str(port)
    return dict(output_dir=str(output_dir), db=str(db), queries=len(records),
        source_groups=len(groups), selected_sources=len(catalog), selected_candidates=len(candidate_keys),
        benchmark_job=parent, enrichment_job=child, status='completed',
        benchmark_url=base+'/jobs/'+parent+'#opportunities',
        extract_url=base+'/extract/'+child, induct_url=base+'/induct/'+child,
        api_calls=0, decision_origin='supplied_agent_review', independent_accuracy_evaluation=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, required=True,
                        help='Local directory containing train.csv, attributes.csv and product_descriptions.csv')
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--db', type=Path, help='Job database (default: OUTPUT_DIR/replay.sqlite)')
    parser.add_argument('--port', type=int, default=8473, help='Port in displayed URLs only; no server is started')
    args = parser.parse_args(argv)
    try:
        summary = replay(args.input_dir, args.output_dir, db=args.db, port=args.port)
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(2, 'Replay failed: ' + str(exc) + '\n')
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
