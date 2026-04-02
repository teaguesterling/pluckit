"""Tests for selector alias resolution and pseudo-class registry."""
import pytest

from pluckit.selectors import resolve_alias, PseudoClassRegistry, ALIASES


class TestAliases:
    def test_fn_resolves(self):
        assert resolve_alias(".fn") == ".def-func"

    def test_cls_resolves(self):
        assert resolve_alias(".cls") == ".def-class"

    def test_call_resolves(self):
        assert resolve_alias(".call") == ".access-call"

    def test_ret_resolves(self):
        assert resolve_alias(".ret") == ".flow-jump"

    def test_import_resolves(self):
        assert resolve_alias(".import") == ".external-import"

    def test_except_resolves(self):
        assert resolve_alias(".except") == ".error-catch"

    def test_raise_resolves(self):
        assert resolve_alias(".raise") == ".error-throw"

    def test_str_resolves(self):
        assert resolve_alias(".str") == ".literal-str"

    def test_num_resolves(self):
        assert resolve_alias(".num") == ".literal-num"

    def test_assign_resolves(self):
        assert resolve_alias(".assign") == ".statement-assign"

    def test_preserves_id_suffix(self):
        assert resolve_alias(".fn#validate") == ".def-func#validate"

    def test_preserves_attr_suffix(self):
        assert resolve_alias(".fn[name^='test_']") == ".def-func[name^='test_']"

    def test_unknown_passes_through(self):
        assert resolve_alias(".function_definition") == ".function_definition"

    def test_no_dot_passes_through(self):
        assert resolve_alias("function_definition") == "function_definition"


class TestPseudoClassRegistry:
    def test_builtin_exported(self):
        reg = PseudoClassRegistry()
        entry = reg.get(":exported")
        assert entry is not None
        assert entry.engine == "sitting_duck"

    def test_builtin_line(self):
        reg = PseudoClassRegistry()
        entry = reg.get(":line")
        assert entry is not None
        assert entry.takes_arg is True

    def test_register_custom(self):
        reg = PseudoClassRegistry()
        reg.register(":orphan", engine="fledgling")
        entry = reg.get(":orphan")
        assert entry is not None
        assert entry.engine == "fledgling"

    def test_unknown_returns_none(self):
        reg = PseudoClassRegistry()
        assert reg.get(":nonexistent") is None

    def test_classify_by_engine(self):
        reg = PseudoClassRegistry()
        reg.register(":orphan", engine="fledgling")
        groups = reg.classify([":exported", ":orphan", ":line"])
        assert ":exported" in groups["sitting_duck"]
        assert ":orphan" in groups["fledgling"]
        assert ":line" in groups["sitting_duck"]

    def test_classify_unknown(self):
        reg = PseudoClassRegistry()
        groups = reg.classify([":nonexistent"])
        assert ":nonexistent" in groups["unknown"]
