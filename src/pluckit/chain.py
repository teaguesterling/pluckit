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
