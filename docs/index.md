# pluckit

*A fluent API for querying, viewing, and mutating source code. CSS selectors over ASTs, backed by DuckDB.*

pluckit is a thin Python layer over [DuckDB](https://duckdb.org/) with the
[sitting_duck](https://github.com/teaguesterling/sitting_duck) community
extension. You write CSS-like selectors against tree-sitter ASTs for 27
languages; pluckit compiles them to SQL, runs them against `read_ast()`,
and gives you back a lazy `Selection` object that chains through filters,
navigation, view rendering, and structural mutations.

!!! info "Status"
    v0.1-alpha. Query, view, and mutate all work end-to-end. Call graph,
    git history, and scope plugins are landing in v0.2.

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

### Find

```bash
pluckit find ".fn:exported" src/**/*.py
# src/auth.py:14:authenticate
# src/auth.py:42:decode_jwt
# src/users.py:8:get_user
# ...

pluckit find ".fn[name^=test_]" --count tests/*.py
# 218
```

### View

```bash
pluckit view ".fn#validate_token { show: signature; }" src/**/*.py
# ```python
# def validate_token(token: str, *, clock_skew: int = 30) -> User:
# ```

pluckit view ".cls#Config" src/config.py
# Class outline: header + every method signature, inline
```

### Edit

```bash
# Add a parameter to every exported function AND update every call site
pluckit edit \
    ".fn:exported" --add-param "trace_id: str | None = None" \
    -- \
    ".call:exported" --add-arg "trace_id=trace_id" \
    src/**/*.py
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

    Complete reference for `pluckit view`, `find`, `edit`, and `init`,
    including every flag, output format, and chainable-edit pattern.

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
