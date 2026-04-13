"""Selector type — a validated, serializable CSS-over-AST selector string."""
from __future__ import annotations

import json as _json
from typing import Any


class Selector(str):
    """A CSS-like AST selector string with validation and serialization.

    Subclasses str — usable everywhere a bare selector string works today.
    """

    @property
    def is_valid(self) -> bool:
        try:
            self.validate()
            return True
        except Exception:
            return False

    def validate(self) -> None:
        from pluckit._sql import _selector_to_where
        from pluckit.types import PluckerError

        try:
            result = _selector_to_where(str(self))
        except Exception as e:
            raise PluckerError(f"Invalid selector {self!r}: {e}") from e
        if result == "1=0":
            raise PluckerError(
                f"Selector {self!r} resolved to a taxonomy class with no "
                f"known semantic type code — it would match nothing."
            )

    def to_dict(self) -> dict[str, Any]:
        return {"selector": str(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Selector:
        if "selector" not in data:
            raise ValueError("Selector.from_dict requires a 'selector' key")
        return cls(data["selector"])

    def to_json(self, **kwargs: Any) -> str:
        return _json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_json(cls, text: str) -> Selector:
        return cls.from_dict(_json.loads(text))

    def to_argv(self) -> list[str]:
        return [str(self)]

    @classmethod
    def from_argv(cls, tokens: list[str]) -> Selector:
        if not tokens:
            raise ValueError("Selector.from_argv requires at least one token")
        return cls(tokens[0])
