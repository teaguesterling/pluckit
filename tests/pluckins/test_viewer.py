"""Tests for the AstViewer plugin."""
from __future__ import annotations

import warnings

import pytest

from pluckit import AstViewer, Plucker, PluckerError
from pluckit.pluckins.viewer import (
    _default_show,
    _extract_body,
    _extract_signature,
    parse_viewer_query,
)

# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------

class TestParseViewerQuery:
    def test_bare_selector(self):
        rules = parse_viewer_query(".fn#main")
        assert len(rules) == 1
        assert rules[0].selector == ".fn#main"
        assert rules[0].declarations == {}

    def test_empty_declaration_block(self):
        rules = parse_viewer_query(".fn#main { }")
        assert len(rules) == 1
        assert rules[0].selector == ".fn#main"
        assert rules[0].declarations == {}

    def test_single_declaration(self):
        rules = parse_viewer_query(".fn#main { show: body; }")
        assert len(rules) == 1
        assert rules[0].declarations == {"show": "body"}

    def test_no_trailing_semicolon(self):
        rules = parse_viewer_query(".fn#main { show: body }")
        assert rules[0].declarations == {"show": "body"}

    def test_multiple_declarations(self):
        rules = parse_viewer_query(".fn { show: body; format: markdown; }")
        assert rules[0].declarations == {"show": "body", "format": "markdown"}

    def test_multiple_rules(self):
        rules = parse_viewer_query(".fn { show: signature; } #main { show: body; }")
        assert len(rules) == 2
        assert rules[0].selector == ".fn"
        assert rules[0].declarations == {"show": "signature"}
        assert rules[1].selector == "#main"
        assert rules[1].declarations == {"show": "body"}

    def test_attribute_selector_not_confused_by_brace(self):
        rules = parse_viewer_query('.cls[name*="Service"] { show: outline; }')
        assert rules[0].selector == '.cls[name*="Service"]'
        assert rules[0].declarations == {"show": "outline"}

    def test_complex_selector_with_has(self):
        rules = parse_viewer_query(".fn:has(.call#execute):not(:has(.try))")
        assert len(rules) == 1
        assert rules[0].selector == ".fn:has(.call#execute):not(:has(.try))"

    def test_quoted_value(self):
        rules = parse_viewer_query(".fn { show: 'signature'; }")
        assert rules[0].declarations == {"show": "signature"}

    def test_double_quoted_value(self):
        rules = parse_viewer_query('.fn { show: "body"; }')
        assert rules[0].declarations == {"show": "body"}

    def test_unknown_property_warns(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            parse_viewer_query(".fn { trace: callers; }")
            msgs = [str(wi.message) for wi in w]
            assert any("trace" in m and "reserved" in m for m in msgs)

    def test_unknown_property_still_parsed(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            rules = parse_viewer_query(".fn { trace: callers; }")
        # Reserved properties are still parsed into declarations dict
        assert rules[0].declarations.get("trace") == "callers"

    def test_empty_query(self):
        assert parse_viewer_query("") == []

    def test_whitespace_only(self):
        assert parse_viewer_query("   \n\t  ") == []

    def test_trailing_whitespace(self):
        rules = parse_viewer_query(".fn#main   ")
        assert len(rules) == 1
        assert rules[0].selector == ".fn#main"


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

class TestDefaults:
    def test_default_show_for_function(self):
        assert _default_show({"type": "function_definition"}) == "body"

    def test_default_show_for_class(self):
        assert _default_show({"type": "class_definition"}) == "outline"

    def test_default_show_for_module(self):
        assert _default_show({"type": "module"}) == "outline"

    def test_default_show_for_call(self):
        assert _default_show({"type": "call"}) == "body"


class TestExtractors:
    def test_extract_body_single_line(self):
        lines = ["line 1\n", "line 2\n", "line 3\n"]
        assert _extract_body(lines, 2, 2) == "line 2"

    def test_extract_body_range(self):
        lines = ["line 1\n", "line 2\n", "line 3\n", "line 4\n"]
        assert _extract_body(lines, 2, 3) == "line 2\nline 3"

    def test_extract_body_whole_file(self):
        lines = ["a\n", "b\n", "c\n"]
        assert _extract_body(lines, 1, 3) == "a\nb\nc"

    def test_extract_signature_python(self):
        lines = [
            "def foo(x, y):\n",
            "    return x + y\n",
        ]
        sig = _extract_signature(lines, 1, 2, "python")
        assert sig == "def foo(x, y):"

    def test_extract_signature_python_multiline(self):
        lines = [
            "def foo(\n",
            "    x: int,\n",
            "    y: int,\n",
            ") -> int:\n",
            "    return x + y\n",
        ]
        sig = _extract_signature(lines, 1, 5, "python")
        assert "def foo(" in sig
        assert "-> int:" in sig

    def test_extract_signature_javascript(self):
        lines = [
            "function foo(x) {\n",
            "    return x * 2;\n",
            "}\n",
        ]
        sig = _extract_signature(lines, 1, 3, "javascript")
        assert sig == "function foo(x) {"


# ---------------------------------------------------------------------------
# End-to-end rendering tests (use a fixture file)
# ---------------------------------------------------------------------------

SAMPLE_CODE = '''\
def top_level_fn(x):
    """Top-level function."""
    return x * 2


class Config:
    """Config class."""

    def __init__(self, db):
        self.db = db

    def get_user(self, user_id):
        return self.db.fetch(user_id)


def main():
    c = Config(None)
    return c
'''


@pytest.fixture
def viewer_repo(tmp_path):
    """Create a temp repo with a sample Python file."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "sample.py").write_text(SAMPLE_CODE)
    return tmp_path


@pytest.fixture
def pluck(viewer_repo):
    """Plucker with AstViewer loaded."""
    return Plucker(
        code=str(viewer_repo / "src/*.py"),
        plugins=[AstViewer],
    )


class TestRenderBody:
    def test_function_body(self, pluck):
        output = pluck.view(".fn#top_level_fn")
        assert "def top_level_fn(x):" in output
        assert "return x * 2" in output
        assert "```python" in output

    def test_empty_match_returns_empty_string(self, pluck):
        output = pluck.view(".fn#nonexistent")
        assert output == ""

    def test_includes_location_header(self, pluck):
        output = pluck.view(".fn#top_level_fn")
        lines = output.markdown.split("\n")
        assert lines[0].startswith("# ")
        assert "sample.py:" in lines[0]


class TestRenderSignature:
    def test_signature_only(self, pluck):
        output = pluck.view(".fn#top_level_fn { show: signature; }")
        assert "def top_level_fn(x):" in output
        # Should NOT contain the body
        assert "return x * 2" not in output


class TestRenderOutline:
    def test_class_outline(self, pluck):
        output = pluck.view(".cls#Config")
        # Class header
        assert "class Config:" in output
        # Method signatures
        assert "def __init__(self, db):" in output
        assert "def get_user(self, user_id):" in output
        # Body text should NOT be in outline (roughly)
        assert "return self.db.fetch" not in output

    def test_explicit_show_outline(self, pluck):
        output = pluck.view(".cls#Config { show: outline; }")
        assert "class Config:" in output
        assert "def __init__" in output


class TestSignatureTable:
    def test_multi_match_signature_becomes_table(self, pluck):
        # Sample has top_level_fn and main at module level
        output = pluck.view(".fn { show: signature; }")
        # Should be a markdown table
        assert "| File | Lines | Signature |" in output
        assert "|---|---|---|" in output
        # Both functions should appear as rows
        assert "top_level_fn" in output
        assert "main" in output

    def test_signature_table_has_line_range(self, pluck):
        """Each row should show start-end range when the node spans multiple lines."""
        output = pluck.view(".fn { show: signature; }")
        # top_level_fn is 3 lines (def + docstring + return)
        # It should appear as something like "1-3" or similar range
        import re
        # Find the row for top_level_fn and check it has a range
        rows = [line for line in output.markdown.split("\n") if "top_level_fn" in line]
        assert rows, "top_level_fn row not found"
        # At least one row should contain a range like N-M
        assert any(re.search(r"\| \d+-\d+ \|", r) for r in rows), \
            f"Expected line range in table rows: {rows}"

    def test_single_match_signature_stays_code_block(self, pluck):
        output = pluck.view(".fn#top_level_fn { show: signature; }")
        # Should NOT be a table
        assert "| File |" not in output
        # Should be a code fence
        assert "```python" in output
        assert "def top_level_fn(x):" in output

    def test_table_cell_escapes_pipes(self):
        from pluckit.pluckins.viewer import _escape_table_cell
        assert _escape_table_cell("str | None") == "str \\| None"

    def test_table_cell_flattens_multiline(self):
        from pluckit.pluckins.viewer import _escape_table_cell
        assert _escape_table_cell("line 1\n    line 2") == "line 1 line 2"


class TestNumericShow:
    def test_show_n_lines(self, pluck):
        # Get first 1 line of top_level_fn
        output = pluck.view(".fn#top_level_fn { show: 1; }")
        assert "def top_level_fn(x):" in output
        # Body should be truncated
        assert "return x * 2" not in output
        # Should have truncation marker
        assert "..." in output

    def test_show_many_lines(self, pluck):
        output = pluck.view(".fn#top_level_fn { show: 10; }")
        # With 10 lines, the whole body (which is short) should be there
        assert "def top_level_fn(x):" in output
        assert "return x * 2" in output


class TestNativeSignature:
    def test_synthesize_function_signature(self):
        from pluckit.pluckins.viewer import _synthesize_signature
        node = {
            "type": "function_definition",
            "name": "foo",
            "language": "python",
            "signature_type": "int",
            "parameters": [
                {"name": "x", "type": "int"},
                {"name": "y", "type": "int"},
            ],
            "modifiers": [],
        }
        sig = _synthesize_signature(node)
        assert sig == "def foo(x: int, y: int) -> int:"

    def test_synthesize_class_signature(self):
        from pluckit.pluckins.viewer import _synthesize_signature
        node = {
            "type": "class_definition",
            "name": "Foo",
            "language": "python",
        }
        sig = _synthesize_signature(node)
        assert sig == "class Foo:"

    def test_synthesize_returns_none_when_no_params(self):
        from pluckit.pluckins.viewer import _synthesize_signature
        node = {
            "type": "function_definition",
            "name": "foo",
            "language": "python",
            "parameters": None,
        }
        assert _synthesize_signature(node) is None

    def test_synthesize_go_function(self):
        from pluckit.pluckins.viewer import _synthesize_signature
        node = {
            "type": "function_declaration",
            "name": "Foo",
            "language": "go",
            "signature_type": "error",
            "parameters": [{"name": "ctx", "type": "context.Context"}],
        }
        sig = _synthesize_signature(node)
        assert "func Foo(ctx: context.Context) error {" in sig


class TestMultipleRules:
    def test_multiple_rules_rendered(self, pluck):
        query = ".fn#top_level_fn { show: signature; } .fn#main { show: body; }"
        output = pluck.view(query)
        assert "def top_level_fn(x):" in output
        assert "def main():" in output
        # main should have its body
        assert "c = Config(None)" in output

    def test_rules_separated_by_blank_lines(self, pluck):
        query = ".fn#top_level_fn { show: signature; } .fn#main { show: signature; }"
        output = pluck.view(query)
        # Two rendered blocks separated by blank line
        assert "\n\n#" in output


class TestPluckerIntegration:
    def test_view_method_available(self, pluck):
        assert hasattr(pluck, "view")
        assert callable(pluck.view)

    def test_view_without_plugin_raises(self, viewer_repo):
        pluck = Plucker(code=str(viewer_repo / "src/*.py"))  # no AstViewer
        with pytest.raises(PluckerError, match="AstViewer"):
            pluck.view(".fn#top_level_fn")

    def test_unsupported_format_raises(self, pluck):
        with pytest.raises(PluckerError, match="format"):
            pluck.view(".fn#top_level_fn", format="pandoc")


# ---------------------------------------------------------------------------
# View result type — structured API around the rendered output
# ---------------------------------------------------------------------------

class TestViewReturnType:
    """The view() methods now return a View object, not a bare string."""

    def test_view_returns_View_instance(self, pluck):
        from pluckit import View
        result = pluck.view(".fn#top_level_fn")
        assert isinstance(result, View)

    def test_str_yields_markdown(self, pluck):
        result = pluck.view(".fn#top_level_fn")
        assert "def top_level_fn(x):" in str(result)
        assert "```python" in str(result)

    def test_markdown_property_matches_str(self, pluck):
        result = pluck.view(".fn#top_level_fn")
        assert result.markdown == str(result)

    def test_contains_checks_markdown(self, pluck):
        result = pluck.view(".fn#top_level_fn")
        assert "def top_level_fn(x):" in result
        assert "nonexistent_function" not in result

    def test_equality_with_string_compat(self, pluck):
        """A View compares equal to a string matching its markdown —
        backward-compat for v0.1 tests that did `output == ""` checks."""
        empty = pluck.view(".fn#nonexistent")
        assert empty == ""
        assert not empty  # __bool__ false

    def test_len_returns_block_count(self, pluck):
        result = pluck.view(".fn#top_level_fn")
        assert len(result) == 1

    def test_iterable_yields_ViewBlocks(self, pluck):
        from pluckit import ViewBlock
        result = pluck.view(".fn#top_level_fn")
        blocks = list(result)
        assert len(blocks) == 1
        assert isinstance(blocks[0], ViewBlock)

    def test_block_metadata_populated(self, pluck):
        result = pluck.view(".fn#top_level_fn")
        block = result[0]
        assert block.name == "top_level_fn"
        assert block.show == "body"
        assert block.language == "python"
        assert block.start_line is not None
        assert block.end_line is not None
        assert block.file_path is not None
        assert block.node_type == "function_definition"
        assert not block.is_aggregate

    def test_files_property(self, pluck):
        result = pluck.view(".fn")
        # With default "body" show, non-aggregate — each block has a file_path
        assert len(result.files) >= 1
        assert all(f.endswith(".py") for f in result.files)

    def test_signature_table_is_aggregate_block(self, pluck):
        """Multi-match `show: signature` becomes ONE aggregate block — not
        N separate blocks."""
        result = pluck.view(".fn { show: signature; }")
        assert len(result) == 1
        block = result[0]
        assert block.is_aggregate
        assert block.file_path is None
        assert block.start_line is None
        assert block.show == "signature-table"
        assert "| File | Lines | Signature |" in block.markdown

    def test_aggregate_blocks_not_in_files(self, pluck):
        """An aggregate-only view should have an empty .files list — the
        signature table isn't tied to a single file."""
        result = pluck.view(".fn { show: signature; }")
        assert result.files == []

    def test_multi_rule_produces_multiple_blocks(self, pluck):
        query = ".fn#top_level_fn { show: signature; } .fn#main { show: body; }"
        result = pluck.view(query)
        # One block per rule (both single-match, so no table collapse)
        assert len(result) == 2
        names = [b.name for b in result]
        assert "top_level_fn" in names
        assert "main" in names

    def test_slice_returns_list_of_blocks(self, pluck):
        query = ".fn#top_level_fn { show: signature; } .fn#main { show: body; }"
        result = pluck.view(query)
        first_only = result[:1]
        assert isinstance(first_only, list)
        assert len(first_only) == 1

    def test_to_dict_is_json_serializable(self, pluck):
        import json
        result = pluck.view(".fn#top_level_fn")
        d = result.to_dict()
        # Round-trip through JSON
        round_tripped = json.loads(json.dumps(d))
        assert round_tripped["query"] == ".fn#top_level_fn"
        assert round_tripped["format"] == "markdown"
        assert len(round_tripped["blocks"]) == 1
        assert round_tripped["blocks"][0]["name"] == "top_level_fn"

    def test_repr_summarizes_shape(self, pluck):
        result = pluck.view(".fn#top_level_fn")
        r = repr(result)
        assert "View" in r
        assert "1 block" in r

    def test_empty_view_is_falsy_and_has_empty_markdown(self, pluck):
        empty = pluck.view(".fn#does_not_exist")
        assert not empty
        assert len(empty) == 0
        assert empty.markdown == ""
        assert empty.files == []
        assert list(empty) == []


# ---------------------------------------------------------------------------
# View.relation and View.tabular
# ---------------------------------------------------------------------------

class TestViewRelation:
    def test_relation_has_columns(self, pluck):
        v = pluck.view(".fn")
        rel = v.relation
        assert "file_path" in rel.columns
        assert "name" in rel.columns
        assert "start_line" in rel.columns

    def test_relation_has_rows(self, pluck):
        v = pluck.view(".fn")
        rel = v.relation
        rows = rel.fetchall()
        assert len(rows) >= 1

    def test_relation_excludes_aggregates(self, pluck):
        v = pluck.view(".fn { show: signature; }")
        rel = v.relation
        rows = rel.fetchall()
        # Aggregate blocks (signature tables) should be excluded
        # Each row should have a non-null file_path
        for row in rows:
            assert row[0] is not None  # file_path

    def test_empty_relation(self, pluck):
        v = pluck.view(".fn#nonexistent")
        rel = v.relation
        rows = rel.fetchall()
        assert rows == []
        assert "file_path" in rel.columns

    def test_tabular_no_connection_needed(self):
        from pluckit.pluckins.viewer import View, ViewBlock
        blocks = [
            ViewBlock(markdown="# test", rule=None, show="source",
                     file_path="test.py", start_line=1, end_line=5,
                     name="test_fn", node_type="function", language="python"),
        ]
        v = View(blocks)
        cols, rows = v.tabular
        assert cols[0] == "file_path"
        assert len(rows) == 1
        assert rows[0][0] == "test.py"

    def test_relation_without_db_raises(self):
        from pluckit.pluckins.viewer import View, ViewBlock
        blocks = [
            ViewBlock(markdown="# test", rule=None, show="source",
                     file_path="test.py", start_line=1, end_line=5,
                     name="test_fn", node_type="function", language="python"),
        ]
        v = View(blocks)  # no db
        with pytest.raises(PluckerError, match="no database connection"):
            _ = v.relation  # noqa: B018 — property access IS the side effect


# ---------------------------------------------------------------------------
# View serialization round-trips
# ---------------------------------------------------------------------------

class TestViewSerialization:
    def test_from_dict_round_trip(self, pluck):
        from pluckit.pluckins.viewer import View
        view = pluck.view(".fn#top_level_fn")
        d = view.to_dict()
        restored = View.from_dict(d)
        assert len(restored) == len(view)
        assert restored.markdown == view.markdown
        assert restored[0].name == view[0].name

    def test_to_json_round_trip(self, pluck):
        import json

        from pluckit.pluckins.viewer import View
        view = pluck.view(".fn#top_level_fn")
        j = view.to_json()
        data = json.loads(j)
        assert "blocks" in data
        restored = View.from_json(j)
        assert restored.markdown == view.markdown

    def test_from_dict_empty_view(self):
        from pluckit.pluckins.viewer import View
        d = {"query": "", "format": "markdown", "blocks": []}
        v = View.from_dict(d)
        assert len(v) == 0
        assert not v

    def test_from_dict_with_blocks(self):
        from pluckit.pluckins.viewer import View
        d = {
            "query": ".fn",
            "format": "markdown",
            "blocks": [{
                "markdown": "```python\ndef foo(): pass\n```",
                "show": "body",
                "file_path": "test.py",
                "start_line": 1,
                "end_line": 1,
                "name": "foo",
                "node_type": "function_definition",
                "language": "python",
                "is_aggregate": False,
            }],
        }
        v = View.from_dict(d)
        assert len(v) == 1
        assert v[0].name == "foo"
        assert "def foo" in v.markdown
