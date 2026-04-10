"""Tests for the pluckit CLI entry point."""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from pluckit.cli import _read_query, _normalize_positional_args, main


SAMPLE_CODE = '''\
def top_level_fn(x):
    """Top-level function."""
    return x * 2


class Config:
    def __init__(self, db):
        self.db = db


def main():
    return Config(None)
'''


@pytest.fixture
def cli_repo(tmp_path):
    """Create a temp repo with a sample Python file."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "sample.py").write_text(SAMPLE_CODE)
    return tmp_path


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

class TestReadQuery:
    def test_positional_string(self):
        assert _read_query(".fn#main", None) == ".fn#main"

    def test_strip_whitespace(self):
        assert _read_query("  .fn#main  ", None) == ".fn#main"

    def test_query_file(self, tmp_path):
        qfile = tmp_path / "query.txt"
        qfile.write_text(".class#Config { show: outline; }\n")
        assert _read_query(None, str(qfile)) == ".class#Config { show: outline; }"

    def test_query_file_overrides_positional(self, tmp_path):
        qfile = tmp_path / "query.txt"
        qfile.write_text(".cls")
        # --query-file takes priority over positional
        assert _read_query(".fn", str(qfile)) == ".cls"

    def test_stdin(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO(".fn#main\n"))
        assert _read_query("-", None) == ".fn#main"

    def test_missing_query_raises(self):
        with pytest.raises(SystemExit, match="query is required"):
            _read_query(None, None)


class TestNormalizePositionalArgs:
    def test_no_query_file_no_change(self):
        import argparse
        args = argparse.Namespace(query=".fn", paths=["src/*.py"], query_file=None)
        _normalize_positional_args(args)
        assert args.query == ".fn"
        assert args.paths == ["src/*.py"]

    def test_query_file_shifts_positional(self):
        import argparse
        args = argparse.Namespace(query="src/*.py", paths=[], query_file="q.txt")
        _normalize_positional_args(args)
        assert args.query is None
        assert args.paths == ["src/*.py"]

    def test_query_file_with_multiple_paths(self):
        import argparse
        args = argparse.Namespace(query="a.py", paths=["b.py"], query_file="q.txt")
        _normalize_positional_args(args)
        assert args.query is None
        assert args.paths == ["a.py", "b.py"]


# ---------------------------------------------------------------------------
# End-to-end CLI tests
# ---------------------------------------------------------------------------

class TestCliView:
    def test_positional_query_and_path(self, cli_repo, capsys):
        result = main([
            "view",
            ".fn#top_level_fn",
            str(cli_repo / "src/*.py"),
        ])
        assert result == 0
        captured = capsys.readouterr()
        assert "def top_level_fn(x):" in captured.out
        assert "return x * 2" in captured.out

    def test_signature_mode(self, cli_repo, capsys):
        main([
            "view",
            ".fn#top_level_fn { show: signature; }",
            str(cli_repo / "src/*.py"),
        ])
        captured = capsys.readouterr()
        assert "def top_level_fn(x):" in captured.out
        # Body should not be present
        assert "return x * 2" not in captured.out

    def test_query_from_file(self, cli_repo, tmp_path, capsys):
        qfile = tmp_path / "query.txt"
        qfile.write_text(".cls#Config { show: outline; }")
        main([
            "view",
            "--query-file", str(qfile),
            str(cli_repo / "src/*.py"),
        ])
        captured = capsys.readouterr()
        assert "class Config:" in captured.out
        assert "def __init__" in captured.out

    def test_query_from_stdin(self, cli_repo, capsys, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO(".fn#main"))
        main([
            "view",
            "-",
            str(cli_repo / "src/*.py"),
        ])
        captured = capsys.readouterr()
        assert "def main():" in captured.out

    def test_output_to_file(self, cli_repo, tmp_path):
        out_file = tmp_path / "output.md"
        result = main([
            "view",
            ".fn#top_level_fn",
            str(cli_repo / "src/*.py"),
            "--output", str(out_file),
        ])
        assert result == 0
        assert out_file.exists()
        content = out_file.read_text()
        assert "def top_level_fn(x):" in content

    def test_multiple_paths(self, cli_repo, capsys):
        # Create a second file
        (cli_repo / "src" / "other.py").write_text(
            "def other_fn():\n    pass\n"
        )
        main([
            "view",
            ".fn",
            str(cli_repo / "src/sample.py"),
            str(cli_repo / "src/other.py"),
        ])
        captured = capsys.readouterr()
        assert "top_level_fn" in captured.out
        assert "other_fn" in captured.out

    def test_no_matches_returns_zero(self, cli_repo, capsys):
        result = main([
            "view",
            ".fn#does_not_exist",
            str(cli_repo / "src/*.py"),
        ])
        assert result == 0
        captured = capsys.readouterr()
        # Empty output when no matches
        assert captured.out == ""

    def test_missing_query_fails(self, cli_repo):
        with pytest.raises(SystemExit):
            main(["view"])

    def test_help_flag(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["--help"])
        assert exc.value.code == 0

    def test_version_flag(self, capsys):
        result = main(["--version"])
        assert result == 0
        captured = capsys.readouterr()
        assert "pluckit" in captured.out


class TestCliEdit:
    def test_replace_2arg(self, cli_repo, capsys):
        result = main([
            "edit",
            ".fn#top_level_fn",
            str(cli_repo / "src/sample.py"),
            "--replace", "return x * 2", "return x * 3",
        ])
        assert result == 0
        content = (cli_repo / "src" / "sample.py").read_text()
        assert "return x * 3" in content
        assert "return x * 2" not in content

    def test_rename(self, cli_repo, capsys):
        result = main([
            "edit",
            ".fn#top_level_fn",
            str(cli_repo / "src/sample.py"),
            "--rename", "renamed_fn",
        ])
        assert result == 0
        content = (cli_repo / "src" / "sample.py").read_text()
        assert "def renamed_fn" in content

    def test_add_param(self, cli_repo):
        result = main([
            "edit",
            ".fn#top_level_fn",
            str(cli_repo / "src/sample.py"),
            "--add-param", "debug: bool = False",
        ])
        assert result == 0
        content = (cli_repo / "src" / "sample.py").read_text()
        assert "top_level_fn(x, debug: bool = False)" in content

    def test_add_arg(self, cli_repo):
        # Add a call site to the sample file
        (cli_repo / "src" / "caller.py").write_text(
            "def run():\n    return top_level_fn(5)\n"
        )
        result = main([
            "edit",
            ".call#top_level_fn",
            str(cli_repo / "src/caller.py"),
            "--add-arg", "verbose=True",
        ])
        assert result == 0
        content = (cli_repo / "src" / "caller.py").read_text()
        assert "top_level_fn(5, verbose=True)" in content

    def test_remove_arg(self, cli_repo):
        (cli_repo / "src" / "caller.py").write_text(
            "def run():\n    return fetch(url='x', timeout=30)\n"
        )
        result = main([
            "edit",
            ".call#fetch",
            str(cli_repo / "src/caller.py"),
            "--remove-arg", "timeout",
        ])
        assert result == 0
        content = (cli_repo / "src" / "caller.py").read_text()
        assert "fetch(url='x')" in content
        assert "timeout" not in content

    def test_remove_param(self, cli_repo):
        result = main([
            "edit",
            ".fn#top_level_fn",
            str(cli_repo / "src/sample.py"),
            "--remove-param", "x",
        ])
        assert result == 0
        content = (cli_repo / "src" / "sample.py").read_text()
        assert "def top_level_fn()" in content

    def test_remove(self, cli_repo):
        result = main([
            "edit",
            ".fn#top_level_fn",
            str(cli_repo / "src/sample.py"),
            "--remove",
        ])
        assert result == 0
        content = (cli_repo / "src" / "sample.py").read_text()
        assert "def top_level_fn" not in content
        # Other content preserved
        assert "class Config" in content

    def test_dry_run_does_not_modify(self, cli_repo):
        original = (cli_repo / "src" / "sample.py").read_text()
        result = main([
            "edit",
            ".fn#top_level_fn",
            str(cli_repo / "src/sample.py"),
            "--remove",
            "--dry-run",
        ])
        assert result == 0
        content = (cli_repo / "src" / "sample.py").read_text()
        assert content == original

    def test_no_matches_returns_zero(self, cli_repo):
        result = main([
            "edit",
            ".fn#nonexistent",
            str(cli_repo / "src/sample.py"),
            "--remove",
        ])
        assert result == 0

    def test_requires_mutation_flag(self, cli_repo):
        # argparse exits with 2 when a required mutually-exclusive group is missing
        with pytest.raises(SystemExit):
            main([
                "edit",
                ".fn#top_level_fn",
                str(cli_repo / "src/sample.py"),
            ])

    def test_multiple_paths(self, cli_repo):
        # Create a second file
        (cli_repo / "src" / "other.py").write_text(
            "def top_level_fn(x):\n    return x + 1\n"
        )
        result = main([
            "edit",
            ".fn#top_level_fn",
            str(cli_repo / "src/sample.py"),
            str(cli_repo / "src/other.py"),
            "--rename", "renamed",
        ])
        assert result == 0
        assert "def renamed" in (cli_repo / "src" / "sample.py").read_text()
        assert "def renamed" in (cli_repo / "src" / "other.py").read_text()
