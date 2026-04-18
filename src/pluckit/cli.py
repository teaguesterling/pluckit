"""Command-line interface for pluckit.

Usage:

    pluckit [FLAGS] SOURCE STEP [STEP...] [-- STEP...]
    pluckit --json JSON_STRING
    pluckit init [--force-reinstall] [--quiet]

Everything is expressed as a chain: source patterns followed by a
pipeline of operations.  The CLI parses arguments into a ``Chain``
object, resolves configuration, and evaluates it.
"""
from __future__ import annotations

import argparse
import sys

from pluckit.chain import Chain

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _package_version() -> str:
    from importlib.metadata import PackageNotFoundError, version
    for dist in ("ast-pluckit", "pluckit"):
        try:
            return version(dist)
        except PackageNotFoundError:
            continue
    return "unknown"


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

def _print_help() -> None:
    print("""\
usage: pluckit [FLAGS] SOURCE STEP [STEP...] [-- STEP...]
       pluckit --json JSON_STRING
       pluckit init [--force-reinstall] [--quiet]

Query, view, and edit source code with CSS selectors.

Source:
  PATH / GLOB       File paths or glob patterns (e.g., src/**/*.py)
  -c, --code        Use the 'code' source from [tool.pluckit.sources]
  -d, --docs        Use the 'docs' source
  -t, --tests       Use the 'tests' source

Steps (chain operations):
  find SELECTOR      Select AST nodes matching a CSS selector
  filter [KWARGS]    Narrow the selection (--name__startswith=..., etc.)
  count / names / text / materialize    Terminal: return data
  view [QUERY]       Render matched regions as markdown
  addParam / removeParam / rename / remove / ...    Mutations
  patch CONTENT      Apply a unified diff or replacement text
  reset              Start a new find context (also: bare --)
  pop                Return to previous selection scope

Arguments:
  @PATH              Read argument content from a file
  @@PATH             Literal @PATH (escape the @ prefix)

Flags:
  --plugin NAME      Load a plugin (repeatable)
  --repo DIR         Repository root (default: cwd)
  --dry-run, -n      Preview changes without writing
  --diff             Output mutation changes as unified diff (no writes)
  --json JSON        Evaluate a JSON chain string
  --to-json          Emit the parsed chain as JSON (don't evaluate)
  --version          Show version
  -h, --help         Show this help

Config:
  Default plugins and source shortcuts are read from [tool.pluckit]
  in pyproject.toml. See docs for details.

Examples:
  pluckit src/**/*.py find ".fn:exported" count
  pluckit -c find ".fn#validate_token" view
  pluckit src/**/*.py find ".fn#foo" addParam "trace: str = None"
  pluckit src/**/*.py find ".fn#foo" rename bar -- find ".call#foo" addArg "trace=None"
  pluckit src/**/*.py find ".fn#foo" rename bar --diff > refactor.patch
  pluckit src/**/*.py find ".fn#foo" replaceWith @patches/new_foo.py
  pluckit src/**/*.py find ".fn#foo" patch @refactor.patch
""")


# ---------------------------------------------------------------------------
# Result formatting
# ---------------------------------------------------------------------------

def _print_result(result: dict) -> None:
    import json as _json

    rtype = result.get("type", "")
    data = result.get("data")

    if rtype == "count":
        print(data)
    elif rtype == "names":
        for name in data:
            print(name)
    elif rtype == "text":
        for text in data:
            print(text)
    elif rtype == "view":
        for block in data.get("blocks", []):
            md = block.get("markdown", "")
            if md:
                print(md)
    elif rtype == "mutation":
        print("pluckit: mutation applied", file=sys.stderr)
    elif rtype == "materialize":
        for row in data:
            print(_json.dumps(row))
    elif rtype in ("history",):
        for item in data:
            if isinstance(item, dict):
                print(_json.dumps(item))
            else:
                print(item)
    elif rtype in ("authors", "at", "diff"):
        for item in data:
            print(item)
    else:
        print(_json.dumps(data))


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


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if not argv or argv[0] in ("-h", "--help"):
        _print_help()
        return 0

    if argv[0] == "--version":
        print(f"pluckit {_package_version()}")
        return 0

    if argv[0] == "init":
        return _cmd_init(argv[1:])

    # Parse as chain
    try:
        chain = Chain.from_argv(argv)
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 2

    # --json mode: re-parse from the JSON string
    if chain.json_input:
        json_text = chain.source[0] if chain.source else ""
        try:
            chain = Chain.from_json(json_text)
            chain.json_input = True
        except (ValueError, KeyError) as e:
            print(f"pluckit: invalid chain JSON: {e}", file=sys.stderr)
            return 2

    # --to-json: emit chain as JSON without evaluating
    if chain.json_output:
        print(chain.to_json(indent=2))
        return 0

    # Resolve source shortcuts via config
    from pluckit.config import PluckitConfig
    config = PluckitConfig.load(chain.repo)
    resolved_source: list[str] = []
    for s in chain.source:
        resolved_source.extend(config.resolve_source(s))
    chain.source = resolved_source

    # Merge config plugins with explicit plugins
    all_plugins = list(dict.fromkeys(config.plugins + chain.plugins))
    chain.plugins = all_plugins

    # Evaluate
    try:
        result = chain.evaluate()
    except Exception as e:
        print(f"pluckit: {e}", file=sys.stderr)
        return 1

    # Format and print result
    _print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
