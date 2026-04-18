"""Tests for the Patch mutation — unified diff and raw replacement."""
from __future__ import annotations

import textwrap

import pytest

from pluckit.mutations import Patch, _parse_unified_diff, _apply_hunk


class TestPatchDetection:
    """Test auto-detection of diff vs raw replacement."""

    def test_unified_diff_detected(self):
        content = "--- a/file.py\n+++ b/file.py\n@@ -1,2 +1,2 @@\n foo\n-bar\n+baz\n"
        p = Patch(content)
        assert p._is_diff is True

    def test_diff_git_detected(self):
        content = "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-old\n+new\n"
        p = Patch(content)
        assert p._is_diff is True

    def test_raw_text_not_detected_as_diff(self):
        content = "def hello(): pass"
        p = Patch(content)
        assert p._is_diff is False

    def test_leading_whitespace_before_diff_marker(self):
        content = "  --- a/file.py\n"
        p = Patch(content)
        assert p._is_diff is True


class TestParseDiff:
    """Test unified diff parsing into hunks."""

    def test_single_hunk(self):
        diff = textwrap.dedent("""\
            --- a/file.py
            +++ b/file.py
            @@ -1,3 +1,3 @@
             def hello():
            -    return 42
            +    return 43
        """)
        hunks = _parse_unified_diff(diff)
        assert len(hunks) == 1
        assert hunks[0]["old_start"] == 1
        lines = hunks[0]["lines"]
        assert lines[0] == (" ", "def hello():\n")
        assert lines[1] == ("-", "    return 42\n")
        assert lines[2] == ("+", "    return 43\n")

    def test_multiple_hunks(self):
        diff = textwrap.dedent("""\
            --- a/file.py
            +++ b/file.py
            @@ -1,2 +1,2 @@
            -line1
            +LINE1
             line2
            @@ -5,2 +5,2 @@
             line5
            -line6
            +LINE6
        """)
        hunks = _parse_unified_diff(diff)
        assert len(hunks) == 2
        assert hunks[0]["old_start"] == 1
        assert hunks[1]["old_start"] == 5

    def test_empty_diff_returns_no_hunks(self):
        diff = "--- a/file.py\n+++ b/file.py\n"
        hunks = _parse_unified_diff(diff)
        assert hunks == []


class TestApplyHunk:
    """Test hunk application to line lists."""

    def test_simple_replacement(self):
        old_lines = ["def hello():\n", "    return 42\n"]
        hunk = {
            "old_start": 1,
            "lines": [
                (" ", "def hello():\n"),
                ("-", "    return 42\n"),
                ("+", "    return 43\n"),
            ],
        }
        result = _apply_hunk(old_lines, hunk)
        assert result == ["def hello():\n", "    return 43\n"]

    def test_addition_only(self):
        old_lines = ["line1\n", "line2\n"]
        hunk = {
            "old_start": 1,
            "lines": [
                (" ", "line1\n"),
                ("+", "inserted\n"),
                (" ", "line2\n"),
            ],
        }
        result = _apply_hunk(old_lines, hunk)
        assert result == ["line1\n", "inserted\n", "line2\n"]

    def test_removal_only(self):
        old_lines = ["line1\n", "remove_me\n", "line3\n"]
        hunk = {
            "old_start": 1,
            "lines": [
                (" ", "line1\n"),
                ("-", "remove_me\n"),
                (" ", "line3\n"),
            ],
        }
        result = _apply_hunk(old_lines, hunk)
        assert result == ["line1\n", "line3\n"]

    def test_context_mismatch_raises(self):
        from pluckit.types import PluckerError

        old_lines = ["actual_line\n"]
        hunk = {
            "old_start": 1,
            "lines": [(" ", "expected_line\n")],
        }
        with pytest.raises(PluckerError, match="context mismatch"):
            _apply_hunk(old_lines, hunk)

    def test_removal_mismatch_raises(self):
        from pluckit.types import PluckerError

        old_lines = ["actual\n"]
        hunk = {
            "old_start": 1,
            "lines": [("-", "expected\n")],
        }
        with pytest.raises(PluckerError, match="removal mismatch"):
            _apply_hunk(old_lines, hunk)


class TestPatchCompute:
    """Test the full Patch.compute() method."""

    def test_raw_replacement(self):
        p = Patch("def new(): pass")
        result = p.compute(
            {"name": "old", "type": "function"},
            "def old(): pass\n",
            "def old(): pass\n",
        )
        assert "def new(): pass" in result

    def test_diff_replacement(self):
        diff = textwrap.dedent("""\
            --- a/file.py
            +++ b/file.py
            @@ -1,2 +1,2 @@
             def hello():
            -    return 42
            +    return 43
        """)
        p = Patch(diff)
        old_text = "def hello():\n    return 42\n"
        result = p.compute({}, old_text, old_text)
        assert result == "def hello():\n    return 43\n"

    def test_diff_no_hunks_raises(self):
        from pluckit.types import PluckerError

        diff = "--- a/file.py\n+++ b/file.py\n"
        p = Patch(diff)
        with pytest.raises(PluckerError, match="no hunks"):
            p.compute({}, "def foo(): pass\n", "def foo(): pass\n")

    def test_multi_hunk_diff(self):
        old_text = "line1\nline2\nline3\nline4\nline5\nline6\n"
        diff = textwrap.dedent("""\
            --- a/file.py
            +++ b/file.py
            @@ -1,2 +1,2 @@
            -line1
            +LINE1
             line2
            @@ -5,2 +5,2 @@
             line5
            -line6
            +LINE6
        """)
        p = Patch(diff)
        result = p.compute({}, old_text, old_text)
        assert result == "LINE1\nline2\nline3\nline4\nline5\nLINE6\n"
