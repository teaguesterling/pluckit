"""Tests for training/validate.py — chain type-checker and filter CLI."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from training.spec import load_spec
from training.validate import ChainValidationResult, validate_chain

SPEC_PATH = Path(__file__).parent.parent.parent / "reference" / "api.yaml"


@pytest.fixture(scope="module")
def spec():
    return load_spec(SPEC_PATH)


# ---------------------------------------------------------------------------
# ChainValidationResult dataclass
# ---------------------------------------------------------------------------

class TestChainValidationResult:
    def test_valid_defaults(self):
        r = ChainValidationResult(valid=True)
        assert r.valid is True
        assert r.error == ""
        assert r.warnings == []
        assert r.output_type == ""

    def test_mutable_warnings_default_is_independent(self):
        r1 = ChainValidationResult(valid=True)
        r2 = ChainValidationResult(valid=True)
        r1.warnings.append("x")
        assert r2.warnings == []

    def test_explicit_fields(self):
        r = ChainValidationResult(valid=False, error="oops", warnings=["w"], output_type="Selection")
        assert r.valid is False
        assert r.error == "oops"
        assert r.warnings == ["w"]
        assert r.output_type == "Selection"


# ---------------------------------------------------------------------------
# Valid chains
# ---------------------------------------------------------------------------

class TestValidChains:
    def test_simple_select(self, spec):
        result = validate_chain("select('.fn:exported')", spec)
        assert result.valid is True
        assert result.output_type == "Selection"

    def test_source_find(self, spec):
        result = validate_chain("source('tests/**/*.py').find('.fn')", spec)
        assert result.valid is True
        assert result.output_type == "Selection"

    def test_select_mutation(self, spec):
        result = validate_chain("select('.fn:exported').addParam('timeout: int = 30')", spec)
        assert result.valid is True
        assert result.output_type == "Selection"

    def test_select_terminal(self, spec):
        result = validate_chain("select('.fn').count()", spec)
        assert result.valid is True
        assert result.output_type == "terminal"

    def test_long_pipeline(self, spec):
        # A pipeline with multiple mutations then a terminal delegate.
        # Note: test() outputs terminal, so save() cannot follow it per spec rules.
        # This pipeline ends with save() after a mutation+delegate sequence.
        chain = "select('.fn:exported').addParam('timeout: int = 30').black().save('feat: add timeout')"
        result = validate_chain(chain, spec)
        assert result.valid is True

    def test_mutation_then_mutation(self, spec):
        result = validate_chain("select('.fn:exported').rename('new_name').addParam('x: int')", spec)
        assert result.valid is True
        assert result.output_type == "Selection"

    def test_history_chain(self, spec):
        # select → history() → at() → Selection
        result = validate_chain("select('.fn#validate_token').history().at('last_green_build')", spec)
        assert result.valid is True
        assert result.output_type == "Selection"

    def test_select_filter_names(self, spec):
        result = validate_chain("select('.fn').filter(fn: fn.complexity() > 10).names()", spec)
        assert result.valid is True
        assert result.output_type == "terminal"


# ---------------------------------------------------------------------------
# Invalid chains
# ---------------------------------------------------------------------------

class TestInvalidChains:
    def test_empty_chain(self, spec):
        result = validate_chain("", spec)
        assert result.valid is False
        assert result.error != ""

    def test_no_entry_point(self, spec):
        # Starts with a non-entry op
        result = validate_chain("filter(fn: True)", spec)
        assert result.valid is False

    def test_terminal_in_middle(self, spec):
        # count() is terminal; chaining after it is invalid
        result = validate_chain("select('.fn').count().filter(fn: True)", spec)
        assert result.valid is False
        assert "terminal" in result.error.lower()

    def test_unknown_operation(self, spec):
        result = validate_chain("select('.fn').nonexistent_op()", spec)
        assert result.valid is False

    def test_source_followed_by_non_find(self, spec):
        # Source only allows find; filter is not valid on Source
        result = validate_chain("source('src/**/*.py').filter(fn: True)", spec)
        assert result.valid is False

    def test_view_has_no_valid_ops(self, spec):
        # impact() -> View, then trying to chain another op is invalid
        result = validate_chain("select('.fn#handle_request').impact().count()", spec)
        assert result.valid is False


# ---------------------------------------------------------------------------
# Warnings
# ---------------------------------------------------------------------------

class TestWarnings:
    def test_save_without_mutation_warns(self, spec):
        # select → save (no mutation) should warn
        result = validate_chain("select('.fn:exported').save()", spec)
        assert result.valid is True
        assert any("mutation" in w.lower() or "save" in w.lower() for w in result.warnings)

    def test_save_with_mutation_no_warn(self, spec):
        result = validate_chain("select('.fn:exported').addParam('x: int').save()", spec)
        assert result.valid is True
        mutation_warn = [w for w in result.warnings if "mutation" in w.lower() or "save" in w.lower()]
        assert len(mutation_warn) == 0
