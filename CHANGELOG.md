# Changelog

All notable changes to this project are documented here. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
