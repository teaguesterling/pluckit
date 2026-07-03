# Changelog

All notable changes to this project are documented here. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- **Selector alias drift** ([#10]): documented aliases now resolve to their
  documented targets instead of silently matching nothing or the wrong nodes.
  `.def`/`.let`/`.jump` were missing from the alias table; `.module`/`.ns`/
  `.namespace`/`.package` resolved to `ORGANIZATION_BLOCK` (every block)
  instead of `DEFINITION_MODULE`; `.null`/`.none` resolved to *string*
  literals and `.bool`/`.boolean` to an unmapped class — both now map to the
  engine's `LITERAL_ATOMIC` (new taxonomy class `.literal-atom`). Newly
  wired 1:1 equivalents verified against the installed sitting_duck build:
  `.assert` → `ERROR_THROW`, `.union` → `DEFINITION_CLASS`,
  `.del`/`.delete` → `EXECUTION_MUTATION`, `.comp`/`.comprehension` →
  `TRANSFORM_QUERY`, `.include` → `EXTERNAL_IMPORT`, `.extern`/`.ffi` →
  `EXTERNAL_FOREIGN`.
- **Unknown selector classes fail loudly** ([#10]): a class that would
  compile to a match-nothing predicate now raises
  `UnknownSelectorClassError` (with the working alternative in the message)
  instead of silently returning an empty result. This covers typos
  (`.fnn`), removed aliases, and the taxonomy classes the engine cannot
  express — notably `.self`/`.this`/`.super`, which previously resolved to
  `NAME_IDENTIFIER` and matched **every identifier**.
- **Alias substitution no longer rewrites attribute values** ([#10]):
  `.fn[name*=.str]` used to become `[name*=.literal_string]`. `[attr]`
  blocks, quoted strings, and non-selector pseudo-class arguments
  (`:match('…')`, `:contains(…)`) are now copied verbatim; aliases still
  resolve inside `:has()` / `:not()`.
- **`:line`/`:lines`/`:long`/`:complex` arguments are `int()`-validated**
  ([#10], LOW hardening): a non-integer argument such as
  `:line(5 OR 1=1)` now raises `SelectorArgError` instead of being
  interpolated raw into the post-filter WHERE clause (boolean-context
  SQL-arg injection, reachable via squackit's `pluck` MCP tool). An argless
  `:line` also raises instead of rendering malformed SQL. Same validation
  applied to `Selection.filter(...)` pseudo-classes (which now accept
  arguments, e.g. `.filter(":line(5)")`), `filter(field__gt=...)`
  comparison values, and `at_line`/`at_lines`.
- **`:contains` escapes LIKE wildcards**: `_`/`%` in the argument now match
  literally (previously `_` matched any character).

### Changed
- `docs/selectors.md` reconciled with the shipped taxonomy: documents the
  `.literal-atom` bucket (engine classifies booleans and null together),
  notes that `.member`/`.index` are equivalent today (single
  `COMPUTATION_ACCESS` type), documents the raising behavior for
  inexpressible aliases with alternatives, and corrects the false claim
  that `_` is auto-escaped in `[attr^=...]` values (the engine's LIKE has
  no ESCAPE clause; use `.filter(name__startswith=...)` for literal
  underscores).

[#10]: https://github.com/teaguesterling/pluckit/issues/10

## [0.14.0] - 2026-06-08

### Fixed
- `Plucker.docs()` now lazy-loads the `duckdb_markdown` community extension via
  `_Context._ensure_markdown_extension()`, so Pluckers configured with
  `docs=...` work in ephemeral envs (e.g. fresh CI) that don't have the
  extension pre-installed. Previously hit a raw
  `CatalogException: Table Function with name read_markdown_sections does not exist`;
  now installs from community on first use and raises a clean `PluckerError` if
  that fails. Pluckers that never call `.docs()` don't pay the install cost.
- `TestSearchWithoutFledgling::test_error_message_without_fts` assertion was
  pinned to `"FTS index"` but the actual error message varies by env:
  `"FTS search requires fledgling"` (no fledgling), `"FTS index not found"`
  (no FTS schema), `"FTS index is empty"` (schema present, no rows).
  Regex broadened to `r"FTS (index|search)"`.
- `test_fn.py @requires_fledgling` predicate now verifies the fledgling
  extension actually *loads* (not just that the Python module is importable),
  so tests that assert on specific fledgling SQL macros (`doc_outline`,
  `find_definitions`) skip cleanly in CI envs where the bundled extension
  doesn't match the duckdb version pip resolves.
- Internal: chain `except`'d errors with `raise ... from e` in `_assert_fts_index`
  so the underlying duckdb error is preserved in the traceback (B904).
- Cleared 15 long-standing ruff errors (B905, B904, B018, F401×4, F841,
  E741×5, I001×2) — `ruff check src tests` now clean on `main`.

### Changed
- **Selector matching is now delegated to sitting_duck's `ast_select` /
  `ast_select_from`.** pluckit's partial Python selector→SQL compiler is removed;
  sitting_duck is now the single source of truth for the *structural* grammar
  (classes, types, `#id`, `[attr]`, combinators, `:has` / `:not`, and its native
  pseudo-classes). This fixes silent over-matching: `:has()` / `:not()` /
  combinators that the old compiler dropped now work in `Plucker.find()` and chained
  `.find()` / `.ancestor()` (previously `.fn:has(.call#x)` collapsed to `.fn`).

### Added
- **Value-add pseudo-classes as post-filters.** `:exported` / `:private` (Python
  name convention), `:contains(s)` (`peek` substring), and `:line(n)` / `:lines(a,b)` /
  `:long(n)` / `:complex(n)` (line/size/complexity thresholds) are applied as a SQL
  `WHERE` over the delegated result — sitting_duck cannot express these natively. They
  have identical meaning in `find()` and `filter()`. (`:line` / `:lines` / `:long` /
  `:complex` now work in selector strings, not just deferred.)

### Removed
- Dropped the never-implemented `:wide` and `:last` pseudo-classes (both had no SQL
  template and silently matched everything).

## [0.13.0] — 2026-05-26

### Added (public API — SemVer-stable from here)
- `Plucker.pluckins` — public accessor for the loaded pluckin instances (in
  registration order). Lets downstream consumers (e.g. squackit) enumerate
  pluckins for tool discovery without reaching into the private `._registry`.
- `Chain.MUTATION_OPS` — public, stable set of mutation operation names
  (`_MUTATION_OPS` kept as a deprecated internal alias).
- Documented `Plucker.connection`'s contract: it is a `fledgling.Connection`
  (exposing `.con` / `.tools` / `.ensure_fts()`) when `fledgling-mcp` is
  installed, else a bare DuckDB connection — so consumers needing `.con`/`.tools`
  must declare a direct `fledgling-mcp` dependency.
- (Includes the `pluckit.pluckins.search` / `.viewer` surface.)

## [0.12.0] — 2026-04-18

### Added

- **`--diff` flag** — preview mutations as unified diff output without
  writing files. Works like `--dry-run` but outputs the actual diff to
  stdout, pipeable to `patch`, `git apply`, or pluckit's own `patch` op.
  `--diff` takes precedence when combined with `--dry-run`.
- **`patch` mutation** — apply a unified diff or raw replacement text to
  matched nodes. Auto-detects unified diffs (by `---` / `diff --git`
  prefix); everything else is treated as raw replacement. Strict context
  matching in v1 — hunks must match exactly or `PluckerError` is raised.
  Registered as a chain op (`Selection.patch(content)`).
- **`@file` argument syntax** — any string argument in a chain step can
  reference a file with `@path`. The file's content replaces the argument
  at evaluation time. `@@path` escapes to literal `@path`. In JSON,
  `{"file": "path"}` is an alternative to `"@path"`. Resolution is
  relative to CWD and happens at eval time, keeping serialized chains
  portable.

### Fixed

- **`--dry-run` now works.** The flag was parsed into `Chain.dry_run`
  but never checked during `evaluate()`. Mutations now run, roll back,
  and report `{"applied": False, "dry_run": True}`.
- **`--diff` and `--dry-run` can appear after steps** in the CLI, not
  just before the source. Both positions are supported.

## [0.11.1] — 2026-04-14

### Changed

- **Pagination `total` is now lazy.** `Chain.evaluate()` no longer runs
  a second count query to populate `page.total` by default. The field
  is `None` in the result envelope; call `Chain.with_total(result)` to
  fill it in (costs one extra query). This halves the query cost of
  paginated chains when the caller doesn't need the exact total.
- **`has_more` is now heuristic** when `total` is unknown:
  `data_length < limit` → definitively `False`; `data_length >= limit`
  → conservatively `True`. `Chain.with_total(result)` refines
  `has_more` to exact.

### Added

- `Chain.with_total(result)` classmethod — fills in `page.total` and
  refines `has_more` on a paginated result. Returns the mutated result
  for chaining. No-op on unpaginated results.

### Documented

- `_attach_pagination_metadata` docstring now calls out two edge
  cases: `page N SIZE` + subsequent `limit`/`offset` overrides
  (well-defined but potentially confusing — use one or the other);
  and `limit` before a mutation restricts the mutation to the first
  N matches (correct but surprising).

## [0.11.0] — 2026-04-14

### Added

- Chain-level pagination. New ops limit / offset / page in the
  chain vocabulary, with matching Selection methods. Chain.evaluate()
  result envelope gains source_chain + page metadata (offset, limit,
  total, has_more) whenever any pagination op appears in the chain.
  Consumers can rebuild the "next page" chain by taking source_chain
  and appending a new offset/limit. No MCP-layer wrapping needed.
- Pagination navigation helpers: `Chain.next_page(result)`,
  `Chain.prev_page(result)`, `Chain.goto_page(result, n)`. Each takes
  an evaluated paginated result dict and returns a new Chain ready to
  evaluate for the requested page (or `None` when navigation isn't
  possible — no more pages, already at offset 0, or the result wasn't
  paginated).

## [0.10.0] — 2026-04-14

### Added

- **`Isolated` type** — new terminal on `Selection` via `.isolate()` that
  extracts a block of code (e.g., a function body, a line range) as a
  standalone unit. It identifies free variables read by the block but
  defined outside it, classifies each as Python builtin / imported
  symbol / free parameter, and can render the result as a standalone
  function (`.as_function()`) or a Jupyter cell (`.as_jupyter_cell()`).
  Supports `to_dict` / `from_dict` / `to_json` / `from_json` for
  transport. Useful for extracting runnable snippets that an agent or
  user can paste into a notebook or test.

### Notes

- The `Calls` pluckin's implementation (callers/callees/references)
  will simplify once sitting_duck ships a structured `scope` struct
  (`{current, function, class, module, stack}`) on every `read_ast`
  row. The current provenance-walk + `ast_select` round-trip is a
  workaround for that missing schema — when upstream lands, the per-
  file fan-out collapses substantially (filter directly on
  `scope.function` for callers). See docstring in
  `src/pluckit/pluckins/calls.py`.

## [0.9.0] — 2026-04-14

Brand-consistency rename for the plugin system. Plugin authors should
migrate module paths (`pluckit.plugins.*` → `pluckit.pluckins.*`). The
class-level aliases (`Plugin = Pluckin`) keep existing source compiling
unchanged.

### Changed

- **Plugin base class renamed `Plugin` → `Pluckin`** (and `PluginRegistry`
  → `PluckinRegistry`) for brand consistency with the rest of the
  pluckit family ("pluckin" = pluckit + plugin) and to disambiguate
  from generic Python plugins in multi-plugin-system contexts (MCP,
  LSP, etc.). Old names are kept as aliases — existing code importing
  `Plugin` and `PluginRegistry` continues to work without modification.
- **Breaking: `pluckit.plugins` package renamed to `pluckit.pluckins`.**
  Imports of the form `from pluckit.plugins.X import Y` must be updated
  to `from pluckit.pluckins.X import Y`. The class-level aliases
  (`Plugin = Pluckin`, `PluginRegistry = PluckinRegistry`) remain for
  source-level backward compat, but the package path itself is a clean
  break — there is no shim at the old `pluckit.plugins` path. Top-level
  imports (`from pluckit import AstViewer`, etc.) are unaffected.

### Added

- `PluckinRegistry.pluckins` property — returns the list of unique
  registered pluckin instances. Designed for downstream consumers
  (e.g., squackit) to enumerate pluckins for tool/integration
  discovery without coupling pluckit to specific consumer APIs.

## [0.8.0] — 2026-04-14

Substantial release adding chain serialization, MCP transport,
persistent AST caching, and three new pluckins (Calls, Scope, History).
Breaking changes to the CLI surface — see "Changed" below.

### Added

- **Calls pluckin** — `callers()`, `callees()`, `references()` methods
  on Selection, wrapping sitting_duck's `::callers` / `::callees` /
  `::references` pseudo-elements. Load with `Plucker(plugins=[Calls])`.
- **Scope pluckin** — `scope()`, `defs()`, `refs()` methods on
  Selection. `scope()` wraps sitting_duck's `::scope` pseudo-element
  (returns enclosing scope hierarchy). `defs()` / `refs()` filter by
  `scope_id` and the flags byte (IS_DEFINITION / IS_REFERENCE).
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
- `Commit` dataclass exported from `pluckit` and `pluckit.pluckins`
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

## [0.7.0] — 2026-04-12

Infrastructure sync with the fledgling-mcp ecosystem. No new pluckit-
facing features; the version bump was required to align with a
fledgling release. Functionally equivalent to the tip of the
`feat/training-data-generator` branch at that point (pre-chain,
pre-MCP-serialization, pre-cache).

### Added

- Fledgling kwargs pass-through (`profile`, `modules`, `init`) on
  `Plucker.__init__` and `_Context.__init__`.
- Public `Plucker.connection` property exposing the underlying DuckDB
  connection (a `fledgling.Connection` proxy when fledgling is
  installed, otherwise a bare DuckDB connection).

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

[Unreleased]: https://github.com/teaguesterling/pluckit/compare/v0.11.1...HEAD
[0.11.1]: https://github.com/teaguesterling/pluckit/releases/tag/v0.11.1
[0.11.0]: https://github.com/teaguesterling/pluckit/releases/tag/v0.11.0
[0.10.0]: https://github.com/teaguesterling/pluckit/releases/tag/v0.10.0
[0.9.0]: https://github.com/teaguesterling/pluckit/releases/tag/v0.9.0
[0.8.0]: https://github.com/teaguesterling/pluckit/releases/tag/v0.8.0
[0.7.0]: https://github.com/teaguesterling/pluckit/releases/tag/v0.7.0
[0.1.0a1]: https://github.com/teaguesterling/pluckit/releases/tag/v0.1.0a1
