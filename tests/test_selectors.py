"""Tests for selector alias resolution and pseudo-class registry."""

import pytest

from pluckit.selectors import (
    PseudoClassRegistry,
    SelectorArgError,
    UnknownSelectorClassError,
    resolve_alias,
    resolve_aliases,
    split_post_filters,
)


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


class TestAliasDriftRegression:
    """Issue #10: documented aliases must resolve to their documented targets.

    docs/selectors.md advertises these aliases; on drifted code they either
    passed through unresolved (matching the wrong sitting_duck alias, or
    nothing at all) or resolved to the wrong semantic-type class.
    """

    def test_def_is_function_definition(self):
        # docs: `.def` ≡ `.fn`. On drifted code it passed through to
        # sitting_duck's kind-level DEF alias (every definition).
        assert resolve_alias(".def") == ".def-func"
        assert resolve_aliases(".def") == ".definition_function"

    def test_let_is_variable_definition(self):
        assert resolve_alias(".let") == ".def-var"
        assert resolve_aliases(".let") == ".definition_variable"

    def test_jump_is_flow_jump(self):
        assert resolve_alias(".jump") == ".flow-jump"
        assert resolve_aliases(".jump") == ".flow_jump"

    def test_module_family_is_def_module(self):
        # docs: `.module`/`.ns`/`.namespace` → def-module. On drifted code
        # they resolved to .block-ns → .organization_block (every block).
        for alias in (".module", ".ns", ".namespace", ".package"):
            assert resolve_alias(alias) == ".def-module", alias
            assert resolve_aliases(alias) == ".definition_module", alias

    def test_bool_and_null_are_atomic_literals(self):
        # sitting_duck classifies True/False/None as LITERAL_ATOMIC. On
        # drifted code .bool resolved to the unmapped .literal-bool (matched
        # nothing) and .null/.none to .literal-str (string literals).
        for alias in (".bool", ".boolean", ".null", ".none"):
            assert resolve_alias(alias) == ".literal-atom", alias
            assert resolve_aliases(alias) == ".literal_atomic", alias

    def test_assert_is_error_throw(self):
        # Empirically (installed sitting_duck build): python assert_statement
        # → ERROR_THROW. Previously .assert → .flow-guard (matched nothing).
        assert resolve_aliases(".assert") == ".error_throw"

    def test_union_is_class_definition(self):
        # union_specifier → DEFINITION_CLASS, same bucket as .struct.
        # Previously .union → .typedef-union (matched nothing).
        assert resolve_aliases(".union") == ".definition_class"

    def test_delete_is_execution_mutation(self):
        # python delete_statement → EXECUTION_MUTATION. Previously
        # .statement-delete was unmapped (matched nothing).
        assert resolve_aliases(".del") == ".execution_mutation"
        assert resolve_aliases(".delete") == ".execution_mutation"

    def test_comprehension_is_transform_query(self):
        # list/dict/generator comprehensions → TRANSFORM_QUERY. Previously
        # .transform-comp was unmapped (matched nothing).
        assert resolve_aliases(".comp") == ".transform_query"
        assert resolve_aliases(".comprehension") == ".transform_query"

    def test_include_and_extern_map_to_external(self):
        # preproc_include → EXTERNAL_IMPORT; extern/FFI → EXTERNAL_FOREIGN.
        # Previously both taxonomy classes were unmapped (matched nothing).
        assert resolve_aliases(".include") == ".external_import"
        assert resolve_aliases(".extern") == ".external_foreign"
        assert resolve_aliases(".ffi") == ".external_foreign"

    def test_attribute_values_are_not_rewritten(self):
        # Alias substitution must not rewrite [attr] *values*: previously
        # `.fn[name*=.str]` became `[name*=.literal_string]`.
        assert (
            resolve_aliases(".fn[name*=.str]")
            == ".definition_function[name*=.str]"
        )

    def test_quoted_attribute_values_are_not_rewritten(self):
        assert (
            resolve_aliases(".fn[name^='.str']")
            == ".definition_function[name^='.str']"
        )

    def test_aliases_inside_has_are_still_resolved(self):
        # :has()/:not() args are sub-selectors — aliases resolve there too.
        assert (
            resolve_aliases(".fn:has(.call#x)")
            == ".definition_function:has(.computation_call#x)"
        )


class TestUnknownClassLoudness:
    """A selector class that would compile to `match nothing` must raise,
    not silently return an empty result."""

    def test_self_this_super_raise(self):
        # The engine classifies python `self` as a plain identifier; the old
        # mapping resolved .self/.this/.super to .name_identifier (EVERY
        # identifier — silently wrong). They now fail loudly with guidance.
        for alias in (".self", ".this", ".super", ".base"):
            with pytest.raises(UnknownSelectorClassError):
                resolve_aliases(alias)

    def test_unmapped_taxonomy_classes_raise(self):
        # Documented-ish aliases with no sitting_duck equivalent used to
        # silently match nothing.
        for sel in (".guard", ".doc", ".docstring", ".new", ".constructor",
                    ".bits", ".bitwise", ".gen", ".generator", ".void",
                    ".any", ".never", ".block-ns"):
            with pytest.raises(UnknownSelectorClassError):
                resolve_aliases(sel)

    def test_typoed_class_raises(self):
        # A typo'd or removed alias must not resolve to WHERE false.
        with pytest.raises(UnknownSelectorClassError):
            resolve_aliases(".fnn")
        with pytest.raises(UnknownSelectorClassError):
            resolve_aliases(".zzz-bogus")

    def test_sitting_duck_vocabulary_passes_through(self):
        # Native sitting_duck classes and kind/super-type aliases are valid.
        for sel in (".definition_function", ".DEFINITION", ".typedef",
                    ".operator", ".pattern", ".syntax", ".transform",
                    ".literal_atomic", ".name_scoped"):
            assert resolve_aliases(sel)  # must not raise

    def test_unknown_class_nested_in_pseudo_args_does_not_raise(self):
        # Inside pseudo-class parens we can't reliably distinguish selector
        # classes from argument text — leave those for the engine.
        resolve_aliases(".fn:has(.definition_function:match('foo.bar'))")

    def test_error_message_names_the_class(self):
        with pytest.raises(UnknownSelectorClassError, match=r"\.self"):
            resolve_aliases(".self")


class TestNumericArgValidation:
    """LOW SQL-arg hardening (issue #10): :line/:lines/:long/:complex args
    must be validated as integers before they reach the WHERE clause."""

    def test_line_rejects_boolean_injection(self):
        with pytest.raises(SelectorArgError):
            split_post_filters(".fn:line(5 OR 1=1)")

    def test_lines_rejects_non_integer_args(self):
        with pytest.raises(SelectorArgError):
            split_post_filters(".fn:lines(1,2 OR 1=1)")

    def test_long_and_complex_reject_non_integers(self):
        with pytest.raises(SelectorArgError):
            split_post_filters(".fn:long(abc)")
        with pytest.raises(SelectorArgError):
            split_post_filters(".fn:complex(1;DROP TABLE x)")

    def test_argless_numeric_pseudo_raises(self):
        # Previously `.fn:line` rendered malformed SQL:
        # `start_line <=  AND end_line >= `.
        with pytest.raises(SelectorArgError):
            split_post_filters(".fn:line")

    def test_lines_requires_two_args(self):
        with pytest.raises(SelectorArgError):
            split_post_filters(".fn:lines(3)")

    def test_line_positive(self):
        structural, conds = split_post_filters(".fn:line(5)")
        assert structural == ".fn"
        assert conds == ["start_line <= 5 AND end_line >= 5"]

    def test_lines_positive(self):
        structural, conds = split_post_filters(".fn:lines(3, 7)")
        assert structural == ".fn"
        assert conds == ["start_line >= 3 AND end_line <= 7"]

    def test_contains_escapes_like_wildcards(self):
        # `_`/`%` in a :contains arg must match literally, not as wildcards.
        _, conds = split_post_filters(".fn:contains(a_b)")
        assert len(conds) == 1
        assert "a\\_b" in conds[0]
        assert "ESCAPE" in conds[0]


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


class TestAliasDriftEndToEnd:
    """Issue #10 end-to-end: drifted aliases against the real engine."""

    @pytest.fixture
    def plucker(self, tmp_path):
        from pluckit import Plucker

        (tmp_path / "m.py").write_text(
            "import os\n"
            "def foo():\n"
            "    ok = True\n"
            "    nothing = None\n"
            "    return [i for i in range(3)]\n"
        )
        return Plucker(code="*.py", repo=str(tmp_path))

    def test_module_matches_module_definitions_not_every_block(self, plucker):
        types = set(plucker.find(".module").attr("type"))
        assert types == {"module"}

    def test_bool_and_null_match_atomic_literals(self, plucker):
        assert "True" in set(plucker.find(".bool").names())
        assert "None" in set(plucker.find(".null").names())

    def test_comprehension_matches(self, plucker):
        assert plucker.find(".comp").count() == 1

    def test_def_matches_only_functions(self, plucker):
        # `.def` ≡ `.fn` per docs — not every definition in the file.
        assert set(plucker.find(".def").names()) == {"foo"}

    def test_line_filters_to_spanning_nodes(self, plucker):
        # positive control: a validated integer arg still works end-to-end
        assert "foo" in set(plucker.find(".fn:line(3)").names())

    def test_line_injection_raises_before_sql(self, plucker):
        with pytest.raises(SelectorArgError):
            plucker.find(".fn:line(1 OR 1=1)")

    def test_unknown_class_raises_via_find(self, plucker):
        with pytest.raises(UnknownSelectorClassError):
            plucker.find(".fnn")
