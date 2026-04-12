"""Tests for chain CLI argv parsing."""
from __future__ import annotations

import pytest

from pluckit.chain import Chain, ChainStep


class TestFromArgv:
    def test_simple_find_count(self):
        chain = Chain.from_argv(["src/**/*.py", "find", ".fn", "count"])
        assert chain.source == ["src/**/*.py"]
        assert len(chain.steps) == 2
        assert chain.steps[0] == ChainStep(op="find", args=[".fn"])
        assert chain.steps[1] == ChainStep(op="count")

    def test_filter_with_kwargs(self):
        chain = Chain.from_argv([
            "src/*.py", "find", ".fn",
            "filter", "--name__startswith=validate_",
            "count",
        ])
        assert chain.steps[1].op == "filter"
        assert chain.steps[1].kwargs == {"name__startswith": "validate_"}

    def test_group_separator_becomes_reset(self):
        chain = Chain.from_argv([
            "src/*.py",
            "find", ".fn#foo", "addParam", "x: int",
            "--",
            "find", ".fn#bar", "remove",
        ])
        # -- becomes a reset step
        ops = [s.op for s in chain.steps]
        assert "reset" in ops

    def test_plugin_flag(self):
        chain = Chain.from_argv([
            "--plugin", "History",
            "src/*.py", "find", ".fn", "history",
        ])
        assert "History" in chain.plugins

    def test_repo_flag(self):
        chain = Chain.from_argv([
            "--repo", "/tmp/myrepo",
            "src/*.py", "find", ".fn", "count",
        ])
        assert chain.repo == "/tmp/myrepo"

    def test_source_shortcut_code(self):
        chain = Chain.from_argv(["-c", "find", ".fn", "count"])
        assert chain.source == ["code"]

    def test_source_shortcut_docs(self):
        chain = Chain.from_argv(["-d", "find", ".fn", "count"])
        assert chain.source == ["docs"]

    def test_source_shortcut_tests(self):
        chain = Chain.from_argv(["-t", "find", ".fn", "count"])
        assert chain.source == ["tests"]

    def test_multi_arg_ops(self):
        chain = Chain.from_argv([
            "src/*.py", "find", ".fn#main",
            "insertBefore", ".ret", "cleanup()",
        ])
        assert chain.steps[1].op == "insertBefore"
        assert chain.steps[1].args == [".ret", "cleanup()"]

    def test_dry_run_flag(self):
        chain = Chain.from_argv([
            "--dry-run", "src/*.py", "find", ".fn", "count",
        ])
        assert chain.dry_run is True

    def test_to_json_flag(self):
        chain = Chain.from_argv([
            "--to-json", "src/*.py", "find", ".fn", "count",
        ])
        assert chain.json_output is True

    def test_json_input_flag(self):
        chain = Chain.from_argv(["--json", '{"source":["x"],"steps":[{"op":"count"}]}'])
        assert chain.json_input is True

    def test_empty_argv_raises(self):
        with pytest.raises(SystemExit):
            Chain.from_argv([])
