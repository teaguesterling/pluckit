# Design: `--diff` flag, `patch` mutation, `@file` argument syntax

**Date:** 2026-04-18
**Issues:** [pluckit#4](https://github.com/teaguesterling/pluckit/issues/4), [pluckit#5](https://github.com/teaguesterling/pluckit/issues/5)
**Status:** Design

---

## Context

pluckit's mutation engine applies structural code changes atomically — rename,
addParam, replaceWith, etc. — but today there's no way to **preview** a
mutation as a diff before applying it, no way to **apply an external diff** to
matched code regions, and no way to **read argument content from files** (which
makes multi-line mutations on the CLI painful).

These three features compose into a review workflow:

```
query → mutate → diff → review → apply
```

```bash
# 1. Generate a diff preview
pluckit src/**/*.py find ".fn#old_api" rename "new_api" --diff > refactor.patch

# 2. Human or agent reviews the patch

# 3. Apply it
pluckit src/**/*.py find ".fn#new_api" patch @refactor.patch
```

---

## Feature 1: `--diff` — mutation preview as unified diff

### Behavior

`--diff` is a global flag (like `--dry-run`) that changes how mutations
produce output. Instead of writing files, the chain outputs a unified diff
of what *would* change to stdout.

```bash
pluckit src/**/*.py find ".fn#validate" rename "validate_token" --diff
# --- a/src/auth.py
# +++ b/src/auth.py
# @@ -12,3 +12,3 @@
# -def validate(token: str) -> User:
# +def validate_token(token: str) -> User:
```

Output goes to stdout (pipeable), not stderr.

### Implementation

#### Chain dataclass

New field on `Chain`:

```python
@dataclass
class Chain:
    ...
    diff: bool = False      # new — parallel to dry_run
```

Parsed in `from_argv()` as `--diff`. Serialized in `to_dict()` / `from_dict()`
(omitted when false). Included in `to_argv()` output.

#### MutationEngine — no changes needed for diff mode

The engine itself stays unchanged. It always writes to disk (so multi-step
chains see intermediate state) and already holds snapshots for rollback.

Diff computation happens at the **evaluator level**, not the engine level.
This avoids splitting the engine's return type and keeps the single-step vs
multi-step logic in one place.

#### Chain.evaluate() — diff orchestration

The evaluator manages the full diff lifecycle:

1. Before the step loop, initialize `initial_snapshots: dict[str, str] = {}`
2. Before the **first** mutation step, snapshot every file that the
   Plucker's source patterns match. (Lazy: read and cache each file path
   on first encounter via `MutationEngine._materialize()` results.)
3. Let mutations write to disk normally via the unchanged engine (so
   subsequent mutations and re-parses see intermediate state).
4. After all steps complete, diff each file's initial snapshot against its
   current disk content using `difflib.unified_diff()`.
5. Roll back all modified files to their initial snapshots.

```python
# In evaluate(), before the step loop:
initial_snapshots: dict[str, str] = {}

# On first mutation dispatch when self.diff is True:
#   for each file the mutation touches (from engine._materialize):
#       if fp not in initial_snapshots:
#           initial_snapshots[fp] = Path(fp).read_text()
#   let engine.apply() run normally (writes to disk)

# After the step loop, if self.diff:
#   diffs = []
#   for fp, original in initial_snapshots.items():
#       current = Path(fp).read_text()
#       if current != original:
#           rel = os.path.relpath(fp)
#           diff = "".join(difflib.unified_diff(
#               original.splitlines(keepends=True),
#               current.splitlines(keepends=True),
#               fromfile=f"a/{rel}",
#               tofile=f"b/{rel}",
#           ))
#           diffs.append(diff)
#       Path(fp).write_text(original)  # roll back
```

The evaluator returns:

```python
{
    "chain": self.to_dict(),
    "type": "diff",
    "data": ["--- a/src/auth.py\n+++ b/src/auth.py\n@@ ...\n..."],
}
```

This reuses the existing `"diff"` result type in `_print_result()`.

#### --dry-run implementation (while we're here)

`--dry-run` is currently parsed into `Chain.dry_run` but **never checked**
during `evaluate()`. Since `--diff` and `--dry-run` share the "don't
persist changes" mechanism, implement both:

- `--dry-run`: run mutations, roll back, report
  `{"type": "mutation", "data": {"applied": False, "dry_run": True}}`
- `--diff`: run mutations, roll back, report diffs

If both are set, `--diff` takes precedence (it's strictly more informative).

---

## Feature 2: `patch` — apply diffs or replacement text to matched nodes

### Behavior

`Selection.patch(content)` applies external content to matched nodes. The
content is interpreted based on its shape:

1. **Unified diff** — detected by leading `---` or `diff --git`. Hunks are
   applied to the matched node's text.
2. **Raw replacement text** — everything else. Functionally equivalent to
   `replaceWith`, but signals "applying an external change" and pairs
   naturally with `@file`.

```bash
# Apply a unified diff from a file
pluckit src/**/*.py find ".fn#handler" patch @refactor.patch

# Apply raw replacement text
pluckit src/**/*.py find ".fn#handler" patch "def handler(): return 43"

# Inline diff (uncommon but supported)
pluckit src/**/*.py find ".fn#handler" patch @- <<'EOF'
--- a/handler.py
+++ b/handler.py
@@ -1,3 +1,3 @@
 def handler():
-    return 42
+    return 43
EOF
```

### Implementation

#### Patch mutation class (mutations.py)

```python
class Patch(Mutation):
    """Apply a unified diff or raw replacement to matched nodes."""

    def __init__(self, content: str) -> None:
        self.content = content
        self._is_diff = content.lstrip().startswith(("---", "diff --git"))

    def compute(self, node: dict, old_text: str, full_source: str) -> str:
        if self._is_diff:
            return self._apply_diff(old_text)
        else:
            # Raw replacement — delegate to ReplaceWith behavior
            indent = _leading_indent(old_text)
            return _reindent(self.content, indent)

    def _apply_diff(self, old_text: str) -> str:
        """Parse unified diff hunks and apply them to old_text."""
        # Parse hunks from self.content
        # Walk old_text lines, applying additions/removals
        # Strict matching: context lines must match exactly
        # Raises PluckerError on mismatch
        ...
```

The diff-application logic parses `@@` hunk headers and walks context/add/remove
lines. v1 is **strict** — context lines must match exactly or it raises
`PluckerError`. Fuzzy matching is a future extension.

#### Registration

- `_MUTATION_OPS` in chain.py: add `"patch"`
- `_KNOWN_OPS` in chain.py: add `"patch"`
- `Selection.patch()` method:

```python
def patch(self, content: str) -> Selection:
    """Apply a unified diff or replacement text to matched nodes."""
    from pluckit.mutation import MutationEngine
    from pluckit.mutations import Patch
    return MutationEngine(self._ctx).apply(self, Patch(content))
```

### Future extensions (not in v1)

- **List of replacements**: JSON array of strings, one per matched node
- **List of mutations**: JSON array of `{"op": ..., "args": ...}` dicts,
  applied per matched node
- **Fuzzy hunk matching**: tolerate drifted line numbers like `git apply`

---

## Feature 3: `@file` argument syntax

### Behavior

Any string argument in a chain step can reference a file with `@path`:

```bash
pluckit src/**/*.py find ".fn#handler" replaceWith @patches/new_handler.py
pluckit src/**/*.py find ".fn#handler" patch @refactor.patch
```

- `@path` — read file at `path`, substitute content as the argument value
- `@@path` — escape: literal string `@path` (no file read)
- Resolution is relative to CWD

### Implementation

#### Resolution helper (chain.py)

```python
def _resolve_file_args(args: list[str]) -> list[str]:
    """Resolve @file references in step arguments."""
    resolved = []
    for arg in args:
        if arg.startswith("@@"):
            resolved.append(arg[1:])  # strip one @, keep rest
        elif arg.startswith("@"):
            path = Path(arg[1:])
            if not path.is_file():
                raise PluckerError(f"@file not found: {path}")
            try:
                resolved.append(path.read_text(encoding="utf-8"))
            except OSError as e:
                raise PluckerError(f"Cannot read @file {path}: {e}") from e
        else:
            resolved.append(arg)
    return resolved
```

#### Where it's called

In `Chain.evaluate()`, right before dispatching any step:

```python
for step in self.steps:
    op = step.op
    resolved_args = _resolve_file_args(step.args)

    # ... dispatch using resolved_args instead of step.args
    method(*resolved_args, **step.kwargs)
```

Applied uniformly to all ops — mutations, queries, terminals, plugin ops.

#### Serialization

`@path` stays as-is in serialized forms. The chain references paths, not
content. Resolution happens only at eval time.

**JSON object form** — in `from_dict()`, an arg may also be an object:

```json
{"op": "replaceWith", "args": [{"file": "patches/new_handler.py"}]}
```

`ChainStep.from_dict()` normalizes `{"file": "..."}` → `"@..."` so there's
one resolution path:

```python
@classmethod
def from_dict(cls, data: dict[str, Any]) -> ChainStep:
    raw_args = data.get("args", [])
    args = []
    for a in raw_args:
        if isinstance(a, dict) and "file" in a:
            args.append(f"@{a['file']}")
        else:
            args.append(a)
    return cls(op=data["op"], args=args, kwargs=data.get("kwargs", {}))
```

---

## Files to modify

| File | Changes |
|------|---------|
| `src/pluckit/chain.py` | `diff` field, `--diff` parsing, `_resolve_file_args()`, evaluate() diff/dry-run orchestration, `"patch"` in op sets, `ChainStep.from_dict()` object-form args |
| `src/pluckit/mutations.py` | `Patch` class with diff parser and raw-replacement fallback |
| `src/pluckit/selection.py` | `Selection.patch()` method |
| `src/pluckit/cli.py` | `--diff` in help text (parsing is in chain.py) |

## Files to add

| File | Purpose |
|------|---------|
| `tests/test_diff_flag.py` | Tests for `--diff` output on various mutations |
| `tests/test_patch.py` | Tests for `patch` with unified diffs and raw text |
| `tests/test_file_args.py` | Tests for `@file` resolution, escaping, errors |

---

## Verification

1. **`--diff` flag**: Run a mutation chain with `--diff`, verify unified diff
   output matches expected, verify no files were modified on disk.
2. **Round-trip**: Generate a diff with `--diff > file.patch`, apply with
   `patch @file.patch`, verify the result matches direct mutation.
3. **`@file` resolution**: Create a file with replacement content, use
   `replaceWith @file`, verify substitution. Test `@@` escaping. Test
   missing-file error.
4. **Multi-step `--diff`**: Chain with multiple mutations + `--diff`, verify
   all changes appear in the diff output.
5. **`--dry-run`**: Verify mutations report without applying, no files changed.
6. **JSON object form**: `{"file": "path"}` in `from_dict()` resolves correctly.
7. **Existing tests**: Run full test suite to verify no regressions.
