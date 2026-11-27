import argparse
import json
from pathlib import Path
from . import __version__
from .facets import commands as facets


def main(argv=None):
    parser = argparse.ArgumentParser(description='PILON · knowledge discovery from customer signals and catalog evidence')
    parser.add_argument('--version', action='version', version=__version__)
    sub = parser.add_subparsers(dest='command', required=True)
    demo = sub.add_parser('demo', help='Replay synthetic fixtures offline; no model or API key')
    demo.add_argument('example', nargs='?', choices=['ecommerce-facets'])
    facets.arguments(demo)
    discover = sub.add_parser('discover', help='Find potential catalog filters from feedback and product specifications')
    discover.add_argument('--model', type=Path, required=True)
    discover.add_argument('--signals', required=True, help='JSONL or CSV file, or - for JSONL on stdin')
    facets.arguments(discover)
    demo.add_argument('--no-serve', action='store_true')
    run = sub.add_parser('run', help='Run paid induction only with explicit opt-in')
    run.add_argument('input', type=Path)
    run.add_argument('--provider', choices=['openrouter'], required=True)
    run.add_argument('--budget', type=float, required=True)
    run.add_argument('--allow-paid', action='store_true')
    run.add_argument('--request-key', help='Optional idempotency key, 8–100 characters')
    serve = sub.add_parser('serve', help='Read-only local results viewer; no inference')
    export = sub.add_parser('export', help='Export a run with evidence, decisions and metrics')
    export.add_argument('run_id')
    export.add_argument('--output', type=Path, required=True)
    amazon = sub.add_parser('import-amazon', help='Download a bounded public Amazon slice; no inference')
    amazon.add_argument('--output', type=Path, default=Path('data/amazon-home-kitchen.json'))
    amazon.add_argument('--limit', type=int, default=20)
    amazon.add_argument('--offset', type=int, default=0)
    amazon.add_argument('--category', default='Home_and_Kitchen')
    amazon.add_argument('--revision')
    for p in (demo, run, serve, export):
        p.add_argument('--db', type=Path, default=Path('runtime/pilon.sqlite'))
    for p in (demo, serve):
        p.add_argument('--port', type=int, default=8472)
    args = parser.parse_args(argv)
    try:
        if args.command == 'discover' or (args.command == 'demo' and args.example == 'ecommerce-facets'):
            facets.execute(args, demo=args.command == 'demo')
        elif args.command == 'import-amazon':
            from .amazon import download
            from .corpus import rows
            result = download(args.output, limit=args.limit, offset=args.offset, category=args.category, revision=args.revision)
            print(json.dumps(dict(output=str(args.output), reviews=len(rows(result)), items=len(result['items']),
                                  revision=result['provenance']['revision'], inference_calls=0), indent=2))
        elif args.command in ('demo', 'run'):
            from .service import execute
            from .fixture import corpus
            from .corpus import load
            demo_mode = args.command == 'demo'
            result = execute(args.db, corpus() if demo_mode else load(args.input),
                             provider='fixture' if demo_mode else args.provider, budget=0 if demo_mode else args.budget,
                             allow_paid=False if demo_mode else args.allow_paid,
                             request_key=None if demo_mode else args.request_key)
            print(json.dumps(dict(run_id=result['id'], status=result['status'], concepts=len(result['facts']),
                                  metrics=result['metrics'], notice=result['quality_notice'], error=result['error']), indent=2))
            if result['status'] != 'completed':
                return 2
            if demo_mode and not args.no_serve:
                show(args)
        elif args.command == 'serve':
            show(args)
        elif args.command == 'export':
            from .store import Store
            from .service import snapshot
            from .consolidation import atomic_json
            if args.output.exists():
                raise ValueError('Output already exists; use a new filename.')
            atomic_json(args.output, snapshot(Store(args.db), args.run_id))
            print(str(args.output))
    except (ValueError, OSError) as exc:
        parser.exit(2, f'PILON: {exc}\n')
    return 0


def show(args):
    from .app import create_app
    print(f'Open http://127.0.0.1:{args.port} · read-only local viewer', flush=True)
    create_app(args.db).run(host='127.0.0.1', port=args.port, debug=False, use_reloader=False)
