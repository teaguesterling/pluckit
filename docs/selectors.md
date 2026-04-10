# Selector & Declaration Language

pluckit's selector language is a CSS-inspired syntax for addressing AST
nodes. It's compiled to SQL over [sitting_duck](https://github.com/teaguesterling/sitting_duck)'s
`read_ast()` table function, which means queries are fast and composable
with anything else DuckDB can do.

This page documents:

- The **selector syntax** pluckit's compiler currently supports
- The **semantic taxonomy** — how CSS class names map to sitting_duck's
  cross-language node categories
- The **`{ show: ... }` declaration language** used by the viewer

!!! note "Upstream vs pluckit"
    sitting_duck ships a richer selector language than pluckit's
    fluent layer currently compiles. Features like `:calls()`,
    `:matches()`, `:scope()`, and the call-graph pseudo-elements work
    when you call `ast_select` directly against the underlying DuckDB
    connection, but aren't yet wired into `Plucker.find()`. This page
    documents the pluckit-compiled subset. See the
    [sitting_duck docs](https://github.com/teaguesterling/sitting_duck)
    for the full upstream language.

---

## Selector syntax

### Class selectors

A leading `.` followed by a taxonomy name selects nodes by their
semantic category:

```css
.fn         /* all function definitions */
.cls        /* all class definitions */
.call       /* all call expressions */
.str        /* all string literals */
.import     /* all import statements */
```

The taxonomy is **cross-language** — `.fn` matches `function_definition`
in Python, `function_declaration` in Go and JavaScript, `function_item`
in Rust, `method_definition` in C++, and so on. You write one selector
and it works across your whole polyglot codebase.

### Name selectors

Append `#name` to restrict to a specific identifier:

```css
.fn#main                 /* function named "main"  */
.cls#Config              /* class named "Config"   */
.call#fetch_user         /* call site: fetch_user(…)*/
```

Names are exact matches. For pattern matching, use attribute selectors.

### Attribute selectors

pluckit supports four CSS-style comparison operators on the `name`,
`type`, and `language` columns:

| Syntax                  | Meaning                                       |
|-------------------------|-----------------------------------------------|
| `[name=validate]`       | Exact match                                   |
| `[name^=test_]`         | Starts with                                   |
| `[name$=_handler]`      | Ends with                                     |
| `[name*=auth]`          | Contains                                      |
| `[language=python]`     | Restrict to a specific language               |
| `[type=lambda]`         | Restrict to a specific tree-sitter node type  |

```css
.fn[name^=test_]         /* test helpers */
.fn[name$=_async]        /* async-suffixed functions */
.cls[language=python]    /* Python classes only */
```

Underscores in the value are escaped automatically, so `[name^=test_]`
matches `test_foo` but not `testXfoo`.

### Descendant combinators

Space-separated selectors match descendants:

```css
.cls#Foo .fn             /* every method in class Foo */
.fn:exported .call#log   /* log() calls in exported fns */
.try .call#execute       /* execute() inside try blocks */
```

### Pseudo-classes

pluckit ships with a small set of pseudo-classes backed by the
sitting_duck flags byte and name conventions:

| Pseudo-class     | Meaning                                                  |
|------------------|----------------------------------------------------------|
| `:exported`      | Name is public (non-underscore prefix in Python, etc.)   |
| `:not(sel)`      | Negation                                                 |
| `:has(sel)`      | Has a descendant matching `sel`                          |

```css
.fn:exported                 /* public functions */
.fn:not(:has(.try))          /* functions with no try block */
.fn:has(.call#execute)       /* functions that call execute() */
```

`:not()` and `:has()` compose — pluckit compiles them to correlated
EXISTS / NOT EXISTS sub-queries over the same `read_ast()` table.

---

## The semantic taxonomy

sitting_duck classifies every AST node with a `semantic_type` code that's
consistent across languages. pluckit's class selectors map onto this
taxonomy:

### Definitions

| Selector(s)                          | Maps to              | Matches                                      |
|--------------------------------------|----------------------|----------------------------------------------|
| `.fn`, `.function`, `.func`, `.def`  | `def-func`           | Function / method definitions                |
| `.cls`, `.class`                     | `def-class`          | Class / struct / trait / interface           |
| `.var`, `.let`, `.const`             | `def-var`            | Variable declarations                        |
| `.module`, `.ns`, `.namespace`       | `def-module`         | Module and namespace definitions             |

### Access (computation)

| Selector(s)                          | Maps to              | Matches                             |
|--------------------------------------|----------------------|-------------------------------------|
| `.call`, `.invoke`                   | `access-call`        | Call expressions                    |
| `.member`, `.attr`, `.field`, `.prop`| `access-member`      | Attribute / field access            |
| `.index`, `.subscript`               | `access-index`       | Subscript access                    |

### Flow & error handling

| Selector(s)                          | Maps to              | Matches                             |
|--------------------------------------|----------------------|-------------------------------------|
| `.loop`, `.for`, `.while`            | `flow-loop`          | Loop constructs                     |
| `.jump`, `.ret`, `.return`, `.break` | `flow-jump`          | Return, break, continue, goto       |
| `.try`                               | `error-try`          | Try / begin blocks                  |
| `.catch`, `.except`                  | `error-catch`        | Catch / except handlers             |
| `.throw`, `.raise`                   | `error-throw`        | Throw / raise expressions           |
| `.finally`, `.ensure`, `.defer`      | `error-finally`      | Finally / defer / ensure            |

### Literals

| Selector(s)                          | Maps to              | Matches                             |
|--------------------------------------|----------------------|-------------------------------------|
| `.str`, `.string`                    | `literal-str`        | String literals                     |
| `.num`, `.int`, `.float`             | `literal-num`        | Numeric literals                    |
| `.bool`, `.boolean`                  | `literal-bool`       | Boolean literals                    |
| `.list`, `.dict`, `.array`, `.map`   | `literal-coll`       | Collection literals                 |

### External

| Selector(s)                          | Maps to              | Matches                             |
|--------------------------------------|----------------------|-------------------------------------|
| `.import`, `.require`, `.use`        | `external-import`    | Import / require / use statements   |
| `.export`, `.pub`                    | `external-export`    | Exports / pub declarations          |

See [`src/pluckit/selectors.py`](https://github.com/teaguesterling/pluckit/blob/main/src/pluckit/selectors.py)
for the complete alias table.

### Fail-closed behavior

If a selector resolves to a taxonomy class that pluckit's compiler
doesn't yet have a semantic code for, the compiler emits a match-nothing
WHERE clause rather than silently matching everything. This is a
deliberate safety net — as sitting_duck's taxonomy grows, pluckit won't
silently drift into over-matching. If you find a taxonomy gap,
[open an issue](https://github.com/teaguesterling/pluckit/issues).

---

## The `{ show: … }` declaration language

The `AstViewer` plugin extends selectors with a CSS-stylesheet-style
declaration block. Each block specifies how matched nodes should be
rendered:

```css
.fn#main { show: body; }
.cls#Config { show: outline; }
.fn { show: signature; }
```

### `show` values

| Value         | Behavior                                                               |
|---------------|------------------------------------------------------------------------|
| `body`        | Full node text (default for functions, calls, statements)              |
| `signature`   | Declaration line only, synthesized from native extraction metadata     |
| `outline`     | Class header + method signatures + dataclass fields (default for classes) |
| `enclosing`   | Walk up to the nearest scope and render *that* as body                 |
| `N` (integer) | First N lines of the body with a `…` truncation marker                 |

```css
.fn { show: signature; }        /* default functions to signatures */
.fn#main { show: body; }        /* main is special — full body */
.cls#Config { show: outline; }  /* Config as an outline */
.fn#parse { show: 10; }         /* first 10 lines of parse() */
```

### Multi-rule queries

Declarations compose exactly like CSS stylesheets. Later, more specific
rules override earlier ones:

```css
.fn { show: signature; }              /* default */
.fn#main { show: body; }              /* except main */
.fn[name^=handle_] { show: 15; }      /* handlers get 15 lines */
```

pluckit's viewer processes them in order and picks the most specific
match per node.

### Auto-collapse for multi-match signature queries

When a single query matches many functions and the `show` mode is
`signature`, the viewer automatically collapses the output into a
markdown table rather than emitting N code fences:

```
| File            | Lines   | Signature                                  |
|---|---|---|
| src/validate.py | 35-54   | `def _is_garbled(intent: str) -> bool:`    |
| src/validate.py | 73-88   | `def _flatten_ops(comp: Any) -> list[str]:`|
```

You can override this with `{ show: body; }` if you really want N
fences.

### Reading from stdin or a file

Queries can get long. Store them in a file and reference with
`--query-file`, or pipe them in:

```bash
pluckit view --query-file audit.q src/**/*.py

cat <<'EOF' | pluckit view - src/**/*.py
.fn { show: signature; }
.fn#main { show: body; }
.cls#Config { show: outline; }
EOF
```
