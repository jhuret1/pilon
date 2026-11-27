"""Command line for local discovery and inspection."""
import argparse
from pathlib import Path
import sys

from . import __version__
from .facets import commands


def main(argv=None):
    parser = argparse.ArgumentParser(description="Discover catalog filters in multichannel feedback.")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="Explore the offline running-shoe example")
    demo.add_argument("example", nargs="?", choices=["ecommerce-facets"])
    commands.arguments(demo)
    # Existing automation may still explicitly request a non-serving demo.
    demo.add_argument("--no-serve", action="store_true", help=argparse.SUPPRESS)

    discover = sub.add_parser("discover", help="Process your catalog model and signal feed")
    discover.add_argument("--model", type=Path, required=True)
    discover.add_argument("--signals", required=True, action="append",
                          help="CSV or JSONL file; repeat for multiple feeds. Use - for JSONL on stdin")
    commands.arguments(discover)

    serve = sub.add_parser("serve", help="View the demo or a custom feed on localhost")
    serve.add_argument("--model", type=Path)
    serve.add_argument("--signals", action="append", help="CSV or JSONL feed; repeat for multiple files")
    serve.add_argument("--port", type=int, default=8472)
    commands.stage_arguments(serve)
    loop = sub.add_parser("loop", help="Benchmark → Extract → Ingest background jobs")
    from .loop.commands import configure, execute as execute_loop
    configure(loop)
    bench = sub.add_parser('benchmark', help='Compare customer requests to a data model')
    from .wands import configure as configure_benchmark, execute as execute_benchmark
    configure_benchmark(bench)
    argv = sys.argv[1:] if argv is None else argv
    args = parser.parse_args(argv or ["demo"])
    try:
        if args.command == "benchmark":
            execute_benchmark(args)
        elif args.command == "loop":
            execute_loop(args)
        elif args.command == "serve":
            from .app import serve_report
            if (args.model is None) != (args.signals is None):
                parser.error("--model and --signals must be supplied together")
            if not 0 <= args.port <= 65535:
                parser.error("--port must be between 0 and 65535")
            report = commands.build_report(args, demo=args.model is None)
            serve_report(report, args.port)
        else:
            commands.execute(args, demo=args.command == "demo")
    except (ValueError, OSError) as exc:
        parser.exit(2, f"PILON: {exc}\n")
    except KeyboardInterrupt:
        return 0
    return 0
