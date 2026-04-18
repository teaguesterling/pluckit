"""Tests for @file argument resolution in chain evaluation."""
from __future__ import annotations

import pytest

from pluckit.chain import ChainStep, _resolve_file_args


class TestResolveFileArgs:
    """Unit tests for the _resolve_file_args helper."""

    def test_plain_args_pass_through(self):
        assert _resolve_file_args([".fn", "foo", "bar"]) == [".fn", "foo", "bar"]

    def test_empty_args(self):
        assert _resolve_file_args([]) == []

    def test_at_file_reads_content(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("def hello(): pass\n")
        result = _resolve_file_args([f"@{f}"])
        assert result == ["def hello(): pass\n"]

    def test_at_file_mixed_with_plain(self, tmp_path):
        f = tmp_path / "snippet.txt"
        f.write_text("new_name")
        result = _resolve_file_args([".fn", f"@{f}", "extra"])
        assert result == [".fn", "new_name", "extra"]

    def test_double_at_escapes_to_literal(self):
        result = _resolve_file_args(["@@literal"])
        assert result == ["@literal"]

    def test_double_at_does_not_read_file(self, tmp_path):
        f = tmp_path / "literal"
        f.write_text("should not be read")
        result = _resolve_file_args([f"@@{f}"])
        assert result == [f"@{f}"]

    def test_missing_file_raises(self):
        from pluckit.types import PluckerError

        with pytest.raises(PluckerError, match="@file not found"):
            _resolve_file_args(["@/nonexistent/path/to/file.txt"])

    def test_multiline_content(self, tmp_path):
        f = tmp_path / "multi.py"
        f.write_text("def handler():\n    return 42\n")
        result = _resolve_file_args([f"@{f}"])
        assert result == ["def handler():\n    return 42\n"]


class TestChainStepFromDictFileForm:
    """Tests for the {"file": "path"} object form in ChainStep.from_dict."""

    def test_file_object_normalized_to_at_string(self):
        step = ChainStep.from_dict({
            "op": "replaceWith",
            "args": [{"file": "patches/new_handler.py"}],
        })
        assert step.args == ["@patches/new_handler.py"]

    def test_mixed_string_and_file_object(self):
        step = ChainStep.from_dict({
            "op": "insertBefore",
            "args": [".fn#anchor", {"file": "code.py"}],
        })
        assert step.args == [".fn#anchor", "@code.py"]

    def test_plain_string_args_unchanged(self):
        step = ChainStep.from_dict({
            "op": "find",
            "args": [".fn:exported"],
        })
        assert step.args == [".fn:exported"]

    def test_to_dict_preserves_at_prefix(self):
        """@path strings serialize as-is (no content baking)."""
        step = ChainStep(op="replaceWith", args=["@patches/file.py"])
        d = step.to_dict()
        assert d["args"] == ["@patches/file.py"]

    def test_round_trip_file_object(self):
        """from_dict normalizes {"file":...} to @..., to_dict keeps @..."""
        original = {
            "op": "patch",
            "args": [{"file": "refactor.patch"}],
        }
        step = ChainStep.from_dict(original)
        d = step.to_dict()
        assert d == {"op": "patch", "args": ["@refactor.patch"]}
