"""Tests for selector alias resolution and pseudo-class registry."""

from pluckit.selectors import PseudoClassRegistry, resolve_alias, split_post_filters


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


class TestPostFilters:
    """Pluckit's value-add pseudo-classes (sitting_duck can't express these) are split off
    from the structural selector and applied as a SQL post-filter on the delegated result."""

    def test_decorated_and_async_have_templates(self):
        reg = PseudoClassRegistry()
        # Previously dead stubs (sql_template=None); now expressed over read_ast columns.
        assert reg.get(":decorated").sql_template == "len(modifiers) > 0"
        assert reg.get(":async").sql_template == "peek LIKE 'async %'"

    def test_wide_and_last_dropped(self):
        reg = PseudoClassRegistry()
        assert reg.get(":wide") is None
        assert reg.get(":last") is None

    def test_split_extracts_top_level_pseudo(self):
        structural, conds = split_post_filters(".fn:exported:complex(5)")
        assert structural == ".fn"
        assert any("NOT LIKE" in c for c in conds)
        assert any("descendant_count > 5" in c for c in conds)

    def test_split_leaves_nested_pseudo_for_sitting_duck(self):
        # :exported inside :has() is sitting_duck's to handle, not a pluckit post-filter.
        structural, conds = split_post_filters(".fn:has(.call#x:exported)")
        assert ":exported" in structural
        assert conds == []

    def test_split_passes_through_plain_selector(self):
        structural, conds = split_post_filters(".fn#main")
        assert structural == ".fn#main"
        assert conds == []


class TestPostFilterFind:
    """End-to-end: the revived :decorated / :async pseudo-classes filter via delegation."""

    def test_decorated_and_async(self, tmp_path):
        from pluckit import Plucker

        (tmp_path / "m.py").write_text(
            "import functools\n"
            "def plain(): pass\n"
            "async def fetch(): pass\n"
            "@functools.cache\n"
            "def cached(): pass\n"
        )
        p = Plucker(code="*.py", repo=str(tmp_path))
        assert set(p.find(".fn:decorated").names()) == {"cached"}
        assert set(p.find(".fn:async").names()) == {"fetch"}
        # :contains is peek-based (the node's own source) — exercises peek recovery,
        # since ast_select nulls peek. "plain" appears only in `def plain(): pass`.
        assert set(p.find(".fn:contains(plain)").names()) == {"plain"}
        # sanity: all three are functions; :exported (no underscore) keeps all
        assert {"plain", "fetch", "cached"} <= set(p.find(".fn:exported").names())
