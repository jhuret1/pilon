"""Import real WANDS queries and an observed schema, without retaining products.

WANDS has no standalone business-model file. The product TSV is read once as a
stream; attribute names, observed values and their category scopes survive.
Descriptions, identifiers, associations and relevance labels are never exported.
Observed values are not an exhaustive or official allowed-value contract.
"""
import csv
from hashlib import sha256
import io
import json
from pathlib import Path
import re
import sys
import urllib.request

from .facets.io import write_text


REVISION = '3b74dcf4ba29ab8ff3e6a50b5b09fc627cb882b5'
FORMAT_VERSION = 3
REPOSITORY = 'https://github.com/wayfair/WANDS'


def schema_from_rows(rows):
    """Aggregate attribute/value domains by category, without product instances."""
    attributes, categories, hierarchy = {}, set(), set()
    scanned = invalid = 0
    for row in rows:
        scanned += 1
        row_categories = {c.strip() for c in row.get('product_class', '').split('|') if c.strip()}
        categories.update(row_categories)
        path = row.get('category hierarchy', row.get('category_hierarchy', '')).strip()
        if path:
            hierarchy.add(path)
        for item in row.get('product_features', '').split('|'):
            name, sep, value = item.partition(':')
            name = ' '.join(name.split())
            value = ' '.join(value.split())
            if not sep or not name or not re.search(r'\w', name):
                if item.strip():
                    invalid += 1
                continue
            attribute = attributes.setdefault(name, dict(scopes=set(), values={}))
            attribute['scopes'].update(row_categories)
            if value:
                scopes = attribute['values'].setdefault(value, set())
                scopes.update(row_categories)
    facets = [dict(key='wands_' + sha256(name.encode()).hexdigest()[:16], label=name,
                   definition='', scopes=sorted(attribute['scopes']),
                   values=sorted(attribute['values']),
                   value_scopes={value:sorted(scopes) for value, scopes in sorted(attribute['values'].items())},
                   values_status='observed_not_exhaustive',
                   schema_source='observed_attribute_names_and_values')
              for name, attribute in sorted(attributes.items())]
    return dict(category='WANDS', assessment_scope='schema_only', observation_period='unknown',
                demand_unit='sampled_queries', facets=facets, categories=sorted(categories),
                category_paths=sorted(hierarchy), assignments=[],
                schema_status='reconstructed_from_published_attributes_and_values'), dict(
                    rows_streamed=scanned, attributes=len(facets), categories=len(categories),
                    attribute_values=sum(len(f['values']) for f in facets),
                    ignored_malformed_attribute_fragments=invalid, retained_product_records=0)


def requests_from_rows(rows):
    records, ids = [], set()
    for position, row in enumerate(rows):
        rid, text = row.get('query_id', '').strip(), row.get('query', '')
        if not rid or not text.strip():
            raise ValueError('WANDS query requires an ID and nonempty original text')
        if rid in ids:
            raise ValueError('Duplicate WANDS query ID: ' + rid)
        ids.add(rid)
        records.append(dict(id='wands_query_' + rid, role='demand', source='wands_site_search',
                            category='WANDS', text=text, query_class=row.get('query_class', '').strip(),
                            count=1, count_basis='one_sampled_query', source_order=position,
                            original_query_id=rid))
    return records


class _HashingReader(io.RawIOBase):
    def __init__(self, response):
        self.response = response
        self.digest = sha256()
        self.size = 0

    def readable(self):
        return True

    def readinto(self, buffer):
        chunk = self.response.read(len(buffer))
        self.digest.update(chunk)
        self.size += len(chunk)
        buffer[:len(chunk)] = chunk
        return len(chunk)


def _read_remote(base, filename, consumer):
    url = base + '/' + filename
    request = urllib.request.Request(url, headers={'User-Agent': 'PILON-WANDS-schema-import/1'})
    with urllib.request.urlopen(request, timeout=60) as response:
        reader = _HashingReader(response)
        with io.TextIOWrapper(io.BufferedReader(reader), encoding='utf-8-sig', newline='') as stream:
            rows = csv.DictReader(stream, delimiter='\t')
            result = consumer(rows)
        return result, dict(url=url, sha256=reader.digest.hexdigest(), bytes_streamed=reader.size)


def import_wands(output_dir, *, revision=REVISION):
    """Network import with immutable revision and hash-verified local reuse."""
    if not re.fullmatch(r'[a-f0-9]{40}', revision):
        raise ValueError('WANDS revision must be a full commit hash')
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / 'manifest.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if manifest.get('format_version') != FORMAT_VERSION:
            raise ValueError('Use a new output directory to import the schema with observed values')
        if manifest.get('revision') != revision:
            raise ValueError('Use a new output directory for a different WANDS revision')
        if set(manifest['exports']) != {'model.json', 'queries.jsonl', 'LICENSE-WANDS.txt'}:
            raise ValueError('Incomplete cached WANDS exports')
        for name, expected in manifest['exports'].items():
            if name not in ('model.json', 'queries.jsonl', 'LICENSE-WANDS.txt'):
                raise ValueError('Unexpected cached WANDS export')
            if sha256((root/name).read_bytes()).hexdigest() != expected:
                raise ValueError('Changed or incomplete WANDS export: ' + name)
        model = json.loads((root/'model.json').read_text(encoding='utf-8'))
        records = [json.loads(line) for line in (root/'queries.jsonl').read_text(encoding='utf-8').splitlines()]
        return model, records, manifest
    base = f'https://raw.githubusercontent.com/wayfair/WANDS/{revision}'
    print('Reading WANDS requests...', file=sys.stderr, flush=True)
    records, query_source = _read_remote(base, 'dataset/query.csv', requests_from_rows)
    print('Reading attributes, observed values and category scopes; product rows are discarded...', file=sys.stderr, flush=True)
    (model, stats), product_source = _read_remote(base, 'dataset/product.csv', schema_from_rows)
    model.update(version='wands-schema-values-v3-' + revision[:12], provenance=dict(
        repository=REPOSITORY, revision=revision, query_source=query_source,
        schema_source=product_source, official_production_ontology=False,
        relevance_labels_used=False, query_product_associations_used=False))
    request = urllib.request.Request(base+'/LICENSE', headers={'User-Agent':'PILON-WANDS-schema-import/1'})
    with urllib.request.urlopen(request, timeout=30) as response:
        license_text = response.read().decode('utf-8')
    exports = {'model.json':json.dumps(model,ensure_ascii=False,indent=2)+'\n',
               'queries.jsonl':''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records),
               'LICENSE-WANDS.txt':license_text}
    for name, text in exports.items():
        write_text(root/name, text)
    manifest = dict(format_version=FORMAT_VERSION, dataset='WANDS', revision=revision, repository=REPOSITORY,
                    queries=len(records), **stats, relevance_labels_used=False,
                    query_product_associations_used=False, observed_value_domains_retained=True,
                    product_value_assignments_retained=False,
                    query_dates_available=False, query_frequencies_available=False,
                    sources=[query_source,product_source],
                    exports={name:sha256((root/name).read_bytes()).hexdigest() for name in exports})
    write_text(manifest_path, json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    return model, records, manifest


def configure(parser):
    sub = parser.add_subparsers(dest='benchmark_command', required=True)
    wands = sub.add_parser('wands', help='Import real queries and schema only; no product instances')
    wands.add_argument('--output-dir', type=Path, default=Path('runtime/wands'))
    wands.add_argument('--db', type=Path, default=Path('runtime/background.sqlite'))
    wands.add_argument('--revision', default=REVISION)
    wands.add_argument('--import-only', action='store_true')
    review = sub.add_parser('review', help='Validate and import grounded semantic decisions for a prepared WANDS model')
    review.add_argument('--output-dir', type=Path, default=Path('runtime/wands'))
    review.add_argument('--db', type=Path, default=Path('runtime/background.sqlite'))
    review.add_argument('--revision', default=REVISION)
    review.add_argument('--reviews', type=Path, required=True)


def execute(args):
    exported = {args.output_dir.resolve()/name for name in ('model.json','queries.jsonl','manifest.json','LICENSE-WANDS.txt')}
    if args.db.resolve() in exported:
        raise ValueError('Database and WANDS exports must have distinct paths')
    model, records, manifest = import_wands(args.output_dir, revision=args.revision)
    if args.benchmark_command == 'review':
        from .loop.semantic import annotate_records
        from .loop.store import fingerprint
        decision_file = json.loads(args.reviews.read_text(encoding='utf-8'))
        if decision_file.get('model_hash') != fingerprint(model) or decision_file.get('records_hash') != fingerprint(records):
            raise ValueError('Semantic decision inputs do not match the frozen WANDS inputs')
        records = annotate_records(model, records, decision_file['reviews'])
    summary = dict(queries=len(records), schema_attributes=len(model['facets']),
                   observed_attribute_values=manifest['attribute_values'],
                   categories=len(model['categories']), retained_products=0,
                   relevance_labels_used=False, output_dir=str(args.output_dir))
    if not getattr(args, 'import_only', False):
        from .loop.store import Queue
        from .loop.worker import run_once
        queue = Queue(args.db)
        jid = queue.enqueue(model, records, options={'through':'benchmark'}, synthetic=False)
        run_once(queue, job_id=jid)
        summary.update(job_id=jid, status=queue.get(jid)['status'],
                       url='http://127.0.0.1:8473/jobs/'+jid+'#demands')
    print(json.dumps(summary, ensure_ascii=True, indent=2))
