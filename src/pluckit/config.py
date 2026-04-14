"""Project config reader — loads ``[tool.pluckit]`` from ``pyproject.toml``."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


@dataclass
class PluckitConfig:
    """Runtime configuration sourced from ``pyproject.toml``."""

    plugins: list[str] = field(default_factory=lambda: ["AstViewer"])
    sources: dict[str, str] = field(default_factory=dict)
    repo: str | None = None
    cache: bool = False
    cache_path: str = ".pluckit.duckdb"

    # ------------------------------------------------------------------
    # Source resolution
    # ------------------------------------------------------------------

    def resolve_source(self, name_or_glob: str) -> list[str]:
        """Return the mapped source value if *name_or_glob* is a shortcut, else pass through."""
        if name_or_glob in self.sources:
            return [self.sources[name_or_glob]]
        return [name_or_glob]

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, root: str | Path | None = None) -> PluckitConfig:
        """Read ``pyproject.toml`` from *root* (default: cwd) and return config."""
        root_path = Path(root) if root is not None else Path.cwd()
        pyproject = root_path / "pyproject.toml"

        if not pyproject.is_file():
            return cls()

        with pyproject.open("rb") as fh:
            data = tomllib.load(fh)

        section = data.get("tool", {}).get("pluckit", {})
        if not section:
            return cls()

        return cls(
            plugins=section.get("plugins", ["AstViewer"]),
            sources=section.get("sources", {}),
            repo=section.get("repo"),
            cache=section.get("cache", False),
            cache_path=section.get("cache_path", ".pluckit.duckdb"),
        )
