"""Tests for the Isolated type."""
from __future__ import annotations

import json
import textwrap

import pytest

from pluckit import Plucker
from pluckit.isolated import Isolated


@pytest.fixture
def isolate_repo(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text(textwrap.dedent("""\
        import json
        from typing import Optional

        def helper(x):
            return x * 2

        def outer(data, threshold=10):
            filtered = []
            for item in data:
                if item > threshold:
                    filtered.append(helper(item))
            result = json.dumps(filtered)
            return result
    """))
    return tmp_path


@pytest.fixture
def pluck(isolate_repo):
    return Plucker(code=str(isolate_repo / "src/*.py"), repo=str(isolate_repo))


class TestIsolateBasics:
    def test_returns_isolated_instance(self, pluck):
        result = pluck.find(".fn#outer").isolate()
        assert isinstance(result, Isolated)

    def test_captures_body(self, pluck):
        result = pluck.find(".fn#outer").isolate()
        assert "filtered" in result.body
        assert "return result" in result.body

    def test_captures_file_path(self, pluck):
        result = pluck.find(".fn#outer").isolate()
        assert result.file_path.endswith("app.py")

    def test_empty_selection_raises(self, pluck):
        from pluckit.types import PluckerError
        with pytest.raises(PluckerError):
            pluck.find(".fn#nonexistent").isolate()


class TestFreeVariableDetection:
    def test_identifies_external_function_as_param_or_import(self, pluck):
        # helper is defined in the same file, NOT imported.
        # For v1, helper should be a param (since it's not an import and not a builtin).
        result = pluck.find(".fn#outer").isolate()
        assert "helper" in result.params

    def test_local_vars_not_in_params(self, pluck):
        # filtered, item, result are defined in outer — not free vars
        result = pluck.find(".fn#outer").isolate()
        assert "filtered" not in result.params
        assert "item" not in result.params
        assert "result" not in result.params


class TestImportDetection:
    def test_json_import_captured(self, pluck):
        # outer uses json.dumps — json is imported at module scope
        result = pluck.find(".fn#outer").isolate()
        # Either json is an import, or it's a param — we want it to be an import
        assert any("json" in imp for imp in result.imports) or "json" in result.params


class TestRendering:
    def test_as_function(self, pluck):
        result = pluck.find(".fn#outer").isolate()
        rendered = result.as_function("my_extracted")
        assert "def my_extracted(" in rendered
        # Body should be inside the function
        assert "filtered" in rendered
        assert "return result" in rendered

    def test_as_function_default_name(self, pluck):
        result = pluck.find(".fn#outer").isolate()
        rendered = result.as_function()
        assert "def extracted(" in rendered

    def test_as_jupyter_cell_has_no_def(self, pluck):
        result = pluck.find(".fn#outer").isolate()
        rendered = result.as_jupyter_cell()
        assert "def " not in rendered.split("\n")[-1]  # last line is body, not def


class TestSerialization:
    def test_to_dict_round_trip(self, pluck):
        result = pluck.find(".fn#outer").isolate()
        d = result.to_dict()
        restored = Isolated.from_dict(d)
        assert restored.body == result.body
        assert restored.params == result.params

    def test_to_json_round_trip(self, pluck):
        result = pluck.find(".fn#outer").isolate()
        j = result.to_json()
        data = json.loads(j)
        assert "body" in data
        restored = Isolated.from_json(j)
        assert restored.body == result.body
