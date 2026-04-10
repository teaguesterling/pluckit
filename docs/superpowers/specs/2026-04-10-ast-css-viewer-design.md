# AST CSS Viewer Design

*A CSS-style query language for code navigation. Selectors identify code elements; declarations control how they're rendered. Output is formatted source regions suitable for humans, agents, or tooling.*

## Goal

Give agents and humans a single compact syntax for "show me this code." The language pairs tree-sitter AST selectors with CSS-style declaration blocks. Matches are rendered as formatted source regions (markdown code blocks with location headers by default), not raw AST rows.

This is complementary to pluckit's query API, not a replacement. The query API returns structured data for composition and aggregation. The viewer returns rendered source for reading.

## Non-goals for v1.0

- Arbitrary row output (pluckit's query API already does this well)
- Syntax highlighting of declarations
- Multiple output formats (markdown only for v1)
- Relationship traversal (callers/callees/dependents) — deferred to v1.1+
- Custom CSS variables or selector metadata

## User-facing API

### Input: selector + optional declaration block

```
.fn#main
.fn#main { show: body; }
.class#Config { show: outline; }
.fn:has(.call#execute):not(:has(.try))
```

A bare selector is equivalent to `{ show: body }` — the default. Declaration blocks override defaults; missing properties fall through to defaults.

### Output: rendered source regions

````markdown
# src/my_module.py:12-18
```python
def main(argv):
    """Entry point."""
    config = parse_args(argv)
    return run(config)
```
````

Multiple matches are separated by blank lines. Each match has a location header (`# path:start-end`) followed by a fenced code block with the language tag.

### Entry point

```python
from pluckit import Plucker
from pluckit.viewer import AstViewer

viewer = AstViewer(code="src/**/*.py")
output = viewer.render(".fn#main")
# -> markdown string

# Or via a plugin on Plucker
pluck = Plucker(code="src/**/*.py", plugins=[AstViewer])
output = pluck.view(".fn#main { show: signature; }")
```

The viewer is a Pluckit plugin. It depends on the Code plugin (which provides the AST source) and adds one method: `view(query) -> str`.

## Query language

### Selectors

Selectors are standard sitting_duck AST CSS selectors, unchanged. See the sitting_duck selector documentation for full syntax.

### Declarations

Declarations are key-value pairs inside `{ }`, separated by semicolons. Keys are lowercase identifiers. Values are lowercase identifiers, numbers, or strings.

```
{ show: body; }
{ show: signature; }
{ show: outline; }
{ show: enclosing; }
```

**v1.0 scope:** only the `show` property is supported. Other properties are parsed but ignored (with a warning) so v1.1 additions don't break v1.0 queries.

### `show` property

Controls which portion of the matched node is rendered.

| Value | Behavior |
|---|---|
| `body` | The full matched node, including its header and body. **Default for functions, calls, statements.** |
| `signature` | The node's declaration line(s) only. For a function: `def foo(x, y):` with no body. For a class: `class Foo(Bar):` with no methods. |
| `outline` | Signature plus any child signatures, no bodies. For a class: the class signature plus each method signature. For a module: the module-level declarations. **Default for classes and modules.** |
| `enclosing` | Walk up to the nearest enclosing scope (function/class) and render that node with `show: body`. Useful for matches on calls or expressions where the bare match lacks context. |

**Type-specific defaults:** When no declaration is provided, the default depends on the matched node type:

- `.fn`, `.call`, `.return`, `.if`, `.loop`, `.try` → `show: body`
- `.class`, `:root`/module → `show: outline`
- `.import`, `.var`, `.str` → `show: body` (these are small)

Defaults can be overridden per-query.

## Deferred for v1.1+

The following properties were considered and deferred. Their names are reserved — v1.0 parses them and emits a warning that the property is not yet supported.

### `trace` — relationship traversal

Render related nodes alongside the match.

```
.fn#execute { trace: callers; depth: 1; }
```

| Value | Behavior |
|---|---|
| `callers` | Also render each direct caller's enclosing function. |
| `callees` | Also render each function this match calls (typically as `signature`). |
| `dependents` | Modules/classes that import/extend this. |
| `dependencies` | Modules/classes this imports/extends. |

Uses pluckit's Calls plugin when available.

### `depth` — traversal limit

```
.fn#execute { trace: callers; depth: 2; }
```

Controls how many hops to follow when `trace` is set. Default is `1`. `all` means transitive closure.

### `expand` — inline child rendering

```
.class#Config { show: outline; expand: .fn#__init__; }
```

For aggregate displays (outline), inline selected children at full `show: body`.

### Additional `show` values

- `call-site` — grep-style N lines of context around a match
- `header` — just the location header, no code
- `docstring` — just the docstring portion

These are all valuable but non-essential for v1.0.

## Parser

The viewer query is parsed as:

```
query      := selector (declaration_block)?
declaration_block := '{' declaration (';' declaration)* ';'? '}'
declaration := identifier ':' value
value      := identifier | number | quoted_string
```

The selector portion is passed verbatim to sitting_duck's existing CSS parser. The declaration block is parsed by the viewer.

Unknown properties produce a warning but do not fail the query — forward compatibility with v1.1 additions.

## Rendering

### Markdown format (v1.0 default)

```
# <relative_path>:<start_line>-<end_line>
```<language>
<source text>
```
```

Multiple matches are joined with two newlines. Source text is extracted from the original file using sitting_duck's start/end line information.

### Language tag

Derived from sitting_duck's language detection on the file. Falls back to the file extension. Falls back to no tag if neither is available.

### File paths

Relative to the current working directory when the viewer was constructed. Absolute paths are used if the relative form would escape the working directory.

## Integration with lackpy

lackpy will ship an AST CSS interpreter that delegates to pluckit's viewer. The interpreter:

1. Validates the query against the grammar (selector + declarations)
2. Invokes `pluckit.viewer.AstViewer.render(query)` against the workspace
3. Returns the rendered markdown as the program's output

The interpreter is a pluckit-backed tool inside lackpy, not a reimplementation. This keeps the viewer logic in pluckit where the AST infrastructure lives.

## Example queries

```
# Show the main function
.fn#main

# Show the Config class outline (signature + method names)
.class#Config

# Show the full body of Config.__init__
.class#Config .fn#__init__

# Show the signature of every test function
.func[name^=test_] { show: signature; }

# Show the function containing any call to execute() without a try block
.call#execute:not(:has(.try)) { show: enclosing; }

# Show every async function as a signature
.fn:async { show: signature; }
```

## Test plan

1. Parser accepts bare selectors (no declaration block)
2. Parser accepts declaration block with single property
3. Parser accepts declaration block with multiple properties
4. Parser handles trailing semicolons
5. Parser emits warning for unknown properties without failing
6. Default `show` value is type-specific (body for fn, outline for class)
7. `show: body` renders full matched node
8. `show: signature` renders just the declaration line(s)
9. `show: outline` for a class renders class + method signatures
10. `show: enclosing` walks up to nearest scope
11. Multiple matches are separated and each has a location header
12. Output uses correct language tag from sitting_duck detection
13. Empty match set returns empty string (not an error)

## Open questions

- **Signature extraction for arbitrary languages:** `show: signature` on a Python function is easy (text up to the colon). On C++ it's the declaration line(s). For v1.0 we may need to delegate this to sitting_duck's existing name/signature extraction, which may not cover every case.

- **`show: outline` for modules:** should it include imports, module-level constants, or just definitions? Probably definitions only for v1.0, with a note that users can use a selector to include imports explicitly.

- **Overlapping matches:** if a selector produces two matches where one contains the other (e.g., a method match inside a class match), the output would duplicate the method's text. For v1.0 we accept this; for v1.1 we could add deduplication.
