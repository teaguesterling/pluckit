"""pluckit — a fluent API for querying, analyzing, and mutating source code."""
from pluckit.plucker import Plucker
from pluckit.plugins.base import Plugin, PluginRegistry
from pluckit.plugins.viewer import AstViewer
from pluckit.types import DiffResult, InterfaceInfo, NodeInfo, PluckerError


def view(query: str, *, code: str = "**/*", format: str = "markdown") -> str:
    """Module-level convenience: render a viewer query against the current directory.

    Creates an ephemeral Plucker with the AstViewer plugin loaded, runs the
    query, and returns the rendered output. For repeated queries against the
    same workspace, construct a Plucker explicitly:

        from pluckit import Plucker, AstViewer
        pluck = Plucker(code="src/**/*.py", plugins=[AstViewer])
        pluck.view(".fn#main")
    """
    pluck = Plucker(code=code, plugins=[AstViewer])
    return pluck.view(query, format=format)


__all__ = [
    "Plucker",
    "Plugin",
    "PluginRegistry",
    "AstViewer",
    "PluckerError",
    "NodeInfo",
    "DiffResult",
    "InterfaceInfo",
    "view",
]
