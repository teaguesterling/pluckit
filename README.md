# pluckit

*A fluent API for querying, viewing, and mutating source code. CSS selectors over ASTs, backed by DuckDB.*

pluckit lets you select code with CSS-like selectors, render it as formatted
source regions, and apply structural mutations — all from a single fluent API
or a compact CLI. Under the hood it's a thin Python layer over DuckDB with
the [sitting_duck](https://github.com/teaguesterling/sitting_duck) AST
extension, so queries compile to SQL and run against tree-sitter ASTs for
27 languages.

> **Status:** v0.1-alpha. Query, view, and mutate work end-to-end. Call graph,
> history, and scope plugins are v0.2. The package name is tentative —
> `pluckit` is taken on PyPI.

## Install

```bash
pip install -e .
```

pluckit needs DuckDB with the `sitting_duck` community extension. It's
auto-installed on first use.

## The CLI

### View — render matched code regions as markdown

```bash
# Show the full body of a function
pluckit view ".fn#parse_chain" training/chain_parser.py

# Just the signature
pluckit view ".fn#parse_chain { show: signature; }" training/chain_parser.py

# First 10 lines
pluckit view ".fn#parse_chain { show: 10; }" training/chain_parser.py

# Class outline — header + method signatures
pluckit view ".cls#ChainSampler" training/chain_sampler.py

# Multi-rule query (CSS-stylesheet style)
pluckit view ".fn { show: signature; } #main { show: body; }" training/generate.py

# Read the query from stdin
echo ".fn[name^=test_] { show: signature; }" | pluckit view - tests/*.py

# Or from a file
pluckit view --query-file audit.q src/**/*.py

# Multiple paths and glob patterns
pluckit view ".fn#parse" src/*.py lib/*.py
```

When a signature-mode query matches more than one function, the output
collapses into a markdown table — dramatically smaller than a code fence per
match:

```
| File               | Lines   | Signature                                  |
|---|---|---|
| src/validate.py    | 35-54   | `def _is_garbled(intent: str) -> bool:`    |
| src/validate.py    | 73-88   | `def _flatten_ops(comp: Any) -> list[str]:`|
| src/validate.py    | 102-196 | `def validate_chain(chain: str) -> Result:`|
```

### Edit — apply structural changes to matched nodes

All edits are **transactional**: if any affected file fails syntax re-validation
after splicing, every file is rolled back to its pre-edit state. Use `--dry-run`
to see how many matches each path would affect before writing.

```bash
# Replace a function's body entirely
pluckit edit ".fn#foo" --replace-with "def foo():\n    return 1" src/*.py

# Scoped find-and-replace within matched nodes (2-arg replace)
pluckit edit ".fn#validate" --replace "return None" "raise ValueError()" src/*.py

# Add a parameter to every matched function
pluckit edit ".fn:exported" --add-param "timeout: int = 30" src/**/*.py

# Remove matched nodes entirely
pluckit edit ".fn#deprecated_helper" --remove src/*.py

# Rename a definition (first name occurrence)
pluckit edit ".fn#old_name" --rename "new_name" src/*.py

# Insert code at the top of matched function bodies
pluckit edit ".fn:exported" --prepend "logger.debug('entered')" src/*.py

# Wrap matched nodes
pluckit edit ".call#query" --wrap "try:" "except DatabaseError:\n    raise" src/*.py

# See what would change without writing
pluckit edit ".fn#foo" --remove --dry-run src/*.py
```

## The Python API

```python
from pluckit import Plucker, AstViewer

pluck = Plucker(code="src/**/*.py", plugins=[AstViewer])

# Query
fns = pluck.find(".fn:exported")
print(fns.count())                  # 47
print(fns.names()[:5])              # ['authenticate', 'decode_jwt', ...]

# View
print(pluck.view(".fn#validate_token { show: signature; }"))

# Mutate (v0.1)
pluck.find(".fn#validate_token").replaceWith(
    "return None",
    "raise ValueError('token required')",
)
pluck.find(".fn:exported").addParam("timeout: int = 30")
```

### Module-level shortcuts

```python
from pluckit import view

# One-shot viewer query — creates an ephemeral Plucker
print(view(".fn#main { show: outline; }", code="src/**/*.py"))
```

## Selector syntax

Selectors mirror CSS but address AST nodes:

| Syntax                          | Meaning                                           |
|---------------------------------|---------------------------------------------------|
| `.fn`                           | All function definitions (cross-language alias)   |
| `.cls`, `.class`                | All class definitions                             |
| `.call`                         | All call expressions                              |
| `.fn#name`                      | Function named `name`                             |
| `.fn:exported`                  | Public (non-underscore) functions                 |
| `.fn[name^=test_]`              | Functions whose name starts with `test_`          |
| `.fn[name*=auth]`               | Functions whose name contains `auth`              |
| `.cls#Foo .fn`                  | Functions inside `class Foo`                      |
| `.fn:has(.call#execute)`        | Functions that call `execute()`                   |
| `.fn:not(:has(.try))`           | Functions with no try block                       |

sitting_duck's full selector language is richer than what pluckit currently
compiles — see its docs for `:calls()`, `:matches()`, `:scope()`, and the
call graph pseudo-elements. These work when you call `ast_select` directly
against the underlying DuckDB connection; pluckit's fluent layer supports
a growing subset.

## Viewer `show` modes

The viewer supports a small declaration language — CSS declaration blocks
attached to selectors:

| Show value   | Behavior                                                          |
|--------------|-------------------------------------------------------------------|
| `body`       | Full matched node text (default for functions, calls, statements) |
| `signature`  | Declaration line only (synthesized from native AST metadata)      |
| `outline`    | Class header + method signatures + dataclass fields (default for classes) |
| `enclosing`  | Walk up to the nearest scope and render *that* as body            |
| `N` (number) | First N lines of the body with `...` truncation marker            |

Rules compose like a stylesheet:

```css
.fn { show: signature; }            /* default most functions to signature */
.fn#main { show: body; }            /* except main — show its full body    */
.cls#Config { show: outline; }      /* Config class with methods listed   */
```

## Plugins

pluckit is composable. Core capabilities stay in `Selection`; anything that
depends on extra data or infrastructure moves to a plugin:

```python
from pluckit import Plucker, AstViewer

pluck = Plucker(
    code="src/**/*.py",
    plugins=[AstViewer],     # viewer with `show:` declarations
    # plugins=[Calls],       # call graph (v0.2)
    # plugins=[History],     # git history (v0.2)
    # plugins=[Scope],       # scope analysis (v0.2)
)
```

Plugins register new methods on `Selection`, new pseudo-classes for the
selector compiler, and optional upgrades for existing methods (e.g.,
fledgling-python can upgrade `callers()` with import-resolved results).

## Training data

The `training/` directory contains a synthetic training data generator that
produces (intent, chain) pairs for fine-tuning a small code model. It works
entirely from the API spec in `reference/api.yaml` — no pluckit runtime
needed. A ~40k-pair corpus (19% error-driven, 19% context-bearing) is
committed via git LFS under `training/`.

See `training/README.md` for generation and formatting.

## Architecture

```
   pluckit.Plucker              entry point, plugin registry, DuckDB context
        │
   pluckit.Selection            lazy DuckDB relation chain
        │                       query, filter, navigate, read, mutate
        ├── pluckit._sql        selector → SQL WHERE fragments
        │
   pluckit.plugins              optional capabilities
        ├── AstViewer           CSS-style viewer with `show:` declarations
        ├── Calls (v0.2)        call graph via name-join + plugin upgrades
        ├── History (v0.2)      git history via duck_tails
        └── Scope (v0.2)        read/write interface via flags byte
        │
   pluckit.mutation             byte-splice engine with transaction rollback
        └── pluckit.mutations   ReplaceWith, AddParam, Wrap, Rename, ...
```

All queries ultimately compile to SQL over sitting_duck's `read_ast()` table.
Mutations read files, apply string-level splices at line granularity, re-parse
to validate, and roll back on any syntax error.

## Contributing

Run tests:

```bash
pip install -e ".[dev]"
pytest
```

189 tests covering selectors, the Selection API, the plugin system, the
viewer, the CLI, and the mutation engine.
