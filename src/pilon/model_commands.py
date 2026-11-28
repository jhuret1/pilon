"""Explicit opt-in command for the configured semantic Benchmark connector."""
import json
from pathlib import Path

from .model_review import run_benchmark
from .facets.io import read_signals


def configure(subparsers):
    parser = subparsers.add_parser('run', help='Review a complete supplied model; dry run unless --execute')
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--signals', type=Path, action='append', required=True, help='Local demand JSONL or CSV; repeat for multiple files')
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--db', type=Path, default=Path('runtime/background.sqlite'))
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--execute', action='store_true', help='Allow configured provider calls and enqueue Benchmark only')


def execute(args):
    from .providers import load_config
    inputs = {p.resolve() for p in [args.model, args.config, *args.signals]}
    outputs = {args.db.resolve(), *[args.output_dir.resolve()/name for name in
               ('checkpoint.json', 'reviews.json', 'annotated-signals.jsonl', 'benchmark.json', 'run.lock')]}
    if inputs & outputs or args.output_dir.resolve() in inputs:
        raise ValueError('Input files, database and generated outputs must have distinct paths')
    config = load_config(args.config)
    model = json.loads(args.model.read_text(encoding='utf-8-sig'))
    records = []
    for path in args.signals:
        records.extend(read_signals(path))
    try:
        result = run_benchmark(model, records, config, output_dir=args.output_dir,
                               db=args.db, execute=args.execute)
    except RuntimeError:
        # ProviderError is RuntimeError-derived; do not echo transport/body/key text.
        raise ValueError('Provider operation failed; inspect the safe usage checkpoint and provider configuration') from None
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return result
