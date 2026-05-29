# Selector & Declaration Language

pluckit's selector language is a CSS-inspired syntax for addressing AST
nodes. The **structural grammar** is [sitting_duck](https://github.com/teaguesterling/sitting_duck)'s
— pluckit delegates matching to sitting_duck's `ast_select` / `ast_select_from`
macros over its `read_ast()` table function, so queries are fast, composable
with anything else DuckDB can do, and share one engine with the rest of the suite.

pluckit adds two thin layers on top of that engine:

1. **Ergonomic shorthand** — short aliases (`.fn`, `.cls`, `.call`) that resolve to
   sitting_duck's semantic-type classes (`.definition_function`, …).
2. **Value-add pseudo-classes** — a small set of filters sitting_duck cannot express
   (`:exported` / `:private` name conventions, `:contains` peek substrings, and the
   `:line` / `:lines` / `:long` / `:complex` thresholds), applied as a post-filter.

This page documents:

- The **selector syntax** (sitting_duck's structural grammar + pluckit's two layers)
- The **semantic taxonomy** — how shorthand class names map to sitting_duck's
  cross-language node categories
- The **`{ show: ... }` declaration language** used by the viewer

!!! note "One engine"
    Because matching is delegated to sitting_duck, the full upstream structural
    grammar — `:has()`, `:not()`, combinators, `[attr]` operators, and sitting_duck's
    native pseudo-classes (`:scope`, `:calls`, `:nth-child`, `:match`, …) — works
    directly through `Plucker.find()`. pluckit no longer maintains a separate, narrower
    compiler. See the [sitting_duck docs](https://github.com/teaguesterling/sitting_duck)
    for the complete structural grammar.

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

Two kinds, from the two layers:

**Structural — handled by sitting_duck.** `:has()`, `:not()`, and sitting_duck's full
native set (`:scope`, `:empty`, `:first-child`, `:nth-child(n)`, `:calls`, `:called-by`,
`:match`, …) pass straight through to the engine:

```css
.fn:not(:has(.try))          /* functions with no try block */
.fn:has(.call#execute)       /* functions that call execute() */
```

**Value-add — pluckit post-filters.** A small set sitting_duck cannot express, applied as a
`WHERE` over the matched nodes' `read_ast` columns (so they have identical meaning whether
used in `find()` or `filter()`):

| Pseudo-class     | Meaning                                                  |
|------------------|----------------------------------------------------------|
| `:exported`      | Public name (no leading underscore — Python convention)  |
| `:private`       | Private name (leading underscore)                        |
| `:contains(s)`   | Node's `peek` text contains the substring `s`            |
| `:line(n)`       | Node spans line `n`                                      |
| `:lines(a,b)`    | Node lies within lines `a`–`b`                           |
| `:long(n)`       | Node is longer than `n` lines                            |
| `:complex(n)`    | Node has more than `n` descendant nodes                  |

```css
.fn:exported                 /* public functions */
.fn:private                  /* _underscore-prefixed functions */
.fn:complex(50)              /* functions with >50 AST descendants */
.fn:long(80)                 /* functions longer than 80 lines */
```

!!! note "Top-level only"
    pluckit's value-add pseudo-classes are top-level filters on the matched set. A pluckit
    pseudo-class nested inside a `:has()` / `:not()` argument is left for sitting_duck's
    engine instead. For a compound selector the post-filter applies to the final matches.

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

### How shorthand resolves

A shorthand alias resolves in two steps: `.fn` → pluckit's taxonomy class `.def-func`
(the form `resolve_alias` exposes) → sitting_duck's semantic-type class
`.definition_function` (the name its `ast_select` understands). Aliases with no clean
sitting_duck equivalent, already-canonical sitting_duck names, and bare tree-sitter types
all pass through unchanged. sitting_duck is the single source of truth for what a class
matches, so the taxonomy can no longer drift away from the engine. If you find a missing
alias, [open an issue](https://github.com/teaguesterling/pluckit/issues).

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
