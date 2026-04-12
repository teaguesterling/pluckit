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

    def evaluate(self) -> dict[str, Any]:
        """Execute this chain and return a JSON-serializable result dict.

        The evaluator resolves plugins, creates a Plucker, then walks the
        steps in order, dispatching each to the appropriate method.  A
        **selection stack** is maintained so that ``find`` pushes,
        ``pop`` pops, and ``reset`` / ``--`` clears.
        """
        from pluckit.plucker import Plucker
        from pluckit.plugins.base import resolve_plugins
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
            return {
                "chain": self.to_dict(),
                "type": result_type,
                "data": result_data,
            }

        # No terminal was hit
        if had_mutation:
            return {
                "chain": self.to_dict(),
                "type": "mutation",
                "data": {"applied": True},
            }

        # Default: materialize the current selection
        if current is not None:
            rows = current.materialize()
            return {
                "chain": self.to_dict(),
                "type": "materialize",
                "data": _make_json_safe(rows),
            }

        return {
            "chain": self.to_dict(),
            "type": "materialize",
            "data": [],
        }


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
