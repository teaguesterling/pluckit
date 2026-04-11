# Changelog

All notable changes to this project are documented here. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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

### Changed

- Bumped the `duckdb` dependency floor to `>=1.3.2` (required by
  `duck_tails`).

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
