"""Tests for the Selector type."""
from __future__ import annotations

import pytest

from pluckit.selector import Selector


class TestSelectorBasics:
    def test_is_a_string(self):
        s = Selector(".fn:exported")
        assert isinstance(s, str)
        assert s == ".fn:exported"

    def test_usable_as_string_argument(self):
        s = Selector(".fn#main")
        assert s.startswith(".fn")
        assert "main" in s

    def test_empty_selector(self):
        s = Selector("")
        assert s == ""


class TestSelectorValidation:
    def test_valid_selector(self):
        s = Selector(".fn:exported")
        assert s.is_valid

    def test_validate_does_not_raise_on_valid(self):
        Selector(".fn#main").validate()

    def test_is_valid_on_raw_type(self):
        assert Selector("function_definition").is_valid


class TestSelectorSerialization:
    def test_to_dict(self):
        assert Selector(".fn:exported").to_dict() == {"selector": ".fn:exported"}

    def test_from_dict(self):
        s = Selector.from_dict({"selector": ".fn#main"})
        assert s == ".fn#main"
        assert isinstance(s, Selector)

    def test_from_dict_missing_key_raises(self):
        with pytest.raises(ValueError, match="selector"):
            Selector.from_dict({})

    def test_to_json_round_trip(self):
        s = Selector(".cls#Config")
        restored = Selector.from_json(s.to_json())
        assert restored == s
        assert isinstance(restored, Selector)

    def test_to_argv(self):
        assert Selector(".fn[name^=test_]").to_argv() == [".fn[name^=test_]"]

    def test_from_argv(self):
        s = Selector.from_argv([".fn:exported"])
        assert s == ".fn:exported"
        assert isinstance(s, Selector)
