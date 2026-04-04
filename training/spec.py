"""Spec loader — parse reference/api.yaml into Python objects.

Usage:
    from training.spec import load_spec
    spec = load_spec("reference/api.yaml")
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TypeInfo:
    name: str
    description: str
    produces: list[str]


@dataclass
class Operation:
    name: str
    signature: str
    category: str
    status: str = "implemented"  # "implemented" or "planned"
    input_type: str | None = None
    output_type: str | None = None
    description: str | None = None
    examples: list[dict] | None = None
    param_examples: list[str] | None = None
    predicate_examples: list[dict] | None = None
    strategy_examples: list[str] | None = None
    ref_examples: list[str] | None = None


@dataclass
class Selectors:
    node_types: list[dict]
    pseudo_selectors: list[dict]
    attribute_selectors: list[dict]
    combinators: list[dict]
    name_selector_syntax: str
    name_selector_examples: list[dict]


@dataclass
class Spec:
    version: str
    types: dict[str, TypeInfo]
    operations: dict[str, Operation]
    selectors: Selectors
    composition: dict[str, Any]
    example_chains: dict[str, list[dict]]


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _parse_types(raw: dict) -> dict[str, TypeInfo]:
    result: dict[str, TypeInfo] = {}
    for name, data in raw.items():
        result[name] = TypeInfo(
            name=name,
            description=data.get("description", ""),
            produces=data.get("produces", []),
        )
    return result


def _output_type_from_signature(signature: str) -> str | None:
    """Extract the return type from a signature string like 'fn(...) -> Type'.

    Returns the type name, or None if the signature has no return annotation.
    """
    if "->" not in signature:
        return None
    after_arrow = signature.split("->")[-1].strip()
    # Take the first token (handles things like "str | list[str]" -> "str")
    # but for our purposes we want the primary type name
    return after_arrow.split()[0].rstrip(",;")


def _parse_operation(raw: dict) -> Operation:
    """Parse a single operation dict from the YAML.

    The ``output_type`` is taken from the ``output`` field when present;
    otherwise it is inferred from the return annotation in ``signature``.
    """
    output_type = raw.get("output")
    if output_type is None:
        output_type = _output_type_from_signature(raw.get("signature", ""))
    return Operation(
        name=raw["name"],
        signature=raw["signature"],
        category=raw["category"],
        status=raw.get("status", "implemented"),
        input_type=raw.get("input"),
        output_type=output_type,
        description=raw.get("description"),
        examples=raw.get("examples"),
        param_examples=raw.get("param_examples"),
        predicate_examples=raw.get("predicate_examples"),
        strategy_examples=raw.get("strategy_examples"),
        ref_examples=raw.get("ref_examples"),
    )


def _parse_operations(raw: dict) -> dict[str, Operation]:
    """Flatten all operation groups into a single dict keyed by operation name.

    When two groups define an operation with the same name (e.g. ``filter``
    appears in both ``query`` and ``history_ops``), the first definition
    encountered wins.  This preserves optional fields such as
    ``predicate_examples`` that may only be present on the primary definition.
    """
    result: dict[str, Operation] = {}
    for _group_name, ops in raw.items():
        for op_raw in ops:
            op = _parse_operation(op_raw)
            if op.name not in result:
                result[op.name] = op
    return result


def _parse_selectors(raw: dict) -> Selectors:
    name_selector = raw.get("name_selector", {})
    return Selectors(
        node_types=raw.get("node_types", []),
        pseudo_selectors=raw.get("pseudo_selectors", []),
        attribute_selectors=raw.get("attribute_selectors", []),
        combinators=raw.get("combinators", []),
        name_selector_syntax=name_selector.get("syntax", ""),
        name_selector_examples=name_selector.get("examples", []),
    )


def _parse_composition(raw: dict) -> dict[str, Any]:
    """Return composition as-is from YAML.

    Values are either a list (e.g. Source, Isolated, History) or a dict of
    category -> list (e.g. Selection).
    """
    return dict(raw)


def _parse_example_chains(raw: dict) -> dict[str, list[dict]]:
    return dict(raw)


def load_spec(path: str | Path) -> Spec:
    """Load and parse the api.yaml spec file.

    Args:
        path: Path to api.yaml (absolute or relative to cwd).

    Returns:
        A fully populated :class:`Spec` object.
    """
    path = Path(path)
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    return Spec(
        version=str(raw["version"]),
        types=_parse_types(raw["types"]),
        operations=_parse_operations(raw["operations"]),
        selectors=_parse_selectors(raw["selectors"]),
        composition=_parse_composition(raw["composition"]),
        example_chains=_parse_example_chains(raw["example_chains"]),
    )
