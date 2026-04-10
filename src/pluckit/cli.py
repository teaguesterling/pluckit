"""Command-line interface for pluckit.

Usage:

    pluckit view ".fn#main" "src/**/*.py"
    pluckit view "-" "src/**/*.py" < query.txt
    pluckit view --query-file query.txt "src/**/*.py"
    echo ".class#Config { show: outline; }" | pluckit view - "**/*.py"
    pluckit view ".fn { show: signature; }" file1.py file2.py

The CLI is intentionally small — it dispatches to subcommands. Currently
only `view` is supported; `find` and `mutate` will follow.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pluckit",
        description="Query, view, and mutate source code with CSS selectors.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show version and exit",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    # `view` subcommand
    view_p = subparsers.add_parser(
        "view",
        help="Render matched code regions as markdown",
        description=(
            "Render matched code regions as markdown using a CSS-style "
            "viewer query. The query can be provided as a positional "
            "argument, via --query-file, or read from stdin with '-'."
        ),
    )
    view_p.add_argument(
        "query",
        nargs="?",
        help=(
            "Viewer query string (e.g., '.fn#main' or "
            "'.class#Foo { show: outline; }'). Use '-' to read from stdin."
        ),
    )
    view_p.add_argument(
        "paths",
        nargs="*",
        help="File paths or glob patterns (default: **/*)",
    )
    view_p.add_argument(
        "-q", "--query-file",
        metavar="FILE",
        help="Read query from FILE instead of positional argument",
    )
    view_p.add_argument(
        "-f", "--format",
        default="markdown",
        choices=["markdown"],
        help="Output format (default: markdown)",
    )
    view_p.add_argument(
        "-o", "--output",
        metavar="FILE",
        help="Write output to FILE (default: stdout)",
    )
    view_p.add_argument(
        "-r", "--repo",
        metavar="DIR",
        help="Repository root for relative paths (default: cwd)",
    )

    return parser


def _read_query(query_arg: str | None, query_file: str | None) -> str:
    """Resolve the viewer query from one of three sources.

    Priority:
    1. --query-file FILE
    2. positional '-' → stdin
    3. positional string

    Returns the query text stripped of surrounding whitespace.
    """
    if query_file:
        return Path(query_file).read_text(encoding="utf-8").strip()

    if query_arg is None:
        raise SystemExit(
            "pluckit view: a query is required. Pass it as the first argument, "
            "use --query-file, or pipe with '-'."
        )

    if query_arg == "-":
        return sys.stdin.read().strip()

    return query_arg.strip()


def _normalize_positional_args(args: argparse.Namespace) -> None:
    """When --query-file is supplied, the positional 'query' is actually a path.

    argparse consumes the first positional as 'query' by default. If the user
    provided --query-file, they probably intended all positionals to be paths.
    Shift them in-place.
    """
    if args.query_file and args.query is not None:
        args.paths = [args.query] + list(args.paths)
        args.query = None


def _cmd_view(args: argparse.Namespace) -> int:
    from pluckit import Plucker
    from pluckit.plugins.viewer import AstViewer
    from pluckit.types import PluckerError

    _normalize_positional_args(args)

    query = _read_query(args.query, args.query_file)
    if not query:
        print("pluckit view: empty query", file=sys.stderr)
        return 2

    paths = list(args.paths) if args.paths else ["**/*"]

    outputs: list[str] = []
    for path in paths:
        try:
            pluck = Plucker(code=path, plugins=[AstViewer], repo=args.repo)
            result = pluck.view(query, format=args.format)
        except PluckerError as e:
            print(f"pluckit view: {e}", file=sys.stderr)
            return 1
        except Exception as e:  # pragma: no cover — defensive
            print(f"pluckit view: unexpected error: {e}", file=sys.stderr)
            return 1
        if result:
            outputs.append(result)

    output = "\n\n".join(outputs)

    if args.output:
        Path(args.output).write_text(output + "\n" if output else "", encoding="utf-8")
    else:
        if output:
            print(output)

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.version:
        try:
            from importlib.metadata import version
            print(f"pluckit {version('pluckit')}")
        except Exception:
            print("pluckit (unknown version)")
        return 0

    if args.command == "view":
        return _cmd_view(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
