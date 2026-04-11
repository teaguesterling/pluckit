# Python API

pluckit's Python API is built around three types: `Plucker` (the entry
point), `Selection` (a lazy query chain), and `Plugin` (the extension
point). Everything else is either a mutation class or a convenience
wrapper around these.

```python
from pluckit import Plucker, AstViewer

pluck = Plucker(code="src/**/*.py", plugins=[AstViewer])
```

---

## `Plucker`

The entry point. Wraps a DuckDB connection, loads the `sitting_duck`
extension on first use, and exposes methods for finding, viewing, and
mutating code.

### Constructor

```python
Plucker(
    code: str | list[str] | None = None,
    *,
    plugins: list[Plugin | type[Plugin]] = (),
    repo: str | None = None,
    db: duckdb.DuckDBPyConnection | None = None,
)
```

| Parameter | Description                                                              |
|-----------|--------------------------------------------------------------------------|
| `code`    | Glob pattern(s) or explicit file list for the source corpus              |
| `plugins` | Plugin classes or instances to register                                  |
| `repo`    | Repository root for relative paths (default: current working directory)  |
| `db`      | An existing DuckDB connection to reuse (default: create a fresh one)     |

### Methods

#### `find(selector: str) -> Selection`

Run a selector against the configured code corpus and return a lazy
`Selection`:

```python
fns = pluck.find(".fn:exported")
```

#### `view(selector: str, *, format: str = "markdown") -> str`

Render matched nodes as markdown (the `AstViewer` plugin must be
registered). Returns a :class:`View` object — see below.

```python
print(pluck.view(".fn#main { show: signature; }"))
```

#### `source(glob: str) -> Source`

Create a `Source` handle for ad-hoc queries against a different glob
without creating a whole new Plucker.

---

## `Selection`

A lazy DuckDB relation. Every method on `Selection` returns another
`Selection` — nothing materializes until you call a terminal method.

### Query composition

```python
# Refine a selection
tests = pluck.find(".fn[name^=test_]")
without_try = tests.filter(".fn:not(:has(.try))")

# Navigate
classes = pluck.find(".cls")
methods = classes.descendants(".fn")
```

| Method                           | Description                                  |
|----------------------------------|----------------------------------------------|
| `find(sel)`                      | Refine the selection with another selector   |
| `filter(sel)`                    | Alias for `find`; semantic clarity           |
| `descendants(sel)`               | Matches anywhere under the selection         |
| `children(sel)`                  | Direct children only                         |
| `ancestors(sel)`                 | Walk up the AST                              |
| `siblings(sel)`                  | Nodes sharing a parent                       |
| `first()`, `last()`, `nth(n)`    | Positional selection                         |
| `limit(n)`, `offset(n)`          | Slice the result set                         |

### Terminal methods

These materialize the relation and return Python data:

| Method                | Returns          | Description                             |
|-----------------------|------------------|-----------------------------------------|
| `count()`             | `int`            | Number of matched nodes                 |
| `names()`             | `list[str]`      | Identifier names (deduplicated)         |
| `files()`             | `list[str]`      | Distinct source files containing matches|
| `rows()`              | `list[Node]`     | Full AST rows with all sitting_duck cols|
| `read()`              | `list[str]`      | Raw source text of each matched node    |
| `to_df()`             | `pd.DataFrame`   | Pandas DataFrame (requires pandas)      |

### Mutation methods

Every mutation method returns a refreshed `Selection` (so you can chain
further queries, though most callers don't). All mutations are
transactional at the invocation level — the enclosing call is atomic,
and multiple fluent mutations are independent transactions.

| Method                                   | Description                                      |
|------------------------------------------|--------------------------------------------------|
| `replaceWith(text)`                      | Replace entire matched node                      |
| `replaceWith(old, new)`                  | String-level replace within matched node         |
| `prepend(text)`                          | Prepend lines to the matched body                |
| `append(text)`                           | Append lines to the matched body                 |
| `insertBefore(anchor, text)`             | Insert lines before an anchor selector           |
| `insertAfter(anchor, text)`              | Insert lines after an anchor selector            |
| `wrap(before, after)`                    | Wrap with surrounding text                       |
| `unwrap()`                               | Inverse of wrap                                  |
| `addParam(param)`                        | Add a parameter to every matched function        |
| `removeParam(name)`                      | Remove a parameter by name                       |
| `addArg(expr)`                           | Add an argument to every matched call            |
| `removeArg(name)`                        | Remove a keyword argument by name                |
| `rename(new_name)`                       | Rename the first name occurrence                 |
| `clearBody()`                            | Replace body with `pass` / `{}`                  |
| `remove()`                               | Delete the matched node                          |

Example:

```python
pluck.find(".fn#validate_token").replaceWith(
    "return None",
    "raise ValueError('token required')",
)
pluck.find(".fn:exported").addParam("timeout: int = 30")
```

### Reading matched source

```python
for node in pluck.find(".fn#validate").rows():
    print(f"{node.file_path}:{node.start_line}")
    print(node.source_text)
```

`Selection.rows()` returns `Node` dataclasses with all of sitting_duck's
columns — `node_id`, `type`, `semantic_type`, `name`, `start_line`,
`end_line`, `parent_id`, `flags`, and the native extraction columns
(`signature_type`, `parameters`, `modifiers`, `annotations`).

---

## Module-level shortcuts

For one-shot queries you don't need a persistent Plucker for:

```python
from pluckit import view, find

print(view(".fn#main { show: outline; }", code="src/**/*.py"))

for path, line, name in find(".fn:exported", code="src/**/*.py"):
    print(f"{path}:{line}:{name}")
```

These create an ephemeral Plucker, run the query, and tear it down.

---

## `View` and `ViewBlock`

`Plucker.view()` and the module-level `pluckit.view()` return a `View`
object — not a plain string. A `View` behaves like a string for the
common "print the rendered markdown" case, but also exposes structured
metadata about the blocks it contains.

```python
from pluckit import Plucker, AstViewer, View, ViewBlock

pluck = Plucker(code="src/**/*.py", plugins=[AstViewer])
result: View = pluck.view(".fn:exported { show: signature; }")

# Rendered output — backward compatible with the v0.1 bare-string return
print(result)                    # prints the markdown
print(str(result))               # same thing
print(result.markdown)           # explicit accessor
assert "def authenticate" in result   # __contains__ checks the markdown

# Structured access
print(result.files)              # ['src/auth.py', 'src/users.py', ...]
print(len(result))               # number of blocks
for block in result:             # iterate as ViewBlock
    print(block.name, block.start_line, block.show)

# JSON export
import json
print(json.dumps(result.to_dict(), indent=2))
```

### `View` methods and properties

| Member            | Type                    | Description                                  |
|-------------------|-------------------------|----------------------------------------------|
| `markdown`        | `str`                   | Full rendered output                         |
| `blocks`          | `list[ViewBlock]`       | Fresh list of contained blocks               |
| `files`           | `list[str]`             | Distinct file paths, in first-seen order     |
| `query`           | `str`                   | The query string that produced this view     |
| `format`          | `str`                   | Output format (`markdown` in v0.1)           |
| `to_dict()`       | `dict`                  | JSON-serializable representation             |
| `str(v)` / `print`| `str`                   | Same as `.markdown`                          |
| `len(v)`          | `int`                   | Number of blocks                             |
| `bool(v)`         | `bool`                  | `False` for empty views                      |
| `for b in v`      | `Iterator[ViewBlock]`   | Iterate blocks in render order               |
| `v[i]` / `v[a:b]` | `ViewBlock` / `list`    | Indexing and slicing                         |
| `"s" in v`        | `bool`                  | Substring check against `.markdown`          |

### `ViewBlock` fields

Each `ViewBlock` is a frozen dataclass with:

| Field          | Type          | Description                                        |
|----------------|---------------|----------------------------------------------------|
| `markdown`     | `str`         | Rendered content for this block                    |
| `rule`         | `Rule`        | The query rule that produced it                    |
| `show`         | `str`         | Resolved show mode (`body`, `signature`, …)        |
| `file_path`    | `str \| None` | Source file — `None` for aggregates                |
| `start_line`   | `int \| None` | Start line — `None` for aggregates                 |
| `end_line`     | `int \| None` | End line — `None` for aggregates                   |
| `name`         | `str \| None` | Identifier name, if any                            |
| `node_type`    | `str \| None` | AST node type (`function_definition`, …)          |
| `language`     | `str \| None` | Source language                                    |
| `is_aggregate` | `bool`        | `True` for multi-match signature tables and such   |

**Aggregate blocks.** When a rule like `.fn { show: signature; }` matches
many nodes, the viewer auto-collapses the output into a single markdown
table. That collapse produces a single `ViewBlock` with `is_aggregate =
True` and `file_path`, `start_line`, `end_line` all `None`. Use
`block.is_aggregate` (or `block.file_path is None`) to distinguish
per-node blocks from aggregates.

---

## Plugins

pluckit is composable. Core capabilities live on `Selection`; anything
that depends on extra infrastructure moves into a plugin.

```python
from pluckit import Plucker, AstViewer

pluck = Plucker(
    code="src/**/*.py",
    plugins=[
        AstViewer,   # viewer with { show: ... } declarations
        # Calls,     # call graph (v0.2)
        # History,   # git history via duck_tails (v0.2)
        # Scope,     # read/write scope analysis (v0.2)
    ],
)
```

### Writing a plugin

A plugin is a subclass of `pluckit.plugins.Plugin`:

```python
from pluckit.plugins import Plugin

class WordCount(Plugin):
    name = "wordcount"

    methods = {
        "word_count": lambda self: sum(
            len(text.split()) for text in self.read()
        ),
    }

    pseudo_classes = {
        ":long": "end_line - start_line > 50",
    }
```

| Class attribute   | Purpose                                                        |
|-------------------|----------------------------------------------------------------|
| `name`            | Unique plugin identifier                                       |
| `methods`         | Dict of method name → function to install on `Selection`       |
| `pseudo_classes`  | Dict of `:name` → SQL WHERE fragment                           |
| `upgrades`        | Dict of method name → function to override an existing method  |
| `setup(ctx)`      | Optional hook called when the plugin is registered             |

Plugins can also register new semantic-type aliases by updating
`pluckit.selectors.ALIASES`, but that's considered advanced — most
plugins only need `methods` and `pseudo_classes`.

### `History` — git history on AST selections

```python
from pluckit import Plucker, History

pluck = Plucker(code="src/**/*.py", plugins=[History])
fn = pluck.find(".fn#validate_token")

# Every commit that touched the function's file, most-recent-first
for commit in fn.history():
    print(f"{commit.hash[:8]} {commit.author_name}: {commit.message}")

# Distinct authors (email) for those commits
print(fn.authors())

# The function's body as it was at an old revision — AST-aware, so
# it matches by (name, type), not by today's line range.
print(fn.at("v0.1.0")[0])

# Unified diff between HEAD and the old revision, per matched node.
print(fn.diff("v0.1.0")[0])
```

| Method            | Returns               | Notes                                          |
|-------------------|-----------------------|------------------------------------------------|
| `history()`       | `list[Commit]`        | Deduplicated, sorted by date descending        |
| `authors()`       | `list[str]` (emails)  | Sorted                                         |
| `at(rev)`         | `list[str]`           | One entry per matched node; `""` if not found  |
| `diff(rev)`       | `list[str]`           | Unified diff per matched node                  |
| `blame()`         | (raises)              | **Deferred** — upstream-blocked on `duck_tails`|

**Dependencies.** `History` requires the `duck_tails` DuckDB community
extension (for `git_read`) and the `git` binary on `PATH` (for `git log
--follow`). pluckit auto-installs `duck_tails` on first use; run
`pluckit init` to provision eagerly.

**Rename handling.** `history()` uses `git log --follow`, so commits
that touched a file under a previous name are included. `at(rev)` /
`diff(rev)` locate the node at the historical revision by name+type,
so a pure rename is tracked as long as the node's name survives.
Structural refactors (a method being pulled out of a class, a
function being split) are not automatically tracked.

---

## Error handling

Every recoverable error raises `PluckerError`:

```python
from pluckit import Plucker, PluckerError

try:
    pluck = Plucker(code="src/**/*.py")
    pluck.find(".fn").replaceWith("def broken(:::")
except PluckerError as e:
    print(f"Mutation failed: {e}")
    # All affected files have already been rolled back to their
    # pre-mutation state.
```

`PluckerError` is raised for:

- Failed extension installation (`pluckit init` will reproduce this)
- Selector compilation errors
- Mutation syntax errors (with automatic rollback)
- Invalid paths, missing files, parse failures
