# CLI Reference

pluckit exposes four subcommands: `init`, `view`, `find`, and `edit`. They
all share one entry point:

```bash
pluckit [--version] [-h] COMMAND [OPTIONS] ...
```

Run `pluckit COMMAND --help` for command-specific options.

---

## `pluckit init`

Eagerly install and verify the DuckDB community extensions pluckit depends
on. This happens lazily on first use of any other command, but running it
explicitly gives you clearer diagnostics if anything fails.

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

## `pluckit view`

Render matched code regions as markdown using a CSS-style viewer query.
The query can be provided as a positional argument, via `--query-file`, or
read from stdin with `-`.

```bash
pluckit view QUERY [PATHS...] [OPTIONS]
pluckit view --query-file FILE [PATHS...] [OPTIONS]
pluckit view - [PATHS...] [OPTIONS]    # read query from stdin
```

### Options

| Flag                 | Description                                            |
|----------------------|--------------------------------------------------------|
| `-q, --query-file`   | Read query from file instead of positional argument    |
| `-f, --format`       | Output format (default: `markdown`)                    |
| `-o, --output`       | Write output to file (default: stdout)                 |
| `-r, --repo`         | Repository root for relative paths (default: cwd)      |

### Examples

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

# Query from stdin
echo ".fn[name^=test_] { show: signature; }" | pluckit view - tests/*.py

# Query from a file
pluckit view --query-file audit.q src/**/*.py

# Multiple paths and glob patterns
pluckit view ".fn#parse" src/*.py lib/*.py
```

### Multi-match collapse

When a signature-mode query matches more than one function, the output
collapses into a markdown table instead of N code fences:

```
| File               | Lines   | Signature                                  |
|---|---|---|
| src/validate.py    | 35-54   | `def _is_garbled(intent: str) -> bool:`    |
| src/validate.py    | 73-88   | `def _flatten_ops(comp: Any) -> list[str]:`|
| src/validate.py    | 102-196 | `def validate_chain(chain: str) -> Result:`|
```

For the full `{ show: ... }` declaration language, see
[Selector & Declaration Language](selectors.md).

---

## `pluckit find`

List AST nodes matching a CSS selector. Output formats are designed for
scripting and agent discovery: terse file:line pairs by default, or a
signature table, or machine-readable JSON.

```bash
pluckit find SELECTOR PATHS... [OPTIONS]
```

### Options

| Flag                                             | Description                                       |
|--------------------------------------------------|---------------------------------------------------|
| `-f, --format {locations,names,signature,json}`  | Output format (default: `locations`)              |
| `-o, --output`                                   | Write output to file (default: stdout)            |
| `-r, --repo`                                     | Repository root for relative paths                |
| `--count`                                        | Print only the total number of matches            |

### Output formats

#### `locations` (default)

One line per match, formatted `path:line:name`. Designed for shell
pipelines:

```bash
$ pluckit find ".fn:exported" src/auth.py
src/auth.py:14:authenticate
src/auth.py:42:decode_jwt
src/auth.py:89:refresh_token
```

#### `names`

Deduplicated list of identifier names. Good for set operations:

```bash
$ pluckit find ".fn[name^=test_]" --format names tests/*.py | wc -l
218
```

#### `signature`

Markdown table with synthesized signatures. Use this for code review and
audits:

```bash
$ pluckit find ".fn:exported" --format signature src/auth.py
| File        | Lines   | Signature                               |
|---|---|---|
| src/auth.py | 14-31   | `def authenticate(username, password):` |
| src/auth.py | 42-66   | `def decode_jwt(token: str) -> dict:`   |
```

#### `json`

One JSON object per match:

```bash
$ pluckit find ".cls" --format json src/models.py
{"file": "src/models.py", "start_line": 8, "end_line": 42, "name": "User", "type": "class_definition", "language": "python"}
{"file": "src/models.py", "start_line": 45, "end_line": 89, "name": "Session", "type": "class_definition", "language": "python"}
```

### Example: counting

```bash
$ pluckit find ".fn" --count src/**/*.py
147
```

---

## `pluckit edit`

Apply structural mutations to matched nodes. All edits are
**transactional**: if any affected file fails syntax re-validation after
splicing, every file is rolled back to its pre-edit state.

```bash
pluckit edit [GLOBAL_FLAGS] SELECTOR OPERATION [OPERATION...]
             [-- SELECTOR OPERATION [OPERATION...] [-- ...]]
             PATHS...
```

### Global flags

| Flag             | Description                                              |
|------------------|----------------------------------------------------------|
| `--dry-run`, `-n`| Show a unified diff of what would change; don't write    |
| `--repo`, `-r`   | Repository root for relative paths                       |

### Operations

| Flag                          | Args   | Description                                                  |
|-------------------------------|--------|--------------------------------------------------------------|
| `--replace-with`              | `TEXT` | Replace the matched node's entire text                       |
| `--replace`                   | `2`    | String-level replace within the matched node                 |
| `--prepend-lines`, `--prepend`| `TEXT` | Insert lines at the top of the matched node's body           |
| `--append-lines`, `--append`  | `TEXT` | Insert lines at the bottom of the matched node's body        |
| `--insert-lines`              | `3`    | `POSITION SELECTOR TEXT` — insert relative to a child anchor |
| `--wrap`                      | `2`    | Wrap the matched node with `BEFORE` and `AFTER`              |
| `--unwrap`                    | `0`    | Remove the matched node's enclosing context (inverse of wrap)|
| `--add-param`                 | `NAME` | Add a parameter to every matched function/method             |
| `--remove-param`              | `NAME` | Remove a parameter by name                                   |
| `--add-arg`                   | `EXPR` | Add an argument to every matched call site                   |
| `--remove-arg`                | `NAME` | Remove a keyword argument by name                            |
| `--rename`                    | `NAME` | Rename the matched definition (first name occurrence)        |
| `--clear-body`                | `0`    | Replace the body with `pass` (Python) or `{}` (C-family)     |
| `--remove`                    | `0`    | Remove the matched node entirely                             |

### Chainable edits

A single `pluckit edit` invocation can apply **multiple operations** to
one selector, or run **multiple groups** in order. Groups are separated by
a bare `--`:

```bash
pluckit edit \
    ".cls#Foo .fn#__init__" --add-param "foo: int = 30" \
                            --append-lines "self.foo = foo" \
    -- \
    ".call#Foo"             --add-arg "foo=10" \
    src/**/*.py
```

That single command:

1. Finds every `__init__` inside class `Foo`, adds the parameter, and
   appends `self.foo = foo` to the body.
2. Finds every call to `Foo(...)` and adds `foo=10` as a keyword
   argument.
3. Validates every affected file parses cleanly.
4. Rolls back *all* changes if any of them fails.

### Dry-run

`--dry-run` prints a real unified diff to stdout (one per changed file)
and a summary line to stderr:

```bash
$ pluckit edit --dry-run ".fn#top_level_fn" --rename renamed src/sample.py
--- a/src/sample.py
+++ b/src/sample.py
@@ -1,4 +1,4 @@
-def top_level_fn(x):
+def renamed(x):
     """Top-level function."""
     return x * 2

[dry-run] 1 group(s), 1 total match(es)
```

Pipe the diff directly into `patch` or `git apply` if you want to stage
it manually instead of letting pluckit write.

### Examples

```bash
# Replace a function's body entirely
pluckit edit ".fn#foo" --replace-with "def foo():\n    return 1" src/*.py

# Scoped find-and-replace within matched nodes
pluckit edit ".fn#validate" --replace "return None" "raise ValueError()" src/*.py

# Add a parameter to every exported function
pluckit edit ".fn:exported" --add-param "timeout: int = 30" src/**/*.py

# Remove a function entirely
pluckit edit ".fn#deprecated_helper" --remove src/*.py

# Clear a function body to `pass` / `{}`
pluckit edit ".fn#todo_later" --clear-body src/*.py

# Insert lines relative to a child anchor
pluckit edit ".cls#Foo" --insert-lines before ".fn#bar" "def pre_bar(self): pass" src/*.py
pluckit edit ".fn#main"  --insert-lines after  ".ret"    "cleanup()"                src/*.py

# Wrap a call in a try/except
pluckit edit ".call#query" --wrap "try:" "except DatabaseError:\n    raise" src/*.py
```

### Line-level vs character-level edits

| Operation            | Granularity | Preserves surrounding text? |
|----------------------|-------------|------------------------------|
| `--prepend-lines`    | line        | yes (inserts whole new lines)|
| `--append-lines`     | line        | yes                          |
| `--insert-lines`     | line        | yes                          |
| `--replace` (2-arg)  | character   | yes (within matched node)    |
| `--replace-with`     | node        | no (replaces entire node)    |
| `--wrap`             | node        | yes (adds lines before/after)|

Character-level insertion at arbitrary positions (`--insert-chars`) is
reserved for v0.2 once sitting_duck exposes byte offsets.
