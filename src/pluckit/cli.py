"""Command-line interface for pluckit.

Usage:

    pluckit view ".fn#main" "src/**/*.py"
    pluckit view "-" "src/**/*.py" < query.txt
    pluckit view --query-file query.txt "src/**/*.py"
    echo ".class#Config { show: outline; }" | pluckit view - "**/*.py"
    pluckit view ".fn { show: signature; }" file1.py file2.py

    pluckit edit ".fn#foo" --replace "return None" "raise ValueError()" src/*.py
    pluckit edit ".fn:exported" --add-param "timeout: int = 30" src/**/*.py
    pluckit edit ".fn#deprecated" --remove src/*.py
    pluckit edit ".fn#foo" --rename "bar" src/*.py

The CLI dispatches to subcommands. `view` renders matched code regions;
`edit` applies structural changes with syntax-validated transactions.
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

    # `edit` subcommand
    edit_p = subparsers.add_parser(
        "edit",
        help="Apply structural edits to matched nodes",
        description=(
            "Apply a structural edit to every node matching SELECTOR "
            "in PATHS. Exactly one edit flag is required. "
            "All edits are transactional — if any file fails syntax "
            "re-validation after splicing, every affected file is rolled "
            "back to its pre-edit state."
        ),
    )
    edit_p.add_argument(
        "selector",
        help="CSS selector for target nodes (e.g., '.fn#main' or '.fn:exported')",
    )
    edit_p.add_argument(
        "paths",
        nargs="+",
        help="File paths or glob patterns",
    )
    edit_p.add_argument(
        "-r", "--repo",
        metavar="DIR",
        help="Repository root for relative paths (default: cwd)",
    )
    edit_p.add_argument(
        "-n", "--dry-run",
        action="store_true",
        help="Print the count of matched nodes without writing anything",
    )

    # Edit operation flags — mutually exclusive
    ops = edit_p.add_mutually_exclusive_group(required=True)
    ops.add_argument(
        "--replace-with",
        metavar="CODE",
        help="Replace entire matched node with CODE",
    )
    ops.add_argument(
        "--replace",
        nargs=2,
        metavar=("OLD", "NEW"),
        help="Scoped replace OLD with NEW within each matched node",
    )
    # Line-level insertions (whole new lines, indentation-matched)
    ops.add_argument(
        "--prepend-lines", "--prepend",
        metavar="CODE",
        dest="prepend_lines",
        help="Insert CODE as new line(s) at the top of the matched node's body",
    )
    ops.add_argument(
        "--append-lines", "--append",
        metavar="CODE",
        dest="append_lines",
        help="Insert CODE as new line(s) at the bottom of the matched node's body",
    )
    ops.add_argument(
        "--wrap",
        nargs=2,
        metavar=("BEFORE", "AFTER"),
        help="Wrap each matched node with BEFORE and AFTER",
    )
    ops.add_argument(
        "--add-param",
        metavar="SPEC",
        help="Add parameter SPEC to matched function signatures (e.g., 'timeout: int = 30')",
    )
    ops.add_argument(
        "--remove-param",
        metavar="NAME",
        help="Remove parameter NAME from matched function signatures",
    )
    ops.add_argument(
        "--add-arg",
        metavar="EXPR",
        help="Add argument EXPR to matched call expressions (e.g., 'timeout=timeout')",
    )
    ops.add_argument(
        "--remove-arg",
        metavar="NAME",
        help="Remove keyword argument NAME from matched call expressions",
    )
    ops.add_argument(
        "--insert-lines",
        nargs=3,
        metavar=("POSITION", "SELECTOR", "CODE"),
        help=(
            "Insert CODE relative to a descendant matching SELECTOR. "
            "POSITION is 'before' or 'after'. SELECTOR is a CSS selector "
            "evaluated against each matched node's subtree; the first match "
            "is used as the anchor."
        ),
    )
    ops.add_argument(
        "--clear-body",
        action="store_true",
        help="Clear the body of matched functions/classes (keeps the signature)",
    )
    ops.add_argument(
        "--rename",
        metavar="NEW_NAME",
        help="Rename matched definitions to NEW_NAME (first name occurrence)",
    )
    ops.add_argument(
        "--remove",
        action="store_true",
        help="Remove matched nodes entirely",
    )
    ops.add_argument(
        "--unwrap",
        action="store_true",
        help="Remove first and last lines of matched nodes, dedent the middle",
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


def _cmd_edit(args: argparse.Namespace) -> int:
    from pluckit import Plucker
    from pluckit.types import PluckerError

    mutation, op_name = _build_mutation_from_args(args)
    if mutation is None:
        print("pluckit edit: no edit operation specified", file=sys.stderr)
        return 2

    total_matched = 0
    total_files = 0
    for path in args.paths:
        try:
            pluck = Plucker(code=path, repo=args.repo)
            selection = pluck.find(args.selector)
            count = selection.count()
        except PluckerError as e:
            print(f"pluckit edit: {e}", file=sys.stderr)
            return 1
        except Exception as e:  # pragma: no cover — defensive
            print(f"pluckit edit: unexpected error: {e}", file=sys.stderr)
            return 1

        if count == 0:
            continue

        total_matched += count
        total_files += 1

        if args.dry_run:
            print(
                f"[dry-run] {path}: would {op_name} on {count} node(s)",
                file=sys.stderr,
            )
            continue

        try:
            from pluckit.mutation import MutationEngine
            MutationEngine(pluck._ctx).apply(selection, mutation)
        except PluckerError as e:
            print(f"pluckit edit: {e}", file=sys.stderr)
            return 1

    if args.dry_run:
        print(
            f"[dry-run] {args.selector}: {total_matched} matches across {total_files} path(s)",
            file=sys.stderr,
        )
    else:
        if total_matched:
            print(
                f"pluckit edit: {op_name} applied to {total_matched} node(s) "
                f"across {total_files} path(s)",
                file=sys.stderr,
            )
        else:
            print(f"pluckit edit: no matches for {args.selector!r}", file=sys.stderr)

    return 0


def _build_mutation_from_args(args: argparse.Namespace):
    """Construct a Mutation instance from the CLI flags.

    Returns (mutation, op_name) for reporting, or (None, '') if none set.
    """
    from pluckit.mutations import (
        AddArg,
        AddParam,
        Append,
        ClearBody,
        InsertAfter,
        InsertBefore,
        Prepend,
        Remove,
        RemoveArg,
        RemoveParam,
        Rename,
        ReplaceWith,
        ScopedReplace,
        Unwrap,
        Wrap,
    )

    if args.replace_with is not None:
        return ReplaceWith(args.replace_with), "replaceWith"
    if args.replace is not None:
        old, new = args.replace
        return ScopedReplace(old, new), "replace"
    if args.prepend_lines is not None:
        return Prepend(args.prepend_lines), "prependLines"
    if args.append_lines is not None:
        return Append(args.append_lines), "appendLines"
    if args.wrap is not None:
        before, after = args.wrap
        return Wrap(before, after), "wrap"
    if args.add_param is not None:
        return AddParam(args.add_param), "addParam"
    if args.remove_param is not None:
        return RemoveParam(args.remove_param), "removeParam"
    if args.add_arg is not None:
        return AddArg(args.add_arg), "addArg"
    if args.remove_arg is not None:
        return RemoveArg(args.remove_arg), "removeArg"
    if args.insert_lines is not None:
        position, selector, code = args.insert_lines
        position = position.lower()
        if position not in ("before", "after"):
            raise SystemExit(
                f"pluckit edit: --insert-lines POSITION must be 'before' or 'after', got {position!r}"
            )
        cls = InsertBefore if position == "before" else InsertAfter
        return cls(selector, code), f"insertLines {position}"
    if args.clear_body:
        return ClearBody(), "clearBody"
    if args.rename is not None:
        return Rename(args.rename), "rename"
    if args.remove:
        return Remove(), "remove"
    if args.unwrap:
        return Unwrap(), "unwrap"
    return None, ""


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

    if args.command == "edit":
        return _cmd_edit(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
