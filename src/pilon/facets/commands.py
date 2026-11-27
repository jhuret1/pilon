import json
from itertools import chain
from pathlib import Path

from .engine import STAGES, explore
from .io import read_signals, write_text
from .report import render


EXAMPLE = Path(__file__).with_name("example")


def stage_arguments(parser):
    parser.add_argument("--through", choices=STAGES, default="usage",
                        help="Stop after this stage (default: usage)")
    parser.add_argument("--horizon-days", type=int, default=30)


def arguments(parser):
    stage_arguments(parser)
    parser.add_argument("--html", type=Path, help="Save a self-contained inspection page")
    parser.add_argument("--output", type=Path, help="Save JSON (default: stdout)")


def input_paths(args, demo):
    if demo:
        return EXAMPLE / "model.json", [EXAMPLE / "signals.jsonl"]
    if args.signals.count("-") > 1:
        raise ValueError("stdin can supply one JSONL feed per run")
    return args.model, args.signals


def build_report(args, demo):
    model, feeds = input_paths(args, demo)
    records = chain.from_iterable(read_signals(path) for path in feeds)
    result = explore(json.loads(model.read_text(encoding="utf-8-sig")), records,
                     through=args.through, horizon_days=args.horizon_days)
    if demo:
        result["synthetic"] = True
    return result


def execute(args, demo=False):
    model, feeds = input_paths(args, demo)
    inputs = {model.resolve(), *(Path(p).resolve() for p in feeds if str(p) != "-")}
    outputs = [p.resolve() for p in (args.output, args.html) if p]
    if len(set(outputs)) < len(outputs) or inputs.intersection(outputs):
        raise ValueError("Choose distinct input, JSON output and HTML paths")
    result = build_report(args, demo)
    if demo and not args.html and not args.output:
        path = Path("runtime/ecommerce-facets.html")
        write_text(path, render(result))
        print(f"{len(result['candidates'])} candidate filter(s) from {result['inventory_products']} products.")
        print(f"Open {path.resolve()}")
        return
    if args.html:
        write_text(args.html, render(result))
    if args.output:
        write_text(args.output, json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    else:
        # ASCII escapes keep redirected JSON portable on Windows console encodings.
        print(json.dumps(result, indent=2, ensure_ascii=True))
