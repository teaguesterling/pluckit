# tests/test_selection.py
"""Tests for Selection: query chaining, navigation, filter, and terminal ops."""
import pytest


class TestTerminalOps:
    def test_count(self, ctx):
        sel = ctx.source("src/auth.py").find(".function")
        assert sel.count() >= 4

    def test_names(self, ctx):
        sel = ctx.source("src/auth.py").find(".function")
        names = sel.names()
        assert "validate_token" in names
        assert "process_data" in names

    def test_text_returns_source(self, ctx):
        sel = ctx.select(".function#validate_token")
        texts = sel.text()
        assert len(texts) >= 1
        assert "def validate_token" in texts[0]

    def test_attr_name(self, ctx):
        sel = ctx.select(".function#validate_token")
        assert sel.attr("name") == ["validate_token"]

    def test_attr_file(self, ctx):
        sel = ctx.select(".function#validate_token")
        files = sel.attr("file_path")
        assert len(files) == 1
        assert "auth.py" in files[0]

    def test_attr_line(self, ctx):
        sel = ctx.select(".function#validate_token")
        lines = sel.attr("start_line")
        assert len(lines) == 1
        assert isinstance(lines[0], int)

    def test_attr_invalid_raises(self, ctx):
        sel = ctx.select(".function#validate_token")
        with pytest.raises(ValueError, match="Unknown attribute"):
            sel.attr("nonexistent")

    def test_complexity(self, ctx):
        sel = ctx.select(".function#process_data")
        cx = sel.complexity()
        assert len(cx) == 1
        assert cx[0] > 0


class TestQueryChaining:
    def test_find_narrows(self, ctx):
        cls = ctx.select(".class#AuthService")
        methods = cls.find(".function")
        names = methods.names()
        assert "authenticate" in names
        assert "validate_token" not in names

    def test_not_excludes(self, ctx):
        sel = ctx.source("src/auth.py").find(".function")
        initial_count = sel.count()
        public = sel.not_(".function#_internal_helper")
        assert public.count() < initial_count
        assert "_internal_helper" not in public.names()

    def test_unique_deduplicates(self, ctx):
        sel = ctx.source("src/auth.py").find(".function")
        deduped = sel.unique()
        assert deduped.count() == sel.count()


class TestFilter:
    def test_filter_sql(self, ctx):
        sel = ctx.source("src/**/*.py").find(".function")
        filtered = sel.filter_sql("name = 'validate_token'")
        assert filtered.count() == 1
        assert "validate_token" in filtered.names()

    def test_filter_keyword_name(self, ctx):
        sel = ctx.source("src/**/*.py").find(".function")
        filtered = sel.filter(name="validate_token")
        assert filtered.count() == 1

    def test_filter_keyword_name_startswith(self, ctx):
        sel = ctx.source("src/**/*.py").find(".function")
        filtered = sel.filter(name__startswith="validate_")
        names = filtered.names()
        assert "validate_token" in names

    def test_filter_keyword_name_contains(self, ctx):
        sel = ctx.source("src/**/*.py").find(".function")
        filtered = sel.filter(name__contains="data")
        assert "process_data" in filtered.names()

    def test_filter_css_exported(self, ctx):
        sel = ctx.source("src/auth.py").find(".function")
        exported = sel.filter(":exported")
        names = exported.names()
        assert "_internal_helper" not in names
        assert "validate_token" in names

    def test_filter_combined(self, ctx):
        sel = ctx.source("src/**/*.py").find(".function")
        filtered = sel.filter(":exported", name__startswith="validate_")
        names = filtered.names()
        assert "validate_token" in names
        assert "_internal_helper" not in names

    def test_filter_unknown_keyword_raises(self, ctx):
        sel = ctx.source("src/**/*.py").find(".function")
        with pytest.raises(ValueError, match="Unknown filter keyword"):
            sel.filter(bogus="value")


class TestNavigation:
    def test_parent(self, ctx):
        methods = ctx.select(".class#AuthService").find(".function")
        parents = methods.parent()
        assert parents.count() >= 1

    def test_children(self, ctx):
        cls = ctx.select(".class#AuthService")
        children = cls.children()
        assert children.count() >= 1

    def test_siblings(self, ctx):
        fn = ctx.select(".function#validate_token")
        sibs = fn.siblings()
        names = sibs.names()
        assert "process_data" in names

    def test_ancestor(self, ctx):
        rets = ctx.source("src/auth.py").find("return_statement")
        fns = rets.ancestor(".function")
        names = fns.names()
        assert "validate_token" in names

    def test_next(self, ctx):
        fn = ctx.select(".function#validate_token")
        nxt = fn.next()
        assert nxt.count() >= 1

    def test_prev(self, ctx):
        fn = ctx.select(".function#process_data")
        prv = fn.prev()
        assert prv.count() >= 1


class TestAddressing:
    def test_containing(self, ctx):
        sel = ctx.source("src/auth.py").find(".function")
        matches = sel.containing("return None")
        names = matches.names()
        assert "validate_token" in names

    def test_at_line(self, ctx):
        sel = ctx.source("src/auth.py").find(".function")
        # validate_token starts at line 4 in auth.py
        matches = sel.at_line(4)
        assert matches.count() >= 1
        assert "validate_token" in matches.names()

    def test_at_lines(self, ctx):
        sel = ctx.source("src/auth.py").find(".function")
        matches = sel.at_lines(4, 9)
        assert matches.count() >= 1
        assert "validate_token" in matches.names()
