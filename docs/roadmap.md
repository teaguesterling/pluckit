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

- **`Selection.patch()` + `diff()` terminal** — complete the mutation
  vocabulary by supporting unified-diff input (the natural format for
  code review workflows). `patch()` applies a diff to matched regions;
  `diff()` outputs a transform as a unified diff instead of applying
  it. Enables the `query → transform → diff → review → apply` loop.
  Tracked as [pluckit#4](https://github.com/teaguesterling/pluckit/issues/4).

- **`@file` argument syntax** — let mutation args (and any string
  chain argument) read content from a file with an `@path` prefix:
  `replaceWith @patches/new_handler.py` instead of inlining escaped
  multi-line code. Applies uniformly to `from_argv`, `from_json`, and
  mutation methods.
  Tracked as [pluckit#5](https://github.com/teaguesterling/pluckit/issues/5).

---

## Architectural

Bigger shape questions. Landing any of these requires design work
before implementation.

### Dynamic, context-aware tool loading (via kibitzer modes)

Today, loading pluckit as an MCP tool (via squackit or similar)
exposes the full tool surface whether or not the current conversation
needs it. A conversation about documentation loads source-mutation
tools it will never use; a code-review conversation loads a viewer
that wastes context budget.

**Upstream mechanism: kibitzer mode-gated tool visibility**
([kibitzer#1](https://github.com/teaguesterling/kibitzer/issues/1)).
Kibitzer already defines modes (`explore` / `implement` / `test` /
`docs` / `review`) that gate writable paths. The proposal is to extend
them to gate *visible* tools per mode, filtering at MCP capability-
negotiation time. Per-turn attention surface drops from ~100 tools to
5-10 per mode; total capability is unchanged. `ChangeToolMode` is the
existing escape hatch.

**Integration shape: a shared participant API that any tool can
implement.** Not a per-consumer custom method, but a single protocol
that pluckit + lackpy + blq + jetsam + any future contributor all
implement the same way. Kibitzer owns the protocol definition; tool
authors just import it.

**Bidirectional: tools reflect back to kibitzer on mode change.**
The naive approach — a static `intent_tags` attribute set once at
plugin registration — is too rigid. A tool's offering can reshape by
mode: in `explore` it offers read-only inspection methods; in
`implement` it adds mutation methods. Example sketch:

```python
# Protocol defined in kibitzer, implemented by any tool
class KibitzerParticipant(Protocol):
    def on_mode_change(self, mode: str) -> list[ToolOffering]:
        """Return the tools this participant wants exposed for `mode`.
        Called by kibitzer on every ChangeToolMode."""

class Calls(Pluckin):  # pluckin side
    def on_mode_change(self, mode: str) -> list[ToolOffering]:
        if mode in ("explore", "review"):
            return [ToolOffering(name="callers", ...),
                    ToolOffering(name="callees", ...)]
        return []  # not surfaced in implement / test / docs modes
```

On a mode transition, kibitzer walks every registered participant,
calls `on_mode_change`, aggregates the returned offerings into the
new MCP tool manifest, and re-announces the capability set. Agents
see a different tool surface per mode; the total capability didn't
change, just what's visible.

Participants without `on_mode_change` fall back to "always visible" —
no regression for existing pluckins.

The primitive generalizes: this same participant API can serve
LSP-aware filtering, VSCode command palettes, etc. Each consumer
defines its own protocol (sharing the bidirectional-on-change shape);
pluckins implement whichever ones they care about.

### Tool search / recommendation via kibitzer

A structured tool surface (`PluckinRegistry.pluckins` is the first
piece) also enables `searchtools` / `recommend_tools` primitives in
kibitzer. An agent asks "what pluckit tools would help me answer
this?" and gets a ranked list back, with filters on intent / context
/ cost.

This complements the mode-gated loading above. Mode-gating is the
coarse filter ("which tools does this conversation's mode even see");
recommendation is the fine filter ("of those visible tools, which is
the right one for this specific sub-task"). kibitzer#1 notes the gap
it leaves: once visibility is constrained, a `ToolSearch`-equivalent
is needed for cross-mode discovery. That's the recommendation
primitive.

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
