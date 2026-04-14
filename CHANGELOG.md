# Changelog

All notable changes to this project are documented here. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **MCP-ready serialization protocol.** A uniform
  `to/from_{dict,json,argv}` interface across pluckit's core types so
  squackit (and other MCP consumers) can round-trip structured state:
  - **`Selector`** — new class (subclasses `str`) with `validate()`,
    `is_valid`, and the full serialization protocol. Backward-compatible
    everywhere a bare selector string is used today.
  - **`Plucker`** — serializes its constructor args (code, plugins,
    repo), not the live DuckDB connection. Plugin names resolve via
    `resolve_plugins()` on deserialization.
  - **`View`** — gains `from_dict`, `from_json`, `to_json` (already had
    `to_dict`). Round-trips through JSON.
  - **`Selection`** — gains `to_chain()` which walks the `_parent`/`_op`
    provenance to reconstruct the chain that produced it, plus
    `to_dict()`/`to_json()` as wrappers.
  - **`Chain`** — gains `to_argv()` (the inverse of `from_argv`) so a
    chain round-trips CLI ↔ dict ↔ JSON ↔ argv.
  - **`Commit`** — gains `to_dict`, `from_dict`, `to_json`, `from_json`.
- **AST caching (`cache=True`).** A `Plucker(cache=True)` opens a
  persistent DuckDB file (`.pluckit.duckdb` in the repo root by
  default) and materializes `read_ast` output into per-pattern tables.
  Subsequent queries against the same pattern skip re-parsing and hit
  the cached table directly. File-stat mtime checks drive incremental
  invalidation — only modified files are re-parsed; the rest of the
  cache is preserved.
  - `cache=True` — use `.pluckit.duckdb` under the repo
  - `cache="/custom/path.duckdb"` — custom cache location
  - `[tool.pluckit] cache = true` and `cache_path = "..."` in
    `pyproject.toml`
  - `ASTCache` and `PluckitConfig` are both exported from the top-level
    package for programmatic use.
- `.pluckit.duckdb` and `.pluckit.duckdb.wal` are added to `.gitignore`.

- **`View` return type for `Plucker.view()`**. Previously `view()`
  returned a bare `str` of rendered markdown. It now returns a
  structured `View` object that:
  - Stringifies to the markdown output (``str(v)``, ``print(v)``,
    ``f"{v}"`` all work as before)
  - Supports ``len(v)``, ``bool(v)``, iteration (``for block in v``),
    indexing (``v[0]``), slicing (``v[:3]``), and containment
    (``"def main" in v``)
  - Exposes ``.markdown``, ``.blocks``, ``.files``, and
    ``.to_dict()`` for structured consumers (agents, JSON pipelines)
  - Wraps each rendered block in a frozen ``ViewBlock`` dataclass
    with ``name``, ``file_path``, ``start_line``, ``end_line``,
    ``node_type``, ``language``, ``show``, and ``rule`` fields
  - Treats multi-match signature tables as a single aggregate
    ``ViewBlock`` (with ``file_path`` / ``start_line`` / ``end_line``
    all ``None`` and ``show == "signature-table"``) so consumers can
    detect auto-collapsed output
- **`History` pluckin** — a v0.2 plugin wrapping `duck_tails` for
  git-history operations on AST selections. Four methods:
  - `history()` — commits that touched each matched node's file
    (rename-aware via `git log --follow`)
  - `authors()` — distinct commit authors for those files
  - `at(rev)` — source text of each matched node **as of revision
    `rev`**, AST-aware: re-parses the file at the old revision and
    looks the node up by `(name, type)` rather than naively slicing
    by current line range
  - `diff(rev)` — per-node unified diff between HEAD and `rev`, using
    the same AST-aware node resolution
- `Commit` dataclass exported from `pluckit` and `pluckit.plugins`
  for typed access to the fields returned by `history()`.

### Architecture notes

- `history()` / `authors()` shell out to `git log --follow` because
  `duck_tails`'s SQL surface has no line-range or file-history join
  point — a pure-SQL implementation would require iterated
  per-commit `git_diff_tree` calls with no lateral-join support.
  Subprocess is faster, rename-aware for free, and simpler.
- `at(rev)` / `diff(rev)` use `duck_tails.git_read` to fetch file
  content at a revision, then re-parse via sitting_duck's `read_ast`
  against a tempfile and look up the matching node with pluckit's
  own selector compiler. When sitting_duck ships `ast_select` as a
  community-extension release, that lookup becomes a one-line swap.
- `blame()` is **deferred** — `duck_tails` has no `git_blame` table
  function, and implementing line-level blame via iterated history
  reads is prohibitively expensive. The method raises a
  `PluckerError` pointing at the upstream tracker.

- **Chain serializer/evaluator.** Every pluckit interaction is now a
  serializable `Chain` — Plucker args plus an ordered list of
  `ChainStep` operations. Chains can be:
  - Constructed from CLI args: `pluckit src/**/*.py find ".fn" count`
  - Parsed from JSON: `pluckit --json '{"source":[...],"steps":[...]}'`
  - Emitted as JSON: `pluckit --to-json src/**/*.py find ".fn" count`
  - Built in Python: `Chain(source=["src/**/*.py"], steps=[...])`
  - Evaluated: `chain.evaluate()` → JSON-serializable result dict
  - The chain that produced a result is always included in the output
    under the `"chain"` key for provenance/replay.
- **Selection stack** — `reset` (or bare `--`) clears the selection
  context and starts a new `find`. `pop` returns to the previous
  selection (e.g., from a narrowed `.fn#main` back to the enclosing
  `.cls` selection).
- **Project config** — `[tool.pluckit]` section in `pyproject.toml`
  for default plugins and named source shortcuts:
  ```toml
  [tool.pluckit]
  plugins = ["AstViewer"]

  [tool.pluckit.sources]
  code = "src/**/*.py"
  tests = "tests/**/*.py"
  ```
  CLI shortcuts: `-c`/`--code`, `-d`/`--docs`, `-t`/`--tests`.
- **`resolve_plugins()`** — string→class plugin lookup supporting both
  short names (`"AstViewer"`) and fully-qualified module paths
  (`"mypackage.plugins:MyPlugin"`).

### Changed

- **Breaking: CLI rewrite.** The `view` / `find` / `edit` subcommands
  are removed. Everything is now a chain:
  ```bash
  # Old: pluckit view ".fn#main" src/**/*.py
  # New: pluckit src/**/*.py find ".fn#main" view

  # Old: pluckit find ".fn:exported" --format names src/**/*.py
  # New: pluckit src/**/*.py find ".fn:exported" names

  # Old: pluckit edit ".fn#foo" --add-param "x: int" src/*.py
  # New: pluckit src/*.py find ".fn#foo" addParam "x: int"
  ```
  `pluckit init` is kept. `--version` and `--help` are kept.
- Bumped the `duckdb` dependency floor to `>=1.3.2` (required by
  `duck_tails`).
- **Breaking:** `Plucker.view()` and the module-level `pluckit.view()`
  now return a `View` object instead of a bare `str`. Code that
  treated the return as a string directly (e.g.,
  ``pluck.view(q).split("\n")``) must switch to the ``.markdown``
  accessor (``pluck.view(q).markdown.split("\n")``) or wrap with
  ``str(...)``. Idiomatic uses — ``print(v)``, ``f"{v}"``,
  ``"needle" in v``, ``v == ""`` — continue to work unchanged.

### Fixed

- `Selection.filter(name__startswith="_")` was matching every
  identifier because `_` is a SQL LIKE wildcard; now routes through
  `_esc_like` and emits `ESCAPE '\\'`.
- Compound selectors like `.fn:exported` silently dropped the
  pseudo-class in `_selector_to_where`; the compiler now parses
  `:pseudo` tokens from the selector tail and looks them up in the
  `PseudoClassRegistry`.

### Removed

- Removed the five history-related stubs (`history`, `at`, `diff`,
  `blame`, `authors`) from core `Selection`. They now live in the
  `History` pluckin; calling them without loading the pluckin
  raises a `PluckerError` with a pointer via `_KNOWN_PROVIDERS`.

## [0.1.0a1] — 2026-04-10

First public alpha. Query, view, and mutate all work end-to-end.

### Added

- **`Plucker` — a fluent entry point** that wraps a DuckDB connection, loads
  the `sitting_duck` community extension, and exposes `find()`, `view()`, and
  mutation methods on lazy `Selection` objects. Selections are DuckDB
  relations that chain filters, navigation, and terminal operations without
  materializing until necessary.

- **CSS-like selector language** (`.fn`, `.cls`, `.call`, `.fn#name`,
  `.fn:exported`, `.fn[name^=test_]`, `.cls#Foo .fn`, `.fn:has(.call#x)`)
  compiled to SQL WHERE fragments over sitting_duck's `read_ast()` table.
  Supports 27 languages via tree-sitter.

- **`AstViewer` plugin** — a CSS-stylesheet-style declaration language
  (`{ show: signature; }`, `{ show: outline; }`, `{ show: 10; }`, etc.)
  attached to selectors. Synthesized signatures from sitting_duck's native
  extraction columns. Multi-match signature queries collapse to a markdown
  table automatically.

- **Mutation engine with transactional rollback.** Line-granularity splicing
  with per-file snapshots, reverse-order application (later edits don't
  shift earlier line numbers), and re-parse validation. Any syntax error
  rolls back every affected file.

- **Mutation vocabulary:** `ReplaceWith`, `ScopedReplace`, `Prepend`,
  `Append`, `Wrap`, `Unwrap`, `Remove`, `Rename`, `AddParam`, `RemoveParam`,
  `AddArg`, `RemoveArg`, `ClearBody`, `InsertBefore`, `InsertAfter`.
  `InsertBefore`/`InsertAfter` take a CSS selector as the anchor and resolve
  it via a scoped AST sub-query — no heuristics.

- **`pluckit` CLI** with four subcommands:
  - `init` — install and verify the required DuckDB community extensions.
  - `view` — render matched code regions as markdown, reading queries from
    argv, a file, or stdin.
  - `find` — list matches for scripting. Four output formats: `locations`
    (file:line:name, default), `names`, `signature` (markdown table), `json`.
  - `edit` — apply structural mutations. Chainable within one invocation:
    multiple operations per group, multiple groups separated by `--`,
    with a real unified-diff preview in `--dry-run`.

- **Plugin system** — third-party plugins register new methods on
  `Selection`, new pseudo-classes for the selector compiler, and optional
  upgrades to existing methods (e.g., the `Calls` plugin will upgrade
  `callers()` with import-resolved results).

- **Cross-language indent detection** for mutations in Python, C++, Go,
  Java, TypeScript, and Rust. Body-frame indent is computed from file
  context, not hard-coded to 4 spaces.

- **CI scaffolding** — GitHub Actions workflow runs lint, pytest, and a
  wheel build on every push and PR.

### Infrastructure

- MIT licensed.
- PyPI distribution name: `ast-pluckit`. Import name, CLI name, and repo
  name are all `pluckit`. (The bare `pluckit` PyPI name is held by an
  abandoned 2019 project.)
- Python 3.10+ supported.
- Documentation published at [pluckit.readthedocs.io](https://pluckit.readthedocs.io).

### Known limitations

- Call graph, git history, and scope plugins are stubs — landing in v0.2.
- pluckit's selector compiler supports only a subset of sitting_duck's full
  selector language. Richer features like `:calls()`, `:matches()`, and
  `:scope()` work when calling `ast_select` directly against the underlying
  DuckDB connection.
- Mutations operate at line granularity because sitting_duck's `read_ast`
  does not yet expose byte offsets. Character-level insertions
  (`--insert-chars`) are reserved for v0.2.

[Unreleased]: https://github.com/teaguesterling/pluckit/compare/v0.1.0a1...HEAD
[0.1.0a1]: https://github.com/teaguesterling/pluckit/releases/tag/v0.1.0a1
