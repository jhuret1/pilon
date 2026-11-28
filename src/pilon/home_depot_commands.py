"""Explicit local-data entry point: no competition login or inference API calls."""
import json
from pathlib import Path


def configure(subparsers):
    command = subparsers.add_parser('home-depot', help='Compare distinct Home Depot queries with observed catalog attributes')
    command.add_argument('--input-dir', type=Path, required=True, help='Directory containing train.csv and attributes.csv')
    command.add_argument('--output-dir', type=Path, default=Path('runtime/home-depot/prepared'))
    command.add_argument('--db', type=Path, default=Path('runtime/background.sqlite'))
    command.add_argument('--sample-size', type=int, default=1000)
    command.add_argument('--seed', default='pilon-home-depot-v1')
    command.add_argument('--import-only', action='store_true')
    command.add_argument('--reviews', type=Path, help='Grounded semantic decisions tied to these frozen inputs')
    command.add_argument('--audit', type=Path, help='Optional locally reviewed errors/disagreements with exact quotations')


def execute(args):
    from .home_depot import import_home_depot
    from .loop.store import Queue, fingerprint
    from .loop.worker import run_once
    from .loop.semantic import annotate_records
    model, records, manifest = import_home_depot(args.input_dir, args.output_dir,
                                                sample_size=args.sample_size, seed=args.seed)
    if args.reviews:
        decisions = json.loads(args.reviews.read_text(encoding='utf-8'))
        if decisions.get('format') == 'pilon_detached_semantic_reviews_v1':
            from .loop.review_bundle import attach_reviews
            reviews = attach_reviews(decisions,model,records)
        else:
            if decisions.get('model_hash') != fingerprint(model) or decisions.get('records_hash') != fingerprint(records):
                raise ValueError('Semantic decisions do not match the frozen Home Depot inputs')
            reviews = decisions['reviews']
        records = annotate_records(model, records, reviews)
    options = {'through': 'benchmark'}
    if args.reviews and decisions.get('audit') and not args.audit:
        from .loop.review_bundle import attach_audit
        options['audit'] = attach_audit(decisions['audit'], model, records)
    if args.audit:
        from .loop.audit import validate_audit
        options['audit'] = validate_audit(json.loads(args.audit.read_text(encoding='utf-8')), model, records)
    summary = dict(dataset='Home Depot', queries=len(records), attributes=len(model['facets']),
                   observed_attribute_values=sum(len(f.get('values', [])) for f in model['facets']),
                   output_dir=str(args.output_dir), api_calls=0,
                   relevance_labels_used=False, query_product_associations_used=False)
    if not args.import_only:
        queue = Queue(args.db)
        jid = queue.enqueue(model, records, options=options, synthetic=False)
        run_once(queue, job_id=jid)
        summary.update(job_id=jid, status=queue.get(jid)['status'],
                       url='http://127.0.0.1:8473/jobs/' + jid + '#opportunities')
    print(json.dumps(summary, indent=2))
