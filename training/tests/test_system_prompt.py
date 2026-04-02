"""Tests for training/system_prompt.py — system prompt generator from api.yaml."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from training.spec import load_spec
from training.system_prompt import generate_system_prompt, write_system_prompt


SPEC_PATH = Path(__file__).parent.parent.parent / "reference" / "api.yaml"


@pytest.fixture(scope="module")
def spec():
    return load_spec(SPEC_PATH)


@pytest.fixture(scope="module")
def prompt(spec):
    return generate_system_prompt(spec)


# ---------------------------------------------------------------------------
# Basic structure
# ---------------------------------------------------------------------------

class TestBasicStructure:
    def test_returns_non_empty_string(self, prompt):
        assert isinstance(prompt, str)
        assert len(prompt) > 100

    def test_contains_jupyter_or_notebook_or_cell(self, prompt):
        lower = prompt.lower()
        assert "jupyter" in lower or "notebook" in lower or "cell" in lower

    def test_contains_import_restriction(self, prompt):
        assert "import" in prompt


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

class TestEntryPoints:
    def test_contains_select_entry_point(self, prompt):
        assert "select(" in prompt

    def test_contains_source_entry_point(self, prompt):
        assert "source(" in prompt


# ---------------------------------------------------------------------------
# Operation coverage
# ---------------------------------------------------------------------------

class TestQueryOps:
    def test_contains_find(self, prompt):
        assert ".find(" in prompt

    def test_contains_filter(self, prompt):
        assert ".filter(" in prompt


class TestMutationOps:
    def test_contains_addParam(self, prompt):
        assert ".addParam(" in prompt

    def test_contains_rename(self, prompt):
        assert ".rename(" in prompt

    def test_contains_replaceWith(self, prompt):
        assert ".replaceWith(" in prompt


class TestTerminalOps:
    def test_contains_text(self, prompt):
        assert ".text()" in prompt

    def test_contains_count(self, prompt):
        assert ".count()" in prompt

    def test_contains_names(self, prompt):
        assert ".names()" in prompt


class TestDelegateOps:
    def test_contains_test(self, prompt):
        assert ".test(" in prompt

    def test_contains_save(self, prompt):
        assert ".save(" in prompt

    def test_contains_black(self, prompt):
        assert ".black()" in prompt


class TestHistoryOps:
    def test_contains_history(self, prompt):
        assert ".history()" in prompt

    def test_contains_at(self, prompt):
        assert ".at(" in prompt

    def test_contains_diff(self, prompt):
        assert ".diff(" in prompt


class TestRelationshipOps:
    def test_contains_callers(self, prompt):
        assert ".callers()" in prompt

    def test_contains_callees(self, prompt):
        assert ".callees()" in prompt


# ---------------------------------------------------------------------------
# Operation count
# ---------------------------------------------------------------------------

class TestOperationCount:
    def test_lists_more_than_20_operations(self, prompt):
        # Count occurrences of "." followed by a method name "(" pattern
        import re
        ops = re.findall(r'\.\w+\(', prompt)
        unique_ops = set(ops)
        assert len(unique_ops) > 20, (
            f"Expected > 20 unique operations, found {len(unique_ops)}: {unique_ops}"
        )


# ---------------------------------------------------------------------------
# write_system_prompt
# ---------------------------------------------------------------------------

class TestWriteSystemPrompt:
    def test_write_creates_file(self, spec):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = str(Path(tmpdir) / "system_prompt.txt")
            write_system_prompt(spec, output_path)
            assert Path(output_path).exists()

    def test_write_file_matches_generate(self, spec):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = str(Path(tmpdir) / "system_prompt.txt")
            write_system_prompt(spec, output_path)
            content = Path(output_path).read_text(encoding="utf-8")
            assert content == generate_system_prompt(spec)
