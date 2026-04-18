"""Tests for --diff flag and --dry-run implementation."""
from __future__ import annotations

import textwrap

import pytest

from pluckit.chain import Chain, ChainStep


@pytest.fixture
def sample_file(tmp_path):
    """Create a simple Python file to test mutations against."""
    f = tmp_path / "sample.py"
    f.write_text(textwrap.dedent("""\
        def hello():
            return 42

        def goodbye():
            return 0
    """))
    return f


class TestDiffFlagParsing:
    """Test that --diff is parsed and serialized correctly."""

    def test_from_argv(self):
        chain = Chain.from_argv(["src/*.py", "find", ".fn", "--diff"])
        assert chain.diff is True

    def test_from_argv_default_false(self):
        chain = Chain.from_argv(["src/*.py", "find", ".fn"])
        assert chain.diff is False

    def test_to_argv_includes_diff(self):
        chain = Chain(
            source=["src/*.py"],
            steps=[ChainStep(op="find", args=[".fn"])],
            diff=True,
        )
        argv = chain.to_argv()
        assert "--diff" in argv

    def test_to_argv_omits_diff_when_false(self):
        chain = Chain(
            source=["src/*.py"],
            steps=[ChainStep(op="find", args=[".fn"])],
        )
        argv = chain.to_argv()
        assert "--diff" not in argv

    def test_to_dict_includes_diff(self):
        chain = Chain(
            source=["src/*.py"],
            steps=[ChainStep(op="find", args=[".fn"])],
            diff=True,
        )
        d = chain.to_dict()
        assert d["diff"] is True

    def test_to_dict_omits_diff_when_false(self):
        chain = Chain(
            source=["src/*.py"],
            steps=[ChainStep(op="find", args=[".fn"])],
        )
        d = chain.to_dict()
        assert "diff" not in d

    def test_from_dict_with_diff(self):
        chain = Chain.from_dict({
            "source": ["src/*.py"],
            "steps": [{"op": "find", "args": [".fn"]}],
            "diff": True,
        })
        assert chain.diff is True

    def test_from_dict_default_false(self):
        chain = Chain.from_dict({
            "source": ["src/*.py"],
            "steps": [{"op": "find", "args": [".fn"]}],
        })
        assert chain.diff is False

    def test_json_round_trip(self):
        chain = Chain(
            source=["src/*.py"],
            steps=[ChainStep(op="find", args=[".fn"])],
            diff=True,
        )
        restored = Chain.from_json(chain.to_json())
        assert restored.diff is True


class TestDiffOutput:
    """Test --diff produces unified diff output without modifying files."""

    def test_rename_produces_diff(self, sample_file):
        chain = Chain(
            source=[str(sample_file)],
            steps=[
                ChainStep(op="find", args=[".fn#hello"]),
                ChainStep(op="rename", args=["greet"]),
            ],
            diff=True,
        )
        result = chain.evaluate()
        assert result["type"] == "diff"
        assert isinstance(result["data"], list)
        assert len(result["data"]) == 1

        diff_text = result["data"][0]
        assert "-def hello():" in diff_text
        assert "+def greet():" in diff_text

        # File should NOT be modified
        assert "def hello():" in sample_file.read_text()

    def test_no_mutation_no_diff(self, sample_file):
        """--diff with no mutation ops produces normal result."""
        chain = Chain(
            source=[str(sample_file)],
            steps=[
                ChainStep(op="find", args=[".fn#hello"]),
                ChainStep(op="count"),
            ],
            diff=True,
        )
        result = chain.evaluate()
        # count is a terminal, not a mutation — no diff behavior
        assert result["type"] == "count"
        assert result["data"] == 1

    def test_diff_has_standard_format(self, sample_file):
        """Diff output uses standard unified diff format."""
        chain = Chain(
            source=[str(sample_file)],
            steps=[
                ChainStep(op="find", args=[".fn#hello"]),
                ChainStep(op="rename", args=["greet"]),
            ],
            diff=True,
        )
        result = chain.evaluate()
        diff_text = result["data"][0]
        assert diff_text.startswith("--- a/")
        assert "\n+++ b/" in diff_text
        assert "\n@@ " in diff_text


class TestDryRun:
    """Test --dry-run prevents file writes."""

    def test_dry_run_no_file_changes(self, sample_file):
        chain = Chain(
            source=[str(sample_file)],
            steps=[
                ChainStep(op="find", args=[".fn#hello"]),
                ChainStep(op="rename", args=["greet"]),
            ],
            dry_run=True,
        )
        result = chain.evaluate()
        assert result["type"] == "mutation"
        assert result["data"]["applied"] is False
        assert result["data"]["dry_run"] is True

        # File should NOT be modified
        assert "def hello():" in sample_file.read_text()

    def test_diff_takes_precedence_over_dry_run(self, sample_file):
        """When both --diff and --dry-run are set, --diff wins."""
        chain = Chain(
            source=[str(sample_file)],
            steps=[
                ChainStep(op="find", args=[".fn#hello"]),
                ChainStep(op="rename", args=["greet"]),
            ],
            diff=True,
            dry_run=True,
        )
        result = chain.evaluate()
        assert result["type"] == "diff"
        assert len(result["data"]) == 1

        # File should NOT be modified
        assert "def hello():" in sample_file.read_text()


class TestDiffRoundTrip:
    """Test generating a diff then applying it with patch."""

    def test_diff_output_is_valid_unified_diff(self, sample_file):
        """The diff output can be parsed by standard tools."""
        diff_chain = Chain(
            source=[str(sample_file)],
            steps=[
                ChainStep(op="find", args=[".fn#hello"]),
                ChainStep(op="rename", args=["greet"]),
            ],
            diff=True,
        )
        diff_result = diff_chain.evaluate()
        diff_text = diff_result["data"][0]

        # Should contain all standard unified diff elements
        lines = diff_text.splitlines()
        assert any(l.startswith("---") for l in lines)
        assert any(l.startswith("+++") for l in lines)
        assert any(l.startswith("@@") for l in lines)
        assert any(l.startswith("-def hello") for l in lines)
        assert any(l.startswith("+def greet") for l in lines)

    def test_patch_with_node_scoped_diff(self, sample_file):
        """Patch works with a diff scoped to the matched node's text."""
        import textwrap

        # Manually craft a node-scoped diff (only covers the function body)
        node_diff = textwrap.dedent("""\
            --- a/sample.py
            +++ b/sample.py
            @@ -1,2 +1,2 @@
            -def hello():
            +def greet():
                 return 42
        """)
        patch_chain = Chain(
            source=[str(sample_file)],
            steps=[
                ChainStep(op="find", args=[".fn#hello"]),
                ChainStep(op="patch", args=[node_diff]),
            ],
        )
        patch_chain.evaluate()

        content = sample_file.read_text()
        assert "def greet():" in content
        assert "def hello():" not in content
        # Other function should be untouched
        assert "def goodbye():" in content
