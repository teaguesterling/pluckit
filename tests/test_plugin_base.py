# tests/test_plugin_base.py
"""Tests for Plugin base class and PluginRegistry."""
from __future__ import annotations

import pytest

from pluckit.plugins import Plugin, PluginRegistry
from pluckit.types import PluckerError

# ---------------------------------------------------------------------------
# Dummy plugins used across multiple tests
# ---------------------------------------------------------------------------

class DummyPlugin(Plugin):
    name = "dummy"
    methods = {"greet": "_greet"}

    def _greet(self, selection, name="world"):
        return f"hello {name}"


class AnotherPlugin(Plugin):
    name = "another"
    methods = {"farewell": "_farewell"}

    def _farewell(self, selection):
        return "goodbye"


class UpgradePlugin(Plugin):
    name = "upgrader"
    upgrades = {"greet": "_upgrade_greet"}

    def _upgrade_greet(self, core_result, original_selection):
        return f"{core_result}!"


class PseudoPlugin(Plugin):
    name = "pseudo"
    pseudo_classes = {"focused": {"filter": "is_focused"}}


# ---------------------------------------------------------------------------
# Plugin class attribute tests
# ---------------------------------------------------------------------------

def test_plugin_has_name():
    p = DummyPlugin()
    assert p.name == "dummy"


def test_plugin_has_methods():
    p = DummyPlugin()
    assert p.methods == {"greet": "_greet"}


def test_plugin_default_pseudo_classes():
    p = DummyPlugin()
    assert p.pseudo_classes == {}


def test_plugin_default_upgrades():
    p = DummyPlugin()
    assert p.upgrades == {}


def test_plugin_with_pseudo_classes():
    p = PseudoPlugin()
    assert p.pseudo_classes == {"focused": {"filter": "is_focused"}}


def test_plugin_with_upgrades():
    p = UpgradePlugin()
    assert p.upgrades == {"greet": "_upgrade_greet"}


# ---------------------------------------------------------------------------
# PluginRegistry.register() — basic method registration
# ---------------------------------------------------------------------------

def test_register_adds_method():
    registry = PluginRegistry()
    plugin = DummyPlugin()
    registry.register(plugin)
    assert "greet" in registry.methods


def test_register_lookup_returns_plugin_and_impl():
    registry = PluginRegistry()
    plugin = DummyPlugin()
    registry.register(plugin)
    provider, impl_name = registry.methods["greet"]
    assert provider is plugin
    assert impl_name == "_greet"


def test_calling_through_registry_works():
    registry = PluginRegistry()
    plugin = DummyPlugin()
    registry.register(plugin)
    provider, impl_name = registry.methods["greet"]
    result = getattr(provider, impl_name)(selection=None, name="pytest")
    assert result == "hello pytest"


def test_multiple_plugins_register_correctly():
    registry = PluginRegistry()
    dummy = DummyPlugin()
    another = AnotherPlugin()
    registry.register(dummy)
    registry.register(another)
    assert "greet" in registry.methods
    assert "farewell" in registry.methods
    assert registry.methods["greet"][0] is dummy
    assert registry.methods["farewell"][0] is another


def test_duplicate_method_name_raises_plucker_error():
    registry = PluginRegistry()
    registry.register(DummyPlugin())
    with pytest.raises(PluckerError):
        registry.register(DummyPlugin())


# ---------------------------------------------------------------------------
# PluginRegistry — pseudo_classes
# ---------------------------------------------------------------------------

def test_register_adds_pseudo_classes():
    registry = PluginRegistry()
    registry.register(PseudoPlugin())
    assert "focused" in registry.pseudo_classes
    assert registry.pseudo_classes["focused"] == {"filter": "is_focused"}


# ---------------------------------------------------------------------------
# PluginRegistry — upgrades
# ---------------------------------------------------------------------------

def test_register_adds_upgrades():
    registry = PluginRegistry()
    registry.register(DummyPlugin())
    registry.register(UpgradePlugin())
    assert "greet" in registry.upgrades
    provider, impl_name = registry.upgrades["greet"]
    assert provider is registry.upgrades["greet"][0]
    assert impl_name == "_upgrade_greet"


def test_calling_upgrade_through_registry():
    registry = PluginRegistry()
    dummy = DummyPlugin()
    upgrader = UpgradePlugin()
    registry.register(dummy)
    registry.register(upgrader)
    provider, impl_name = registry.upgrades["greet"]
    result = getattr(provider, impl_name)(core_result="hello world", original_selection=None)
    assert result == "hello world!"


# ---------------------------------------------------------------------------
# PluginRegistry.method_provider()
# ---------------------------------------------------------------------------

def test_method_provider_returns_registered_plugin_name():
    registry = PluginRegistry()
    registry.register(DummyPlugin())
    assert registry.method_provider("greet") == "dummy"


def test_method_provider_callers_returns_calls():
    registry = PluginRegistry()
    assert registry.method_provider("callers") == "Calls"


def test_method_provider_at_returns_history():
    registry = PluginRegistry()
    assert registry.method_provider("at") == "History"


def test_method_provider_interface_returns_scope():
    registry = PluginRegistry()
    assert registry.method_provider("interface") == "Scope"


def test_method_provider_unknown_returns_none():
    registry = PluginRegistry()
    assert registry.method_provider("totally_unknown_method") is None


def test_method_provider_prefers_registered_over_known():
    """If a plugin is registered for a name that's also in _KNOWN_PROVIDERS,
    the registered plugin's name takes priority."""
    class CallsOverride(Plugin):
        name = "my_calls"
        methods = {"callers": "_callers"}
        def _callers(self, selection): ...

    registry = PluginRegistry()
    registry.register(CallsOverride())
    assert registry.method_provider("callers") == "my_calls"
