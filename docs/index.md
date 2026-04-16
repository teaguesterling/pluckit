# pluckit

*A fluent API for querying, viewing, and mutating source code. CSS selectors over ASTs, backed by DuckDB.*

pluckit is a thin Python layer over [DuckDB](https://duckdb.org/) with the
[sitting_duck](https://github.com/teaguesterling/sitting_duck) community
extension. You write CSS-like selectors against tree-sitter ASTs for 27
languages; pluckit compiles them to SQL, runs them against `read_ast()`,
and gives you back a lazy `Selection` object that chains through filters,
navigation, view rendering, and structural mutations.

!!! info "Status"
    Alpha. Query, view, mutate, call-graph, git history, and scope
    analysis all work end-to-end. See **What's new** below.

## What's new

Recent releases (v0.9 – v0.11.1):

- **`Isolated`** — `Selection.isolate()` extracts a code block along
  with its free-variable dependencies, classifying each name as a
  parameter, import, or builtin; renders as a standalone function or
  Jupyter cell.
- **Pagination** — `limit` / `offset` / `page` work as chain ops and
  as Selection methods. `Chain.evaluate()` attaches pagination
  metadata; `Chain.next_page` / `prev_page` / `goto_page` build
  follow-up chains; `Chain.with_total` computes the exact total on
  demand.
- **`Calls` and `Scope` pluckins** — call-graph (`callers`, `callees`,
  `references`) and scope-aware queries (`scope`, `defs`, `refs`) via
  sitting_duck's pseudo-elements.
- **`Selector` class** — a validated, serializable `str` subclass;
  drop-in replacement for bare selector strings, with
  `.validate()` / `.to_dict()` / `.to_json()` / `.to_argv()`.
- **Persistent AST cache** — `Plucker(cache=True)` or
  `[tool.pluckit] cache = true` materializes `read_ast` output into a
  `.pluckit.duckdb` file and re-parses only files whose mtime has
  changed.
- **`Pluckin` rename** — the extension-point class is now `Pluckin`
  (under `pluckit.pluckins`). The old `Plugin` / `pluckit.plugins`
  names remain as aliases for backward compatibility.

## Why pluckit

Most AST-aware tooling falls into one of two camps:

1. **Language-specific, prescriptive tools** (Python's `ast`, Rust's `syn`,
   comby, tree-sitter queries directly). Powerful, but tied to one
   language and one idiom.
2. **Generic text tools** (`grep`, `sed`, `rg`). Fast and universal, but
   blind to structure — every rename is a regex gamble.

pluckit sits in the middle. You get:

- **Cross-language selectors.** `.fn:exported` means "exported functions"
  in Python *and* Go *and* TypeScript *and* Rust. The semantic taxonomy
  lives in sitting_duck, not in hand-written rules.
- **SQL performance.** Every query is a DuckDB SQL query against the
  `read_ast()` table function. You can join against other tables,
  aggregate, window, and export to Parquet — all with the queries you
  already know.
- **Safe mutations.** The mutation engine snapshots every affected file,
  splices changes in reverse order, re-parses to validate, and rolls
  back everything on any syntax error. Atomic by default.

## Install

```bash
pip install ast-pluckit
```

The PyPI distribution name is `ast-pluckit` — the bare `pluckit` name is
held by an abandoned 2019 project on PyPI. The import name, CLI name,
and repository name are all `pluckit`.

After installing, run:

```bash
pluckit init
```

to eagerly install and verify the `sitting_duck` DuckDB community
extension. This also happens automatically the first time you run any
other command; `init` just gives you clearer diagnostics if something
fails.

## A 30-second tour

pluckit's CLI is a **chain** — source first, then operations. See the
[CLI reference](cli.md) for the full vocabulary.

### Find

```bash
pluckit src/**/*.py find ".fn:exported" names
# authenticate
# decode_jwt
# get_user
# ...

pluckit tests/*.py find ".fn[name^=test_]" count
# 218
```

### View

```bash
pluckit src/**/*.py find ".fn#validate_token" view ".fn#validate_token { show: signature; }"
# ```python
# def validate_token(token: str, *, clock_skew: int = 30) -> User:
# ```

pluckit src/config.py find ".cls#Config" view
# Class outline: header + every method signature, inline
```

### Edit

```bash
# Add a parameter to every exported function AND update every call site
pluckit src/**/*.py \
    find ".fn:exported" addParam "trace_id: str | None = None" \
    -- \
    find ".call:exported" addArg "trace_id=trace_id"
```

Every file in the transaction rolls back if any of them fails to re-parse.
Add `--dry-run` to see the exact unified diff before writing.

### Python API

```python
from pluckit import Plucker, AstViewer

pluck = Plucker(code="src/**/*.py", plugins=[AstViewer])

# Lazy selections chain
tests = pluck.find(".fn[name^=test_]").filter(".fn:not(:has(.try))")
print(tests.count())
print(tests.names()[:10])

# Render as markdown
print(pluck.view(".fn#validate_token { show: signature; }"))

# Mutate via the fluent API
pluck.find(".fn#old_name").rename("new_name")
```

## Where to next

<div class="grid cards" markdown>

-   :material-console:{ .lg .middle } **CLI Reference**

    ---

    Complete reference for the chain-based CLI — sources, step
    operations (query, navigation, mutation, pagination), global
    flags, JSON I/O, and `pluckit init`.

    [:octicons-arrow-right-24: Read the CLI docs](cli.md)

-   :material-language-python:{ .lg .middle } **Python API**

    ---

    The `Plucker` and `Selection` classes, the plugin system, and the
    full vocabulary of mutation methods.

    [:octicons-arrow-right-24: Read the API docs](api.md)

-   :material-code-tags:{ .lg .middle } **Selector & Declaration Language**

    ---

    How selectors map to AST nodes, the taxonomy of class names, the
    `{ show: ... }` declaration language, and the subset of
    sitting_duck's selector syntax that pluckit currently compiles.

    [:octicons-arrow-right-24: Read the selector docs](selectors.md)

-   :material-update:{ .lg .middle } **Changelog**

    ---

    Release notes and what changed between versions.

    [:octicons-arrow-right-24: Read the changelog](changelog.md)

</div>
