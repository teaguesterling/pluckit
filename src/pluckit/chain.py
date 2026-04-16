"""Serializable chain representation of pluckit operations.

A **Chain** is an ordered sequence of pluckit operations (find, filter,
addParam, count, etc.) paired with source file patterns and optional
configuration.  Chains serve as the portable interchange format for
pluckit workflows:

* **MCP transport** — a Chain can be serialised to JSON for transmission
  over the Model Context Protocol, letting an LLM build a query plan and
  send it to a pluckit server for evaluation.
* **CLI** — command-line arguments are parsed into a Chain before
  execution, giving a single internal representation for every entry
  point.
* **Python API** — chains can be constructed and inspected
  programmatically, enabling tooling such as dry-run previews and plan
  diffing.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChainStep:
    """One operation in a chain."""

    op: str
    args: list[str] = field(default_factory=list)
    kwargs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict, omitting empty args/kwargs."""
        d: dict[str, Any] = {"op": self.op}
        if self.args:
            d["args"] = self.args
        if self.kwargs:
            d["kwargs"] = self.kwargs
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChainStep:
        """Construct from a plain dict.  Raises ValueError if *op* is missing."""
        if "op" not in data:
            msg = "ChainStep requires 'op' key"
            raise ValueError(msg)
        return cls(
            op=data["op"],
            args=data.get("args", []),
            kwargs=data.get("kwargs", {}),
        )


@dataclass
class Chain:
    """A complete operation chain: source patterns, steps, and options."""

    source: list[str]
    steps: list[ChainStep]
    plugins: list[str] = field(default_factory=list)
    repo: str | None = None
    dry_run: bool = False
    json_input: bool = False
    json_output: bool = False

    _KNOWN_OPS: frozenset[str] = frozenset({
        # Query
        "find", "filter", "filter_sql", "not_",
        # Navigation
        "unique", "parent", "children", "siblings", "ancestor",
        "next", "prev", "containing", "at_line", "at_lines",
        # Mutation
        "replaceWith", "replace", "addParam", "removeParam",
        "addArg", "removeArg", "insertBefore", "insertAfter",
        "rename", "prepend", "append", "wrap", "unwrap", "remove",
        "clearBody",
        # Terminals
        "count", "names", "text", "attr", "complexity", "materialize",
        # Pagination
        "limit", "offset", "page",
        # Plugin ops
        "view", "history", "authors", "at", "diff", "blame",
        # Control
        "reset", "pop",
    })

    @classmethod
    def from_argv(cls, argv: list[str]) -> Chain:
        """Parse shell-style CLI arguments into a Chain.

        Raises ``SystemExit`` for empty *argv* or unrecoverable parse
        errors, consistent with argparse conventions.
        """
        if not argv:
            print("usage: pluckit [FLAGS] SOURCE STEP [STEP...]", file=sys.stderr)  # noqa: T201
            raise SystemExit(2)

        plugins: list[str] = []
        repo: str | None = None
        dry_run = False
        json_input = False
        json_output = False
        source: list[str] | None = None

        # Phase 1: consume global flags
        i = 0
        while i < len(argv):
            tok = argv[i]
            if tok in ("--plugin", "-p"):
                i += 1
                plugins.append(argv[i])
            elif tok in ("--repo", "-r"):
                i += 1
                repo = argv[i]
            elif tok in ("--dry-run", "-n"):
                dry_run = True
            elif tok == "--json":
                json_input = True
            elif tok == "--to-json":
                json_output = True
            elif tok in ("-c", "--code"):
                source = ["code"]
            elif tok in ("-d", "--docs"):
                source = ["docs"]
            elif tok in ("-t", "--tests"):
                source = ["tests"]
            else:
                # First non-flag token — source (unless shortcut set it)
                if source is None:
                    source = [tok]
                else:
                    # source already set by shortcut; this token starts steps
                    break
                i += 1
                break
            i += 1

        if source is None:
            print("usage: pluckit [FLAGS] SOURCE STEP [STEP...]", file=sys.stderr)  # noqa: T201
            raise SystemExit(2)

        # Phase 2: parse steps from remaining tokens
        remaining = argv[i:]
        steps: list[ChainStep] = []
        current_step: ChainStep | None = None

        for tok in remaining:
            if tok == "--":
                # Flush current step then insert reset
                if current_step is not None:
                    steps.append(current_step)
                    current_step = None
                steps.append(ChainStep(op="reset"))
            elif tok in cls._KNOWN_OPS:
                # Flush previous step, start new one
                if current_step is not None:
                    steps.append(current_step)
                current_step = ChainStep(op=tok)
            elif tok.startswith("--") and "=" in tok:
                # kwarg for current step
                key, _, value = tok[2:].partition("=")
                if current_step is not None:
                    current_step.kwargs[key] = value
            else:
                # positional arg for current step
                if current_step is not None:
                    current_step.args.append(tok)

        if current_step is not None:
            steps.append(current_step)

        return cls(
            source=source,
            steps=steps,
            plugins=plugins,
            repo=repo,
            dry_run=dry_run,
            json_input=json_input,
            json_output=json_output,
        )

    def to_argv(self) -> list[str]:
        """Convert this chain to a CLI token list (inverse of from_argv)."""
        tokens: list[str] = []
        for plugin in self.plugins:
            tokens.extend(["--plugin", plugin])
        if self.repo:
            tokens.extend(["--repo", self.repo])
        if self.dry_run:
            tokens.append("--dry-run")
        tokens.extend(self.source)
        for step in self.steps:
            if step.op == "reset":
                tokens.append("--")
                continue
            tokens.append(step.op)
            tokens.extend(step.args)
            for key, value in step.kwargs.items():
                tokens.append(f"--{key}={value}")
        return tokens

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict, omitting default-valued optional fields."""
        d: dict[str, Any] = {
            "source": self.source,
            "steps": [s.to_dict() for s in self.steps],
        }
        if self.plugins:
            d["plugins"] = self.plugins
        if self.repo is not None:
            d["repo"] = self.repo
        if self.dry_run:
            d["dry_run"] = self.dry_run
        return d

    def to_json(self, **kwargs: Any) -> str:
        """Serialise to a JSON string."""
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Chain:
        """Construct from a plain dict.

        *source* and *steps* are required.  *source* may be a single
        string, which is normalised to a one-element list.
        """
        if "source" not in data:
            msg = "Chain requires 'source' key"
            raise ValueError(msg)
        if "steps" not in data:
            msg = "Chain requires 'steps' key"
            raise ValueError(msg)

        source = data["source"]
        if isinstance(source, str):
            source = [source]

        return cls(
            source=source,
            steps=[ChainStep.from_dict(s) for s in data["steps"]],
            plugins=data.get("plugins", []),
            repo=data.get("repo"),
            dry_run=data.get("dry_run", False),
        )

    @classmethod
    def from_json(cls, text: str) -> Chain:
        """Deserialise from a JSON string."""
        return cls.from_dict(json.loads(text))

    # ------------------------------------------------------------------
    # Pagination navigation helpers
    # ------------------------------------------------------------------

    @classmethod
    def next_page(cls, evaluated_result: dict) -> Chain | None:
        """Build the Chain for the next page of a paginated result.

        Returns None if the result has no pagination metadata or
        ``has_more`` is False.
        """
        page = evaluated_result.get("page")
        if not page or not page.get("has_more"):
            return None
        source_dict = evaluated_result.get("source_chain")
        if source_dict is None:
            return None
        original_chain_dict = evaluated_result.get("chain", {})
        limit = page.get("limit")
        current_offset = page.get("offset", 0)
        if limit is None:
            return None
        return cls._build_paginated_chain(
            source_dict, original_chain_dict,
            offset=current_offset + limit, limit=limit,
        )

    @classmethod
    def prev_page(cls, evaluated_result: dict) -> Chain | None:
        """Build the Chain for the previous page of a paginated result.

        Returns None if the result has no pagination metadata or
        the current offset is already 0.
        """
        page = evaluated_result.get("page")
        if not page:
            return None
        current_offset = page.get("offset", 0)
        limit = page.get("limit")
        if limit is None or current_offset <= 0:
            return None
        source_dict = evaluated_result.get("source_chain")
        if source_dict is None:
            return None
        original_chain_dict = evaluated_result.get("chain", {})
        new_offset = max(0, current_offset - limit)
        return cls._build_paginated_chain(
            source_dict, original_chain_dict,
            offset=new_offset, limit=limit,
        )

    @classmethod
    def goto_page(cls, evaluated_result: dict, page_num: int) -> Chain | None:
        """Build the Chain for a specific 0-indexed page of a paginated result.

        Returns None if the result has no pagination metadata.
        """
        page = evaluated_result.get("page")
        if not page:
            return None
        limit = page.get("limit")
        if limit is None:
            return None
        source_dict = evaluated_result.get("source_chain")
        if source_dict is None:
            return None
        original_chain_dict = evaluated_result.get("chain", {})
        new_offset = max(0, int(page_num) * limit)
        return cls._build_paginated_chain(
            source_dict, original_chain_dict,
            offset=new_offset, limit=limit,
        )

    @classmethod
    def _build_paginated_chain(
        cls,
        source_dict: dict,
        original_chain_dict: dict,  # noqa: ARG003 — kept for symmetry/future use
        *,
        offset: int,
        limit: int,
    ) -> Chain:
        """Construct a Chain by cloning *source_chain* and inserting pagination
        ops immediately before its terminal step.

        The source_chain already contains the terminal (since terminals aren't
        pagination ops, so they survive the ``source_chain = chain - pagination``
        stripping). We insert ``offset`` + ``limit`` just before the terminal
        so pagination happens at the DB level, not after materialization.
        """
        _TERMINALS = {
            "count", "names", "text", "attr", "complexity", "materialize",
            "view", "history", "authors", "at", "diff", "blame",
        }

        base = cls.from_dict(source_dict)

        new_steps = list(base.steps)
        # Find the LAST terminal-op position and insert before it; if none,
        # append to the end.
        insert_at = len(new_steps)
        for i in range(len(new_steps) - 1, -1, -1):
            if new_steps[i].op in _TERMINALS:
                insert_at = i
                break
        new_steps.insert(insert_at, ChainStep(op="limit", args=[str(limit)]))
        new_steps.insert(insert_at, ChainStep(op="offset", args=[str(offset)]))

        return cls(
            source=list(base.source),
            steps=new_steps,
            plugins=list(base.plugins),
            repo=base.repo,
            dry_run=base.dry_run,
        )

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    _TERMINAL_OPS = frozenset({
        "count", "names", "text", "attr", "complexity", "materialize",
    })
    _QUERY_OPS = frozenset({
        "find", "filter", "filter_sql", "not_", "unique",
    })
    _NAV_OPS = frozenset({
        "parent", "children", "siblings", "ancestor",
        "next", "prev", "containing", "at_line", "at_lines",
    })
    _MUTATION_OPS = frozenset({
        "replaceWith", "addParam", "removeParam", "addArg", "removeArg",
        "insertBefore", "insertAfter", "rename", "prepend", "append",
        "wrap", "unwrap", "remove",
    })
    _PLUGIN_OPS = frozenset({
        "view", "history", "authors", "at", "diff", "blame",
    })
    _PAGINATION_OPS = frozenset({"limit", "offset", "page"})

    def evaluate(self) -> dict[str, Any]:
        """Execute this chain and return a JSON-serializable result dict.

        The evaluator resolves plugins, creates a Plucker, then walks the
        steps in order, dispatching each to the appropriate method.  A
        **selection stack** is maintained so that ``find`` pushes,
        ``pop`` pops, and ``reset`` / ``--`` clears.
        """
        from pluckit.plucker import Plucker
        from pluckit.pluckins.base import resolve_plugins
        from pluckit.selection import Selection

        # Resolve plugins
        plugin_classes = resolve_plugins(self.plugins)

        # Build Plucker — currently only supports single source string
        code = self.source[0] if len(self.source) == 1 else self.source[0]
        plucker = Plucker(code=code, plugins=plugin_classes, repo=self.repo)

        stack: list[Selection] = []
        current: Selection | None = None
        last_find_selector: str | None = None
        had_mutation = False
        result_type: str | None = None
        result_data: Any = None

        for step in self.steps:
            op = step.op

            # Control ops
            if op in ("reset", "--"):
                stack.clear()
                current = None
                continue

            if op == "pop":
                if stack:
                    current = stack.pop()
                else:
                    current = None
                continue

            # find — push current onto stack, create new selection
            if op == "find":
                if current is not None:
                    stack.append(current)
                    current = current.find(*step.args, **step.kwargs)
                else:
                    current = plucker.find(*step.args, **step.kwargs)
                last_find_selector = step.args[0] if step.args else None
                continue

            # view — special handling, called on plucker
            if op == "view":
                if step.args:
                    query = step.args[0]
                elif last_find_selector:
                    query = last_find_selector
                else:
                    query = ".fn"
                view_result = plucker.view(query)
                result_type = "view"
                result_data = view_result.to_dict()
                continue

            # Pagination ops — operate on current selection like nav ops
            if op in self._PAGINATION_OPS:
                if current is None:
                    msg = f"Pagination op '{op}' requires a selection (use find first)"
                    raise ValueError(msg)
                if op == "limit":
                    n = int(step.args[0]) if step.args else 0
                    current = current.limit(n)
                elif op == "offset":
                    n = int(step.args[0]) if step.args else 0
                    current = current.offset(n)
                elif op == "page":
                    page_num = int(step.args[0]) if len(step.args) > 0 else 0
                    page_size = int(step.args[1]) if len(step.args) > 1 else 50
                    current = current.page(page_num, page_size)
                continue

            # Terminal ops
            if op in self._TERMINAL_OPS:
                if current is None:
                    msg = f"Terminal op '{op}' requires a selection (use find first)"
                    raise ValueError(msg)
                method = getattr(current, op)
                raw = method(*step.args, **step.kwargs)
                result_type = op
                result_data = _make_json_safe(raw)
                continue

            # Query / navigation / mutation ops — all operate on current selection
            if op in self._QUERY_OPS | self._NAV_OPS | self._MUTATION_OPS:
                if current is None:
                    msg = f"Op '{op}' requires a selection (use find first)"
                    raise ValueError(msg)
                method = getattr(current, op)
                current = method(*step.args, **step.kwargs)
                if op in self._MUTATION_OPS:
                    had_mutation = True
                continue

            # Plugin ops (other than view, handled above)
            if op in self._PLUGIN_OPS:
                if current is None:
                    msg = f"Plugin op '{op}' requires a selection (use find first)"
                    raise ValueError(msg)
                method = getattr(current, op)
                raw = method(*step.args, **step.kwargs)
                result_type = op
                result_data = _make_json_safe(raw)
                continue

            msg = f"Unknown chain op: {op!r}"
            raise ValueError(msg)

        # Build final result
        if result_type is not None:
            result = {
                "chain": self.to_dict(),
                "type": result_type,
                "data": result_data,
            }
        elif had_mutation:
            # No terminal was hit, but mutations were applied
            result = {
                "chain": self.to_dict(),
                "type": "mutation",
                "data": {"applied": True},
            }
        elif current is not None:
            # Default: materialize the current selection
            rows = current.materialize()
            result = {
                "chain": self.to_dict(),
                "type": "materialize",
                "data": _make_json_safe(rows),
            }
        else:
            result = {
                "chain": self.to_dict(),
                "type": "materialize",
                "data": [],
            }

        # Attach pagination metadata if any pagination op appeared in the chain.
        self._attach_pagination_metadata(result)
        return result

    def _attach_pagination_metadata(self, result: dict[str, Any]) -> None:
        """Mutate *result* in place, adding ``source_chain`` + ``page`` keys
        when this chain contains any pagination ops.

        ``total`` is **not** computed eagerly — it defaults to ``None``.
        Call ``Chain.with_total(result)`` afterwards if you need the exact
        count (costs one extra SQL query).

        ``has_more`` is computed heuristically:
        - If ``data_length < limit``: definitively ``False`` (got fewer
          than asked for → no more).
        - If ``data_length == limit``: conservatively ``True`` (might be
          exactly the last page, but we can't know without ``total``).
        - If ``limit`` is ``None``: ``None`` (unknown).

        **Interaction notes:**

        - ``page N SIZE`` sets *both* offset and limit. A subsequent
          ``limit`` or ``offset`` op overrides the corresponding value.
          This is well-defined but potentially confusing; callers should
          use *either* ``page`` *or* ``offset`` + ``limit``, not both.
        - ``limit`` applied before a mutation restricts the mutation to
          the first N matches: ``find .fn limit 5 rename bar`` renames
          only the first 5 functions. This is correct (the Selection
          contains 5 rows at mutation time) but may surprise callers
          who expected limit to apply only to terminal output.
        """
        if not any(s.op in self._PAGINATION_OPS for s in self.steps):
            return

        # Compute effective offset / limit by walking pagination ops in order.
        effective_offset = 0
        effective_limit: int | None = None
        for step in self.steps:
            if step.op == "offset":
                effective_offset += int(step.args[0]) if step.args else 0
            elif step.op == "limit":
                effective_limit = int(step.args[0]) if step.args else None
            elif step.op == "page":
                page_num = int(step.args[0]) if len(step.args) > 0 else 0
                page_size = int(step.args[1]) if len(step.args) > 1 else 50
                effective_offset = page_num * page_size
                effective_limit = page_size

        # Build the source_chain (this chain minus pagination ops).
        source_steps = [s for s in self.steps if s.op not in self._PAGINATION_OPS]
        source_chain = Chain(
            source=self.source,
            steps=source_steps,
            plugins=self.plugins,
            repo=self.repo,
        )

        # Heuristic has_more (no extra query)
        data = result.get("data")
        if isinstance(data, list):
            data_length = len(data)
        elif isinstance(data, int):
            data_length = data
        else:
            data_length = 1

        if effective_limit is not None:
            has_more: bool | None = data_length >= effective_limit
        else:
            has_more = None

        result["source_chain"] = source_chain.to_dict()
        result["page"] = {
            "offset": effective_offset,
            "limit": effective_limit,
            "total": None,
            "has_more": has_more,
        }

    @classmethod
    def with_total(cls, evaluated_result: dict[str, Any]) -> dict[str, Any]:
        """Fill in ``page.total`` and refine ``has_more`` on a paginated result.

        Runs one extra SQL query (a ``count`` against the ``source_chain``).
        Mutates *evaluated_result* in place and also returns it for chaining.

        If the result has no pagination metadata, returns it unchanged.
        """
        page = evaluated_result.get("page")
        source_dict = evaluated_result.get("source_chain")
        if page is None or source_dict is None:
            return evaluated_result

        _NON_COUNT_TERMINALS = cls._TERMINAL_OPS | {"view"}
        source = cls.from_dict(source_dict)
        count_steps = [s for s in source.steps if s.op not in _NON_COUNT_TERMINALS]
        count_steps.append(ChainStep(op="count"))
        count_chain = Chain(
            source=source.source,
            steps=count_steps,
            plugins=source.plugins,
            repo=source.repo,
        )
        try:
            count_result = count_chain.evaluate()
            total_raw = count_result.get("data")
            total = int(total_raw) if total_raw is not None else None
        except Exception:
            total = None

        page["total"] = total
        if total is not None and page.get("limit") is not None:
            data = evaluated_result.get("data")
            data_length = len(data) if isinstance(data, list) else 1
            page["has_more"] = (page["offset"] + data_length) < total

        return evaluated_result


def _make_json_safe(obj: Any) -> Any:
    """Recursively convert non-JSON-safe types to safe equivalents."""
    import datetime
    from decimal import Decimal

    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, Decimal):
        # Use int if it's a whole number, otherwise float
        if obj == int(obj):
            return int(obj)
        return float(obj)
    if isinstance(obj, (datetime.datetime, datetime.date, datetime.time)):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, dict):
        return {str(k): _make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_json_safe(item) for item in obj]
    # Fallback: try str()
    return str(obj)
