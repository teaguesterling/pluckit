# tests/test_selection_plugins.py
"""Tests for Selection plugin delegation via __getattr__."""
import os

import pytest

from pluckit._context import _Context
from pluckit._sql import ast_select_sql
from pluckit.plugins.base import Pluckin, PluckinRegistry
from pluckit.selection import Selection
from pluckit.types import PluckerError


class CountPlugin(Pluckin):
    name = "counter"
    methods = {"double_count": "_double_count"}

    def _double_count(self, selection) -> int:
        return selection.count() * 2


@pytest.fixture
def registry():
    reg = PluckinRegistry()
    reg.register(CountPlugin())
    return reg


@pytest.fixture
def selection_with_plugin(sample_dir, registry):
    ctx = _Context(repo=str(sample_dir))
    sql = ast_select_sql(os.path.join(str(sample_dir), "src/**/*.py"), ".function")
    rel = ctx.db.sql(sql)
    return Selection(rel, ctx, registry)


@pytest.fixture
def selection_no_plugin(sample_dir):
    ctx = _Context(repo=str(sample_dir))
    sql = ast_select_sql(os.path.join(str(sample_dir), "src/**/*.py"), ".function")
    rel = ctx.db.sql(sql)
    return Selection(rel, ctx)


class TestPluginDelegation:
    def test_plugin_method_works(self, selection_with_plugin):
        result = selection_with_plugin.double_count()
        assert isinstance(result, int)
        assert result == selection_with_plugin.count() * 2

    def test_core_methods_still_work(self, selection_with_plugin):
        assert selection_with_plugin.count() > 0
        assert len(selection_with_plugin.names()) > 0

    def test_unknown_method_raises_attribute_error(self, selection_with_plugin):
        with pytest.raises(AttributeError, match="no method"):
            selection_with_plugin.totally_fake_method()

    def test_known_unloaded_plugin_raises_plucker_error(self, selection_with_plugin):
        # callers is known to belong to Calls plugin
        with pytest.raises(PluckerError, match="Calls"):
            selection_with_plugin.callers()

    def test_no_registry_core_still_works(self, selection_no_plugin):
        assert selection_no_plugin.count() > 0

    def test_no_registry_known_method_raises_plucker_error(self, selection_no_plugin):
        with pytest.raises(PluckerError, match="Calls"):
            selection_no_plugin.callers()

    def test_no_registry_unknown_raises_attribute_error(self, selection_no_plugin):
        with pytest.raises(AttributeError):
            selection_no_plugin.totally_fake_method()
