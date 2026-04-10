# src/pluckit/plugins/base.py
"""Plugin base class and registry for pluckit."""
from __future__ import annotations

from pluckit.types import PluckerError

_KNOWN_PROVIDERS: dict[str, str] = {
    "callers": "Calls", "callees": "Calls", "references": "Calls",
    "at": "History", "diff": "History", "blame": "History",
    "authors": "History", "history": "History", "filmstrip": "History",
    "when": "History", "co_changes": "History",
    "interface": "Scope", "refs": "Scope", "defs": "Scope",
    "shadows": "Scope", "unused_params": "Scope",
    "view": "AstViewer",
}


class Plugin:
    """Base class for pluckit plugins."""
    name: str = ""
    methods: dict[str, str] = {}         # {public_name: implementation_method_name}
    pseudo_classes: dict[str, dict] = {} # {pseudo_class_name: config_dict}
    upgrades: dict[str, str] = {}        # {existing_method: upgrade_method_name}


class PluginRegistry:
    """Holds registered plugins and dispatches method lookups."""

    def __init__(self) -> None:
        self.methods: dict[str, tuple[Plugin, str]] = {}
        self.upgrades: dict[str, tuple[Plugin, str]] = {}
        self.pseudo_classes: dict[str, dict] = {}

    def register(self, plugin: Plugin) -> None:
        """Register a plugin instance.

        Raises PluckerError if a duplicate public method name is encountered.
        """
        for public_name, impl_name in plugin.methods.items():
            if public_name in self.methods:
                existing = self.methods[public_name][0].name
                raise PluckerError(
                    f"Method '{public_name}' is already registered by plugin '{existing}'. "
                    f"Cannot also register it from plugin '{plugin.name}'."
                )
            self.methods[public_name] = (plugin, impl_name)

        for pseudo_name, config in plugin.pseudo_classes.items():
            self.pseudo_classes[pseudo_name] = config

        for method_name, upgrade_impl in plugin.upgrades.items():
            self.upgrades[method_name] = (plugin, upgrade_impl)

    def method_provider(self, method_name: str) -> str | None:
        """Return the plugin name that provides *method_name*, or None.

        Checks registered plugins first, then the hardcoded _KNOWN_PROVIDERS
        dict so callers get helpful error messages even when a plugin is not loaded.
        """
        if method_name in self.methods:
            return self.methods[method_name][0].name
        return _KNOWN_PROVIDERS.get(method_name)
