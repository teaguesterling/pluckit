"""pluckit — a fluent API for querying, analyzing, and mutating source code."""
from pluckit.cache import ASTCache
from pluckit.chain import Chain, ChainStep
from pluckit.config import PluckitConfig
from pluckit.isolated import Isolated
from pluckit.plucker import Plucker
from pluckit.pluckins.base import Pluckin, PluckinRegistry, Plugin, PluginRegistry
from pluckit.pluckins.calls import Calls
from pluckit.pluckins.history import Commit, History
from pluckit.pluckins.scope import Scope
from pluckit.pluckins.viewer import AstViewer, View, ViewBlock
from pluckit.selection import Selection
from pluckit.selector import Selector
from pluckit.types import DiffResult, InterfaceInfo, NodeInfo, PluckerError


def view(query: str, *, code: str = "**/*", format: str = "markdown") -> View:
    """Module-level convenience: render a viewer query against a code corpus.

    Creates an ephemeral Plucker with the AstViewer plugin loaded, runs the
    query, and returns the rendered :class:`View`. For repeated queries
    against the same workspace, construct a Plucker explicitly:

        from pluckit import Plucker, AstViewer
        pluck = Plucker(code="src/**/*.py", plugins=[AstViewer])
        result = pluck.view(".fn#main")
        print(result)           # markdown output
        print(result.files)     # file paths touched
    """
    pluck = Plucker(code=code, plugins=[AstViewer])
    return pluck.view(query, format=format)


def find(
    selector: str,
    *,
    code: str = "**/*",
    repo: str | None = None,
) -> list[tuple[str, int, str]]:
    """Module-level convenience: run a selector and return match locations.

    Returns a list of ``(file_path, start_line, name)`` tuples. For the full
    Selection API (navigation, mutation, filtering, terminal methods), use
    ``Plucker.find`` instead:

        from pluckit import Plucker
        pluck = Plucker(code="src/**/*.py")
        sel = pluck.find(".fn:exported")
        print(sel.count(), sel.names())

    This shortcut is designed for quick one-shot queries:

        for path, line, name in find(".fn:exported", code="src/**/*.py"):
            print(f"{path}:{line}:{name}")
    """
    pluck = Plucker(code=code, repo=repo)
    selection = pluck.find(selector)
    rows = selection.materialize()
    return [
        (row["file_path"], row["start_line"], row.get("name") or row.get("type", ""))
        for row in rows
    ]


__all__ = [
    # Core
    "Plucker",
    "Selection",
    "Selector",
    "PluckerError",
    # Chain
    "Chain",
    "ChainStep",
    # Config / cache
    "PluckitConfig",
    "ASTCache",
    # Pluckins (plugins)
    "Pluckin",
    "PluckinRegistry",
    "Plugin",
    "PluginRegistry",
    "AstViewer",
    "History",
    "Commit",
    "Calls",
    "Scope",
    # View result types
    "View",
    "ViewBlock",
    # Data types
    "NodeInfo",
    "DiffResult",
    "InterfaceInfo",
    "Isolated",
    # Module-level shortcuts
    "view",
    "find",
]
