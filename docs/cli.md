# CLI Reference

pluckit uses a **chain-based** CLI where a source comes first, followed
by one or more operation steps. There are no subcommands for querying,
viewing, or editing — everything is expressed as a chain of steps.

```bash
pluckit [FLAGS] SOURCE STEP [STEP...] [-- STEP...]
pluckit --json JSON_STRING
pluckit init [--force-reinstall] [--quiet]
```

Run `pluckit --help` for a summary of flags and operations.

---

## Sources

The first positional argument is the **source** — a file path, glob
pattern, or a named shortcut:

```bash
# Glob pattern
pluckit "src/**/*.py" find ".fn:exported" names

# Explicit file
pluckit src/auth.py find ".fn#validate_token" text

# Named shortcuts
pluckit -c find ".fn:exported" count      # --code
pluckit -d find ".cls" names              # --docs
pluckit -t find ".fn[name^=test_]" names  # --tests
```

Shortcuts (`-c`/`--code`, `-d`/`--docs`, `-t`/`--tests`) resolve via
the `[tool.pluckit.sources]` table in `pyproject.toml`. See
[Configuration](#configuration) below.

---

## Steps

After the source, every token is part of a **step chain**. Each
recognized operation name starts a new step. Positional tokens between
operation names are arguments to that step. `--key=value` tokens become
keyword arguments.

```bash
pluckit src/**/*.py find ".fn:exported" filter --min-lines=10 text
#       ^^^^^^^^^^^ ^^^^ ^^^^^^^^^^^^^^ ^^^^^^ ^^^^^^^^^^^^^^^ ^^^^
#       source      op   arg            op     kwarg           op
```

A bare `--` is equivalent to the `reset` operation — it clears the
current selection and starts a new find context:

```bash
pluckit src/**/*.py find ".fn#foo" rename "bar" -- find ".call#foo" replace "foo" "bar"
```

### Query operations

| Operation        | Arguments          | Description                            |
|------------------|--------------------|----------------------------------------|
| `find`           | `SELECTOR`         | Select nodes matching a CSS selector   |
| `filter`         | `[--kwargs]`       | Narrow the current selection           |
| `not_`           |                    | Invert the current selection           |

### Navigation operations

| Operation        | Arguments          | Description                            |
|------------------|--------------------|----------------------------------------|
| `parent`         |                    | Move to parent nodes                   |
| `children`       |                    | Move to direct children                |
| `siblings`       |                    | Nodes sharing a parent                 |
| `ancestor`       |                    | Walk up the AST                        |
| `next`           |                    | Next sibling                           |
| `prev`           |                    | Previous sibling                       |
| `containing`     | `TEXT`             | Nodes whose source contains text       |
| `at_line`        | `N`                | Node at a specific line number         |
| `at_lines`       | `START END`        | Nodes within a line range              |

### Terminal operations

| Operation        | Arguments          | Description                            |
|------------------|--------------------|----------------------------------------|
| `count`          |                    | Print the number of matches            |
| `names`          |                    | Print one identifier name per line     |
| `text`           |                    | Print the source text of each match    |
| `attr`           | `NAME`             | Print a named attribute of each match  |
| `complexity`     |                    | Print cyclomatic complexity            |
| `materialize`    |                    | Print matches as JSON                  |

### Pagination operations

| Operation        | Arguments          | Description                            |
|------------------|--------------------|----------------------------------------|
| `limit`          | `N`                | Take only the first N matches          |
| `offset`         | `N`                | Skip the first N matches               |
| `page`           | `N SIZE`           | Page N (0-indexed), page size SIZE     |

When any pagination op appears in a chain, the result JSON gains
`source_chain` + `page: {offset, limit, total, has_more}` fields.
`total` is `None` by default (lazy); `has_more` is heuristic until
`total` is computed.

### Mutation operations

| Operation        | Arguments          | Description                            |
|------------------|--------------------|----------------------------------------|
| `addParam`       | `PARAM`            | Add a parameter to matched functions   |
| `removeParam`    | `NAME`             | Remove a parameter by name             |
| `addArg`         | `EXPR`             | Add an argument to matched calls       |
| `removeArg`      | `NAME`             | Remove a keyword argument by name      |
| `rename`         | `NEW`              | Rename the matched definition          |
| `prepend`        | `TEXT`             | Prepend lines to the body              |
| `append`         | `TEXT`             | Append lines to the body               |
| `insertBefore`   | `ANCHOR CODE`      | Insert code before an anchor selector  |
| `insertAfter`    | `ANCHOR CODE`      | Insert code after an anchor selector   |
| `wrap`           | `BEFORE AFTER`     | Wrap the matched node                  |
| `unwrap`         |                    | Remove enclosing context               |
| `remove`         |                    | Delete the matched node                |
| `clearBody`      |                    | Replace body with `pass` / `{}`        |
| `replaceWith`    | `TEXT`             | Replace the entire matched node        |
| `replace`        | `OLD NEW`          | String-level replace within the node   |

### Plugin operations

| Operation        | Arguments          | Description                            |
|------------------|--------------------|----------------------------------------|
| `view`           | `[QUERY]`          | Render matched nodes as markdown       |
| `history`        |                    | Show git history for matched nodes     |
| `authors`        |                    | List distinct commit authors           |
| `at`             | `REV`              | Show the node at a historical revision |
| `diff`           | `REV`              | Unified diff against a revision        |
| `blame`          |                    | Annotate matched nodes with blame info |

### Control operations

| Operation        | Arguments          | Description                            |
|------------------|--------------------|----------------------------------------|
| `reset`          |                    | Clear selection, start fresh (same as bare `--`) |
| `pop`            |                    | Return to the previous selection       |

---

## Global Flags

| Flag                  | Description                                           |
|-----------------------|-------------------------------------------------------|
| `--plugin NAME`       | Load a named plugin                                   |
| `--repo DIR`          | Repository root for relative paths (default: cwd)     |
| `--dry-run`, `-n`     | Show what would change without writing                 |
| `--json JSON`         | Run a chain from a JSON string (see [JSON I/O](#json-io)) |
| `--to-json`           | Print the chain as JSON instead of executing it        |
| `--version`           | Print version and exit                                 |
| `-h`, `--help`        | Print help and exit                                    |

---

## Result Formatting

The terminal operation you choose determines the output format:

| Terminal       | Output                                                  |
|----------------|---------------------------------------------------------|
| `count`        | A single number on stdout                               |
| `names`        | One identifier name per line                            |
| `text`         | Source text of each matched node, separated by newlines  |
| `view`         | Rendered markdown (requires `AstViewer` plugin)         |
| `materialize`  | JSON array of matched nodes                             |
| mutations      | A summary line printed to stderr                        |

When `--dry-run` is active, mutation operations print a unified diff to
stdout and a summary to stderr. Pipe the diff into `patch` or
`git apply` to stage changes manually.

---

## `pluckit init`

The only named subcommand. Eagerly installs and verifies the DuckDB
community extensions pluckit depends on. This happens lazily on first
use of any other command, but running it explicitly gives clearer
diagnostics if anything fails.

```bash
pluckit init [--force-reinstall] [--quiet]
```

### Options

| Flag                | Description                                         |
|---------------------|-----------------------------------------------------|
| `--force-reinstall` | Re-install extensions even if they already load     |
| `--quiet`           | Suppress success messages; only print errors        |

### Exit codes

| Code | Meaning                                                       |
|------|---------------------------------------------------------------|
| `0`  | Required extensions are ready (optional ones may be missing)  |
| `1`  | A required extension could not be installed or loaded         |

### Example

```bash
$ pluckit init
  sitting_duck (required): loaded
  duck_tails (optional): loaded

pluckit init: all extensions ready.
```

---

## JSON I/O

Chains can be expressed as JSON for programmatic use — pass them via
`--json` on the command line or pipe them to tools that generate
pluckit invocations.

```json
{
  "source": ["src/**/*.py"],
  "plugins": ["AstViewer"],
  "steps": [
    {"op": "find", "args": [".fn:exported"]},
    {"op": "count"}
  ]
}
```

```bash
# From the command line
pluckit --json '{"source": ["src/**/*.py"], "steps": [{"op": "find", "args": [".fn:exported"]}, {"op": "count"}]}'

# Inspect what a CLI invocation would look like as JSON
pluckit --to-json src/**/*.py find ".fn:exported" count
```

Each step object has:

| Field    | Type          | Description                              |
|----------|---------------|------------------------------------------|
| `op`     | `str`         | Operation name (e.g. `find`, `count`)    |
| `args`   | `list[str]`   | Positional arguments (optional)          |
| `kwargs` | `dict`        | Keyword arguments (optional)             |

Top-level fields:

| Field     | Type          | Description                              |
|-----------|---------------|------------------------------------------|
| `source`  | `list[str]`   | File paths or glob patterns              |
| `plugins` | `list[str]`   | Plugin names to load (optional)          |
| `steps`   | `list[step]`  | Ordered list of step objects             |

---

## Configuration

pluckit reads configuration from the `[tool.pluckit]` table in
`pyproject.toml`:

```toml
[tool.pluckit]
plugins = ["AstViewer"]
cache = true                      # opt-in persistent AST cache
cache_path = ".pluckit.duckdb"    # custom cache location

[tool.pluckit.sources]
code = ["src/**/*.py"]
docs = ["docs/**/*.md"]
tests = ["tests/**/*.py"]
```

The `plugins` list names plugins to load by default. The
`[tool.pluckit.sources]` table defines named shortcuts that the `-c`,
`-d`, and `-t` flags (and any custom names) resolve against.

Set `cache = true` to enable the persistent AST cache — pluckit
materializes `read_ast` output into per-pattern tables in a
`.pluckit.duckdb` file and re-parses only files whose mtime has
changed. Override the file location with `cache_path`.

---

## Examples

```bash
# Count all exported functions
pluckit src/**/*.py find ".fn:exported" count

# List function names in a file
pluckit src/auth.py find ".fn" names

# View a specific function as markdown
pluckit src/auth.py find ".fn#validate_token" view

# Dry-run a rename
pluckit -n src/*.py find ".fn#old_name" rename "new_name"

# Chain multiple operations with reset
pluckit src/**/*.py find ".fn#foo" rename "bar" -- find ".call#foo" replace "foo" "bar"

# Navigate: find classes then their methods
pluckit src/**/*.py find ".cls:exported" children names

# Use a named source shortcut
pluckit -c find ".fn:exported" count

# Add a parameter to every exported function
pluckit src/**/*.py find ".fn:exported" addParam "timeout: int = 30"

# Get the source text of a function at a historical revision
pluckit src/auth.py find ".fn#validate_token" at v0.1.0

# View complexity of matched functions
pluckit src/**/*.py find ".fn" complexity

# JSON round-trip
pluckit --to-json src/**/*.py find ".fn:exported" count | pluckit --json "$(cat -)"
```

---

## Migration Guide

The old CLI had separate `view`, `find`, and `edit` subcommands. These
are gone. Everything is now a chain where the source comes first,
followed by operations.

### `view` subcommand

```bash
# Old
pluckit view ".fn#main" src/**/*.py
pluckit view ".fn#main { show: signature; }" src/**/*.py

# New
pluckit src/**/*.py find ".fn#main" view
pluckit src/**/*.py find ".fn#main" view ".fn#main { show: signature; }"
```

### `find` subcommand

```bash
# Old
pluckit find ".fn:exported" --format names src/**/*.py
pluckit find ".fn:exported" --count src/**/*.py
pluckit find ".cls" --format json src/models.py

# New
pluckit src/**/*.py find ".fn:exported" names
pluckit src/**/*.py find ".fn:exported" count
pluckit src/models.py find ".cls" materialize
```

### `edit` subcommand

```bash
# Old
pluckit edit ".fn#foo" --add-param "x: int" src/*.py
pluckit edit ".fn#deprecated_helper" --remove src/*.py
pluckit edit --dry-run ".fn#top_level_fn" --rename renamed src/sample.py
pluckit edit ".cls#Foo .fn#__init__" --add-param "foo: int = 30" \
                                     --append-lines "self.foo = foo" \
    -- ".call#Foo" --add-arg "foo=10" src/**/*.py

# New
pluckit src/*.py find ".fn#foo" addParam "x: int"
pluckit src/*.py find ".fn#deprecated_helper" remove
pluckit -n src/sample.py find ".fn#top_level_fn" rename "renamed"
pluckit src/**/*.py find ".cls#Foo .fn#__init__" addParam "foo: int = 30" \
    append "self.foo = foo" -- find ".call#Foo" addArg "foo=10"
```

### Key differences

| Old CLI                    | New CLI                                    |
|----------------------------|--------------------------------------------|
| `pluckit view QUERY PATHS` | `pluckit PATHS find SELECTOR view`         |
| `pluckit find SEL PATHS`   | `pluckit PATHS find SEL terminal`          |
| `pluckit edit SEL --op PATHS` | `pluckit PATHS find SEL op`             |
| `--format names`           | `names` (terminal operation)               |
| `--format json`            | `materialize` (terminal operation)         |
| `--count`                  | `count` (terminal operation)               |
| `--add-param`              | `addParam` (mutation operation)            |
| `--remove`                 | `remove` (mutation operation)              |
| `-- SELECTOR --op`         | `-- find SELECTOR op` or `reset find ...`  |
| Paths at the end           | Source at the beginning                    |
