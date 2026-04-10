"""Command-line interface for pluckit.

Usage:

    pluckit view ".fn#main" "src/**/*.py"
    pluckit view --query-file query.txt "src/**/*.py"
    echo ".class#Config { show: outline; }" | pluckit view - "**/*.py"

    pluckit find ".fn:exported" src/**/*.py
    pluckit find ".fn[name^=test_]" --format signature tests/*.py

    pluckit edit ".fn#foo" --replace "return None" "raise ValueError()" src/*.py
    pluckit edit ".fn:exported" --add-param "timeout: int = 30" src/**/*.py

    # Chainable: multiple mutations in one group, multiple groups via --
    pluckit edit \\
        ".cls#Foo .fn#__init__" --add-param "foo: int = 30" --append-lines "self.foo = foo" \\
        -- \\
        ".call#Foo" --add-arg "foo=10" \\
        src/**/*.py

`view` renders matched code regions; `find` lists matches for scripting;
`edit` applies structural changes with syntax-validated transactions.
"""
from __future__ import annotations

import argparse
import difflib
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# view subcommand (unchanged)
# ---------------------------------------------------------------------------

def _build_view_parser() -> argparse.ArgumentParser:
    view_p = argparse.ArgumentParser(
        prog="pluckit view",
        description=(
            "Render matched code regions as markdown using a CSS-style "
            "viewer query. The query can be provided as a positional "
            "argument, via --query-file, or read from stdin with '-'."
        ),
    )
    view_p.add_argument(
        "query",
        nargs="?",
        help="Viewer query string (e.g., '.fn#main'). Use '-' to read from stdin.",
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
    return view_p


def _read_query(query_arg: str | None, query_file: str | None) -> str:
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


def _normalize_view_args(args: argparse.Namespace) -> None:
    if args.query_file and args.query is not None:
        args.paths = [args.query] + list(args.paths)
        args.query = None


def _cmd_view(argv: list[str]) -> int:
    from pluckit import Plucker
    from pluckit.plugins.viewer import AstViewer
    from pluckit.types import PluckerError

    parser = _build_view_parser()
    args = parser.parse_args(argv)
    _normalize_view_args(args)

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
        except Exception as e:  # pragma: no cover
            print(f"pluckit view: unexpected error: {e}", file=sys.stderr)
            return 1
        if result:
            outputs.append(result)

    output = "\n\n".join(outputs)
    if args.output:
        Path(args.output).write_text(output + "\n" if output else "", encoding="utf-8")
    elif output:
        print(output)
    return 0


# ---------------------------------------------------------------------------
# find subcommand — list matches
# ---------------------------------------------------------------------------

def _build_find_parser() -> argparse.ArgumentParser:
    find_p = argparse.ArgumentParser(
        prog="pluckit find",
        description=(
            "List AST nodes matching a CSS selector. Output formats are "
            "designed for scripting and agent discovery: terse file:line "
            "pairs by default, or a signature table, or machine-readable "
            "JSON."
        ),
    )
    find_p.add_argument(
        "selector",
        help="CSS selector (e.g., '.fn:exported' or '.fn[name^=test_]')",
    )
    find_p.add_argument(
        "paths",
        nargs="+",
        help="File paths or glob patterns",
    )
    find_p.add_argument(
        "-f", "--format",
        choices=["locations", "names", "signature", "json"],
        default="locations",
        help=(
            "Output format: 'locations' (file:line:name, default), "
            "'names' (just the name), 'signature' (markdown table with "
            "synthesized signatures), 'json' (one object per match)"
        ),
    )
    find_p.add_argument(
        "-o", "--output",
        metavar="FILE",
        help="Write output to FILE (default: stdout)",
    )
    find_p.add_argument(
        "-r", "--repo",
        metavar="DIR",
        help="Repository root for relative paths (default: cwd)",
    )
    find_p.add_argument(
        "--count",
        action="store_true",
        help="Print only the total number of matches",
    )
    return find_p


def _cmd_find(argv: list[str]) -> int:
    import json as _json

    from pluckit import Plucker
    from pluckit.plugins.viewer import AstViewer
    from pluckit.types import PluckerError

    parser = _build_find_parser()
    args = parser.parse_args(argv)

    total = 0
    rows: list[dict[str, Any]] = []

    for path in args.paths:
        try:
            pluck = Plucker(code=path, plugins=[AstViewer], repo=args.repo)
            sel = pluck.find(args.selector)
        except PluckerError as e:
            print(f"pluckit find: {e}", file=sys.stderr)
            return 1
        except Exception as e:  # pragma: no cover
            print(f"pluckit find: unexpected error: {e}", file=sys.stderr)
            return 1

        view = sel._register("find")
        try:
            fetched = pluck._ctx.db.sql(
                f"SELECT file_path, start_line, end_line, name, type, language, "
                f"       signature_type, parameters, modifiers, annotations "
                f"FROM {view} ORDER BY file_path, start_line"
            ).fetchall()
        except Exception:
            # Fallback when native extraction columns aren't present
            fetched = pluck._ctx.db.sql(
                f"SELECT file_path, start_line, end_line, name, type, language, "
                f"       NULL, NULL, NULL, NULL "
                f"FROM {view} ORDER BY file_path, start_line"
            ).fetchall()
        finally:
            try:
                sel._unregister(view)
            except Exception:
                pass

        cols = ["file_path", "start_line", "end_line", "name", "type",
                "language", "signature_type", "parameters", "modifiers", "annotations"]
        for row in fetched:
            node = dict(zip(cols, row, strict=True))
            if args.repo:
                repo = args.repo
            else:
                repo = os.getcwd()
            try:
                node["rel_path"] = os.path.relpath(node["file_path"], repo)
            except ValueError:
                node["rel_path"] = node["file_path"]
            rows.append(node)
            total += 1

    if args.count:
        out = str(total)
    elif args.format == "locations":
        lines = []
        for r in rows:
            name = r["name"] or r["type"]
            lines.append(f"{r['rel_path']}:{r['start_line']}:{name}")
        out = "\n".join(lines)
    elif args.format == "names":
        names = {r["name"] for r in rows if r["name"]}
        out = "\n".join(sorted(names))
    elif args.format == "signature":
        from pluckit.plugins.viewer import _synthesize_signature
        table_rows = []
        for r in rows:
            sig = _synthesize_signature(r)
            if not sig:
                continue
            line_range = (
                f"{r['start_line']}-{r['end_line']}"
                if r["end_line"] != r["start_line"]
                else str(r["start_line"])
            )
            sig_cell = sig.replace("|", "\\|")
            table_rows.append(f"| {r['rel_path']} | {line_range} | `{sig_cell}` |")
        if table_rows:
            out = "| File | Lines | Signature |\n|---|---|---|\n" + "\n".join(table_rows)
        else:
            out = ""
    elif args.format == "json":
        out = "\n".join(
            _json.dumps({
                "file": r["rel_path"],
                "start_line": r["start_line"],
                "end_line": r["end_line"],
                "name": r["name"],
                "type": r["type"],
                "language": r["language"],
            })
            for r in rows
        )
    else:
        out = ""

    if args.output:
        Path(args.output).write_text(out + "\n" if out else "", encoding="utf-8")
    elif out:
        print(out)
    return 0


# ---------------------------------------------------------------------------
# edit subcommand — chainable multi-mutation with -- group separator
# ---------------------------------------------------------------------------

@dataclass
class EditGroup:
    """One group of edits to apply: a selector plus an ordered list of operations."""
    selector: str = ""
    operations: list[tuple[str, Any]] = field(default_factory=list)


@dataclass
class EditPlan:
    """A parsed edit command: global flags plus one or more edit groups."""
    groups: list[EditGroup] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    repo: str | None = None
    dry_run: bool = False


# Maps CLI flag → (op_kind, nargs). nargs is the number of value args
# the flag consumes (0 for store-true flags, 1 for single-arg, etc.).
_EDIT_FLAGS: dict[str, tuple[str, int]] = {
    "--replace-with": ("replaceWith", 1),
    "--replace": ("replace", 2),
    "--prepend-lines": ("prependLines", 1),
    "--prepend": ("prependLines", 1),  # alias
    "--append-lines": ("appendLines", 1),
    "--append": ("appendLines", 1),  # alias
    "--wrap": ("wrap", 2),
    "--add-param": ("addParam", 1),
    "--remove-param": ("removeParam", 1),
    "--add-arg": ("addArg", 1),
    "--remove-arg": ("removeArg", 1),
    "--insert-lines": ("insertLines", 3),
    "--clear-body": ("clearBody", 0),
    "--rename": ("rename", 1),
    "--remove": ("remove", 0),
    "--unwrap": ("unwrap", 0),
}

# Global edit flags (apply to the whole command, not a specific group)
_EDIT_GLOBAL_FLAGS = {
    "--dry-run": ("dry_run", 0),
    "-n": ("dry_run", 0),
    "--repo": ("repo", 1),
    "-r": ("repo", 1),
}


def _parse_edit_argv(argv: list[str]) -> EditPlan:
    """Parse the edit subcommand's argv into an EditPlan.

    Handles:
    - Multiple mutation flags per group (preserves order)
    - ``--`` as a group separator (each group has its own selector + flags)
    - Global flags (``--dry-run``, ``--repo``) from anywhere in the command
    - Trailing positional paths in the last segment

    The structure is::

        [GLOBAL_FLAGS] SEL1 OP1 [OP2 ...] [-- SEL2 OP1 [OP2 ...] [-- ...]] PATHS

    Any positional argument that isn't a selector or a flag value becomes
    part of the trailing paths (only meaningful in the last group).
    """
    plan = EditPlan()
    current = EditGroup()
    plan.groups.append(current)
    trailing_positionals: list[str] = []

    i = 0
    n = len(argv)
    while i < n:
        tok = argv[i]

        # Group separator
        if tok == "--":
            current = EditGroup()
            plan.groups.append(current)
            trailing_positionals = []  # paths belong to the LAST group only
            i += 1
            continue

        # Global flags
        if tok in _EDIT_GLOBAL_FLAGS:
            dest, narg = _EDIT_GLOBAL_FLAGS[tok]
            if narg == 0:
                setattr(plan, dest, True)
                i += 1
            else:
                if i + 1 >= n:
                    raise SystemExit(f"pluckit edit: {tok} requires an argument")
                setattr(plan, dest, argv[i + 1])
                i += 2
            continue

        # Mutation flags
        if tok in _EDIT_FLAGS:
            op_kind, narg = _EDIT_FLAGS[tok]
            if narg == 0:
                current.operations.append((op_kind, True))
                i += 1
            else:
                if i + narg >= n:
                    raise SystemExit(
                        f"pluckit edit: {tok} requires {narg} argument(s)"
                    )
                values = argv[i + 1:i + 1 + narg]
                if narg == 1:
                    current.operations.append((op_kind, values[0]))
                else:
                    current.operations.append((op_kind, tuple(values)))
                i += 1 + narg
            continue

        # Unknown flag
        if tok.startswith("-"):
            raise SystemExit(f"pluckit edit: unknown flag {tok!r}")

        # Positional — first one in the group is the selector, rest are paths
        if not current.selector:
            current.selector = tok
        else:
            trailing_positionals.append(tok)
        i += 1

    # Trailing positionals (from the last group) become the shared path list
    plan.paths = trailing_positionals

    # If the last group has a selector but no operations, its "selector" was
    # actually a path positional that landed in a fresh group after `--`.
    # Fold it back into the shared path list and drop the empty group.
    # (e.g., `edit .fn#x --remove -- src/*.py` should treat src/*.py as a path.)
    while plan.groups and not plan.groups[-1].operations:
        dropped = plan.groups.pop()
        if dropped.selector:
            plan.paths.insert(0, dropped.selector)

    return plan


def _build_mutation(op_kind: str, value: Any):
    """Construct a Mutation instance from an (op_kind, value) pair."""
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

    if op_kind == "replaceWith":
        return ReplaceWith(value)
    if op_kind == "replace":
        old, new = value
        return ScopedReplace(old, new)
    if op_kind == "prependLines":
        return Prepend(value)
    if op_kind == "appendLines":
        return Append(value)
    if op_kind == "wrap":
        before, after = value
        return Wrap(before, after)
    if op_kind == "addParam":
        return AddParam(value)
    if op_kind == "removeParam":
        return RemoveParam(value)
    if op_kind == "addArg":
        return AddArg(value)
    if op_kind == "removeArg":
        return RemoveArg(value)
    if op_kind == "insertLines":
        position, selector, code = value
        position = position.lower()
        if position not in ("before", "after"):
            raise SystemExit(
                f"pluckit edit: --insert-lines POSITION must be 'before' or 'after', got {position!r}"
            )
        return InsertBefore(selector, code) if position == "before" else InsertAfter(selector, code)
    if op_kind == "clearBody":
        return ClearBody()
    if op_kind == "rename":
        return Rename(value)
    if op_kind == "remove":
        return Remove()
    if op_kind == "unwrap":
        return Unwrap()
    raise SystemExit(f"pluckit edit: unknown operation {op_kind!r}")


def _cmd_edit(argv: list[str]) -> int:
    from pluckit import Plucker
    from pluckit.mutation import MutationEngine
    from pluckit.types import PluckerError

    plan = _parse_edit_argv(argv)

    if not plan.groups:
        print("pluckit edit: no operations specified", file=sys.stderr)
        return 2

    if not plan.paths:
        print(
            "pluckit edit: no paths specified (add file paths or globs at the end)",
            file=sys.stderr,
        )
        return 2

    # Validate each group has at least one operation and a selector
    for i, group in enumerate(plan.groups):
        if not group.selector:
            print(f"pluckit edit: group {i + 1} has no selector", file=sys.stderr)
            return 2
        if not group.operations:
            print(
                f"pluckit edit: group {i + 1} ({group.selector!r}) has no operations",
                file=sys.stderr,
            )
            return 2

    total_matched = 0
    total_files = 0

    for path in plan.paths:
        try:
            pluck = Plucker(code=path, repo=plan.repo)
        except PluckerError as e:
            print(f"pluckit edit: {e}", file=sys.stderr)
            return 1

        engine = MutationEngine(pluck._ctx)

        # For dry-run diff preview, snapshot files before ANY group runs
        snapshots: dict[str, str] = {}

        for group in plan.groups:
            try:
                selection = pluck.find(group.selector)
                count = selection.count()
            except PluckerError as e:
                print(f"pluckit edit: {e}", file=sys.stderr)
                return 1
            except Exception as e:  # pragma: no cover
                print(f"pluckit edit: unexpected error: {e}", file=sys.stderr)
                return 1

            if count == 0:
                continue

            total_matched += count

            # Record affected files for diff preview
            if plan.dry_run:
                try:
                    view = selection._register("dryrun")
                    fps = pluck._ctx.db.sql(
                        f"SELECT DISTINCT file_path FROM {view}"
                    ).fetchall()
                    for (fp,) in fps:
                        if fp not in snapshots:
                            snapshots[fp] = Path(fp).read_text(encoding="utf-8")
                finally:
                    try:
                        selection._unregister(view)
                    except Exception:
                        pass

            for op_kind, value in group.operations:
                mutation = _build_mutation(op_kind, value)
                try:
                    if plan.dry_run:
                        # Apply to snapshots in memory, not to disk
                        _apply_mutation_to_snapshots(
                            engine, selection, mutation, snapshots, pluck
                        )
                    else:
                        engine.apply(selection, mutation)
                except PluckerError as e:
                    print(f"pluckit edit: {e}", file=sys.stderr)
                    return 1

        total_files += 1 if snapshots or total_matched else 0

        # Dry-run output: show diff between snapshots and on-disk content
        if plan.dry_run:
            for fp, new_content in snapshots.items():
                original = Path(fp).read_text(encoding="utf-8")
                if new_content == original:
                    continue
                rel = _relpath(fp, plan.repo)
                diff = difflib.unified_diff(
                    original.splitlines(keepends=True),
                    new_content.splitlines(keepends=True),
                    fromfile=f"a/{rel}",
                    tofile=f"b/{rel}",
                )
                sys.stdout.write("".join(diff))

    if plan.dry_run:
        print(
            f"[dry-run] {len(plan.groups)} group(s), {total_matched} total match(es)",
            file=sys.stderr,
        )
    else:
        if total_matched:
            ops_summary = ", ".join(
                f"{op_kind}" for group in plan.groups for op_kind, _ in group.operations
            )
            print(
                f"pluckit edit: applied [{ops_summary}] "
                f"to {total_matched} node(s)",
                file=sys.stderr,
            )
        else:
            print("pluckit edit: no matches for any group", file=sys.stderr)

    return 0


def _apply_mutation_to_snapshots(engine, selection, mutation, snapshots, pluck) -> None:
    """Apply a mutation to in-memory snapshots instead of disk (dry-run mode).

    This bypasses the engine's file read/write and works purely on the
    snapshot dict, producing the same result as a real apply.
    """
    rows = engine._materialize(selection)
    by_file: dict[str, list[dict]] = {}
    for row in rows:
        by_file.setdefault(row["file_path"], []).append(row)

    for fp, nodes in by_file.items():
        if fp not in snapshots:
            snapshots[fp] = Path(fp).read_text(encoding="utf-8")
        snapshots[fp] = engine._splice_file(snapshots[fp], nodes, mutation)


def _relpath(fp: str, repo: str | None) -> str:
    try:
        return os.path.relpath(fp, repo or os.getcwd())
    except ValueError:
        return fp


# ---------------------------------------------------------------------------
# Top-level dispatcher
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if not argv or argv[0] in ("-h", "--help"):
        _print_top_help()
        return 0

    if argv[0] == "--version":
        print(f"pluckit {_package_version()}")
        return 0

    command = argv[0]
    rest = argv[1:]

    if command == "view":
        return _cmd_view(rest)
    if command == "find":
        return _cmd_find(rest)
    if command == "edit":
        return _cmd_edit(rest)
    if command == "init":
        return _cmd_init(rest)

    print(f"pluckit: unknown command {command!r}", file=sys.stderr)
    _print_top_help()
    return 2


def _package_version() -> str:
    from importlib.metadata import PackageNotFoundError, version
    for dist in ("ast-pluckit", "pluckit"):
        try:
            return version(dist)
        except PackageNotFoundError:
            continue
    return "unknown"


def _print_top_help() -> None:
    print("""\
usage: pluckit COMMAND [options] ...

Query, view, and edit source code with CSS selectors.

Commands:
  init     Install and verify the required DuckDB extensions
  view     Render matched code regions as markdown
  find     List matches (locations, names, signatures, or JSON)
  edit     Apply structural edits to matched nodes

Options:
  --version  Show version and exit
  -h, --help Show this help message

Run `pluckit COMMAND --help` for command-specific options.
""")


# ---------------------------------------------------------------------------
# init subcommand — install and verify DuckDB extensions
# ---------------------------------------------------------------------------

def _cmd_init(argv: list[str]) -> int:
    """Install sitting_duck (and optionally duck_tails) and verify they load.

    This eagerly performs what ``_Context._ensure_extensions`` does lazily on
    first use, and reports clearly actionable errors rather than letting a
    raw DuckDB exception bubble up mid-query.
    """
    parser = argparse.ArgumentParser(
        prog="pluckit init",
        description=(
            "Install and verify the DuckDB community extensions that pluckit "
            "depends on. Safe to re-run; already-installed extensions are "
            "only re-verified."
        ),
    )
    parser.add_argument(
        "--force-reinstall",
        action="store_true",
        help="Re-install extensions even if they already load",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress success messages; only print errors",
    )
    args = parser.parse_args(argv)

    try:
        import duckdb
    except ImportError:
        print(
            "pluckit init: duckdb is not installed. Run "
            "`pip install 'ast-pluckit'` to pull it in as a dependency.",
            file=sys.stderr,
        )
        return 1

    extensions = [
        ("sitting_duck", True),   # required
        ("duck_tails", False),    # optional (v0.2 History plugin)
    ]

    conn = duckdb.connect()
    failures: list[tuple[str, str]] = []

    for ext, required in extensions:
        label = "required" if required else "optional"
        try:
            if args.force_reinstall:
                conn.sql(f"INSTALL {ext} FROM community")
            conn.sql(f"LOAD {ext}")
            if not args.quiet:
                print(f"  {ext} ({label}): loaded")
        except duckdb.Error:
            try:
                conn.sql(f"INSTALL {ext} FROM community")
                conn.sql(f"LOAD {ext}")
                if not args.quiet:
                    print(f"  {ext} ({label}): installed and loaded")
            except duckdb.Error as e:
                failures.append((ext, str(e)))
                print(
                    f"  {ext} ({label}): FAILED — {e}",
                    file=sys.stderr,
                )

    if failures:
        required_failed = [ext for ext, _ in failures if any(
            ext == e and req for e, req in extensions)]
        if required_failed:
            print(
                "\npluckit init: required extensions could not be installed: "
                f"{', '.join(required_failed)}.\n"
                "Check that your DuckDB build supports community extensions "
                "and that you have network access to install from the "
                "community repository.",
                file=sys.stderr,
            )
            return 1
        if not args.quiet:
            print(
                "\npluckit init: required extensions installed. "
                "Optional extensions unavailable — some plugins will be disabled.",
                file=sys.stderr,
            )
        return 0

    if not args.quiet:
        print("\npluckit init: all extensions ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
