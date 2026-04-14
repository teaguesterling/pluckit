# src/pluckit/plugins/base.py
"""Pluckin base class and registry for pluckit.

pluckit's plugins are colloquially "pluckins" — a portmanteau of
pluckit + plugin. The base class ``Pluckin`` (and its registry
``PluckinRegistry``) are the canonical names; ``Plugin`` and
``PluginRegistry`` are kept as backward-compat aliases at the bottom
of this module.
"""
from __future__ import annotations

from pluckit.types import PluckerError

_KNOWN_PROVIDERS: dict[str, str] = {
    "callers": "Calls", "callees": "Calls", "references": "Calls",
    "at": "History", "diff": "History", "blame": "History",
    "authors": "History", "history": "History", "filmstrip": "History",
    "when": "History", "co_changes": "History",
    "interface": "Scope", "refs": "Scope", "defs": "Scope",
    "scope": "Scope", "shadows": "Scope", "unused_params": "Scope",
    "view": "AstViewer",
}

_PLUGIN_MAP: dict[str, str] = {
    "AstViewer": "pluckit.plugins.viewer:AstViewer",
    "History": "pluckit.plugins.history:History",
    "Calls": "pluckit.plugins.calls:Calls",
    "Scope": "pluckit.plugins.scope:Scope",
}


def resolve_plugins(names: list[str]) -> list[type[Pluckin]]:
    """Resolve plugin names to classes.

    Accepts short names ("AstViewer") or fully-qualified import
    paths ("mypackage.plugins:MyPlugin").
    """
    import importlib

    classes: list[type[Pluckin]] = []
    for name in names:
        if name in _PLUGIN_MAP:
            dotted = _PLUGIN_MAP[name]
        elif ":" in name:
            dotted = name
        else:
            raise PluckerError(
                f"Unknown plugin {name!r}. Known plugins: "
                f"{', '.join(sorted(_PLUGIN_MAP.keys()))}. "
                f"For custom plugins, use 'module.path:ClassName'."
            )
        module_path, class_name = dotted.rsplit(":", 1)
        try:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
        except (ImportError, AttributeError) as e:
            raise PluckerError(
                f"Failed to import plugin {name!r} from {dotted!r}: {e}"
            ) from e
        classes.append(cls)
    return classes


class Pluckin:
    """Base class for pluckit pluckins."""
    name: str = ""
    methods: dict[str, str] = {}         # {public_name: implementation_method_name}
    pseudo_classes: dict[str, dict] = {} # {pseudo_class_name: config_dict}
    upgrades: dict[str, str] = {}        # {existing_method: upgrade_method_name}


class PluckinRegistry:
    """Holds registered pluckins and dispatches method lookups."""

    def __init__(self) -> None:
        self.methods: dict[str, tuple[Pluckin, str]] = {}
        self.upgrades: dict[str, tuple[Pluckin, str]] = {}
        self.pseudo_classes: dict[str, dict] = {}
        self._pluckins: list[Pluckin] = []

    @property
    def pluckins(self) -> list[Pluckin]:
        """All registered pluckin instances, in registration order.

        Designed for downstream consumers (e.g., squackit) that want to
        enumerate pluckins for tool/integration discovery without
        coupling pluckit to specific consumer APIs.
        """
        return list(self._pluckins)

    def register(self, plugin: Pluckin) -> None:
        """Register a pluckin instance.

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

        self._pluckins.append(plugin)

    def method_provider(self, method_name: str) -> str | None:
        """Return the plugin name that provides *method_name*, or None.

        Checks registered pluckins first, then the hardcoded _KNOWN_PROVIDERS
        dict so callers get helpful error messages even when a plugin is not loaded.
        """
        if method_name in self.methods:
            return self.methods[method_name][0].name
        return _KNOWN_PROVIDERS.get(method_name)


# Backward-compat aliases — pluckit's base class was renamed Plugin → Pluckin
# in v0.9.0 for brand consistency. Existing plugins importing Plugin keep
# working; new code should prefer Pluckin.
Plugin = Pluckin
PluginRegistry = PluckinRegistry
