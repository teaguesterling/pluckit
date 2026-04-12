"""Tests for chain CLI argv parsing."""
from __future__ import annotations

import textwrap

import pytest

from pluckit.chain import Chain, ChainStep
from pluckit.cli import main


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


@pytest.fixture
def cli_repo(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text(textwrap.dedent("""\
        def greet(name):
            return f"hello {name}"

        def farewell(name):
            return f"goodbye {name}"

        def _private():
            pass
    """))
    return tmp_path


class TestCliChainExecution:
    def test_find_count(self, cli_repo, capsys):
        result = main([str(cli_repo / "src/*.py"), "find", ".fn", "count"])
        assert result == 0
        out = capsys.readouterr().out.strip()
        assert out.isdigit()
        assert int(out) >= 3

    def test_find_names(self, cli_repo, capsys):
        result = main([str(cli_repo / "src/*.py"), "find", ".fn:exported", "names"])
        assert result == 0
        out = capsys.readouterr().out
        assert "greet" in out
        assert "_private" not in out

    def test_mutation(self, cli_repo):
        result = main([str(cli_repo / "src/*.py"), "find", ".fn#greet", "rename", "salute"])
        assert result == 0
        assert "def salute" in (cli_repo / "src" / "app.py").read_text()

    def test_group_separator(self, cli_repo):
        result = main([
            str(cli_repo / "src/*.py"),
            "find", ".fn#greet", "rename", "salute",
            "--",
            "find", ".fn#farewell", "rename", "adieu",
        ])
        assert result == 0
        content = (cli_repo / "src" / "app.py").read_text()
        assert "def salute" in content
        assert "def adieu" in content

    def test_to_json_output(self, cli_repo, capsys):
        import json
        result = main(["--to-json", str(cli_repo / "src/*.py"), "find", ".fn", "count"])
        assert result == 0
        d = json.loads(capsys.readouterr().out)
        assert "source" in d
        assert "steps" in d

    def test_json_input(self, cli_repo, capsys):
        import json
        chain_json = json.dumps({
            "source": [str(cli_repo / "src/*.py")],
            "steps": [{"op": "find", "args": [".fn"]}, {"op": "count"}],
        })
        result = main(["--json", chain_json])
        assert result == 0
        out = capsys.readouterr().out.strip()
        assert out.isdigit()

    def test_init_still_works(self, capsys):
        result = main(["init"])
        assert result == 0

    def test_version_still_works(self, capsys):
        result = main(["--version"])
        assert result == 0
        assert "pluckit" in capsys.readouterr().out

    def test_help_flag(self, capsys):
        result = main(["--help"])
        assert result == 0
        assert "pluckit" in capsys.readouterr().out

    def test_no_args_shows_help(self, capsys):
        result = main([])
        assert result == 0
        assert "pluckit" in capsys.readouterr().out
