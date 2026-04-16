# Roadmap

Tracked items that don't fit cleanly into any one release's changelog.
Rough grouping by where the friction is: near-term (we could land it
next), architectural (bigger shape, needs design), and upstream
(waiting on sitting_duck or duck_tails).

---

## Near-term

These are scoped well enough that they could land in the next release
or two when someone picks them up.

- **`Chain.sweep(param, values)`** — parameter-sweep batch, the rare
  case where `filter(name__in=[...])` doesn't cover. Runs the same
  chain N times with different input values, aggregates results.
  Covered by the existing selection-stack abstraction; just needs an
  op and a small evaluator extension.

- **Multi-match `Isolated`** — today `Selection.isolate()` extracts
  only the first match. Multi-match would fan out, producing a list of
  `Isolated` objects (one per match). Not complicated; waiting on a
  concrete need.

- **`blame()` in the `History` pluckin** — raises `PluckerError` today.
  Blocked on duck_tails shipping a `git_blame` table function
  ([issue #18 upstream](https://github.com/teaguesterling/duck_tails/issues/18)).

- **Character-level edits (`--insert-chars`)** — line-level splicing
  is what we have; inline positional insertions are reserved for a
  future milestone. Pluckit-side work is modest once sitting_duck
  exposes byte offsets on `read_ast` rows.

- **Cache benchmarks** — `Plucker(cache=True)` should be meaningfully
  faster on repeat queries. We've never measured it against a realistic
  codebase. One afternoon of work and a blog-ready chart.

---

## Architectural

Bigger shape questions. Landing any of these requires design work
before implementation.

### Dynamic, context-aware tool loading

Today, loading pluckit as an MCP tool (via squackit or similar) exposes
the full tool surface whether or not the current conversation needs
it. A conversation about documentation loads source-mutation tools it
will never use; a code-review conversation loads a viewer that wastes
context budget.

Direction: **runtime tool selection driven by conversation context.**

- If the conversation is looking at source code, load query/mutate/view
  tools
- If it's reading docs, load doc-reading tools; skip mutate
- If it's reviewing diffs, load History + blame + diff rendering
- etc.

The primitive is a *tool manifest* keyed by context — a declarative
map from "intent" to "tools" that consumers (squackit / LSP / other
MCP servers) can query.

### Tool search / recommendation via kibitzer

Once pluckit has a structured tool surface (the `PluckinRegistry.pluckins`
iterator is the first piece of this), tying into [kibitzer](https://github.com/teaguesterling/kibitzer)
for `searchtools` / `recommend_tools` becomes tractable. An agent
could ask "what pluckit tools would help me answer this?" and get a
ranked list back, with filters on intent / context / cost.

This is closely related to the context-aware loading item above —
kibitzer's recommendation output could drive the manifest.

### Consumer-agnostic tool contracts

The Plugin → Pluckin rename (v0.9.0) and the `PluckinRegistry.pluckins`
iterator (also v0.9.0) were the first steps toward decoupling pluckit
from any specific consumer (squackit, LSP, VSCode extensions, etc.).
The open architectural question: **what does a pluckin expose to enable
consumer-specific presentation without coupling to any specific
consumer?**

Current working idea (discussed but not implemented): plugins declare
optional methods like `squackit_tools()`, `lsp_actions()`,
`vscode_commands()`. Consumers sniff for their specific method and
fail gracefully when absent. Pluckit knows nothing about any specific
consumer.

### MCP-side pagination/batch integration

v0.11.0 landed chain-level pagination. The open question: does the
consumer-side (squackit/etc.) need any scaffolding, or is it already
sufficient to forward the result envelope? First real agent workflow
using paginated pluckit chains will surface this.

---

## Upstream-blocked

Work that's architecturally ready on the pluckit side and just needs
sitting_duck or duck_tails to ship a matching feature.

### `Calls` pluckin simplification

When sitting_duck ships its `scope` struct (`{current, function,
class, module, stack}`) on every `read_ast` row, the Calls pluckin's
provenance-walk + per-file `ast_select` fan-out collapses to a single
lateral join. See `src/pluckit/pluckins/calls.py` module docstring.

### `duck_tails.git_read` named `repo_path` parameter

`git_read` accepts `repo_path` as a named input but resolves relative
`git://` URIs against the process cwd instead of the repo at
`repo_path`. Workaround lives in `src/pluckit/pluckins/history.py`
(embed absolute path in the URI). Tracked as
[duck_tails#17](https://github.com/teaguesterling/duck_tails/issues/17).

### Native `ast_select` table-source support

`ast_select` takes a file path (goes to `read_ast`). For the AST cache
to use it against a cached table, we'd want `ast_select` to also
accept a table name. Today, `ASTCache` queries cached tables with
pluckit's own `_selector_to_where` compiler instead. Not blocking,
just a polish.

---

## Not on the roadmap (things we deliberately aren't doing)

- **A pluckit LSP server.** pluckit's job is the query/mutate surface;
  LSP integration is a consumer's job (could be a squackit feature or
  its own package). We might expose LSP-friendly hooks on pluckins,
  but pluckit itself stays MCP/CLI-first.
- **A web UI / dashboard.** Same reasoning — consumer's job.
- **Generic full-text search over ASTs.** sitting_duck's selectors
  plus pluckit's `filter(name__contains=...)` already cover this. No
  need for a separate index.

---

## How to propose a roadmap item

Open an issue with the label `roadmap`. Include:

- **Motivation** — concrete use case (not "it would be nice")
- **Proposed shape** — rough API sketch or sequence diagram
- **Upstream dependencies** — sitting_duck / duck_tails features it
  requires
- **Non-goals** — what this explicitly *doesn't* cover

If it's small enough to land in a release, it'll migrate from this
doc to a milestone.
