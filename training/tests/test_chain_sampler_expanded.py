"""Tests for expanded chain sampler — error-driven, code-contextual, multi-language."""
import random
from pathlib import Path

import pytest
from training.spec import load_spec
from training.chain_sampler import ChainSampler

SPEC_PATH = Path(__file__).parent.parent.parent / "reference" / "api.yaml"


@pytest.fixture
def sampler():
    spec = load_spec(str(SPEC_PATH))
    return ChainSampler(spec, rng=random.Random(42))


class TestErrorDriven:
    def test_returns_required_fields(self, sampler):
        result = sampler.sample_error_driven()
        assert "chain" in result
        assert "shape" in result
        assert "category" in result
        assert "context" in result
        assert "language" in result

    def test_category_is_error_fix(self, sampler):
        result = sampler.sample_error_driven()
        assert result["category"] == "error_fix"

    def test_context_contains_error_message(self, sampler):
        result = sampler.sample_error_driven()
        assert "Error" in result["context"] or "error" in result["context"] or "panic" in result["context"]

    def test_chain_starts_with_source(self, sampler):
        result = sampler.sample_error_driven()
        assert result["chain"].startswith("source(")

    def test_language_is_valid(self, sampler):
        for _ in range(20):
            result = sampler.sample_error_driven()
            assert result["language"] in ("python", "go", "typescript")


class TestCodeContextual:
    def test_returns_required_fields(self, sampler):
        result = sampler.sample_code_contextual()
        assert "chain" in result
        assert "context" in result
        assert "language" in result

    def test_context_contains_code(self, sampler):
        result = sampler.sample_code_contextual()
        # Should contain actual code
        assert len(result["context"]) > 10

    def test_category_is_code_fix(self, sampler):
        result = sampler.sample_code_contextual()
        assert result["category"] == "code_fix"


class TestMultilang:
    def test_returns_required_fields(self, sampler):
        result = sampler.sample_multilang()
        assert "chain" in result
        assert "shape" in result
        assert "category" in result
        assert "language" in result

    def test_language_variety(self, sampler):
        langs = set()
        for _ in range(50):
            result = sampler.sample_multilang()
            langs.add(result["language"])
        assert len(langs) >= 2  # Should produce at least 2 different languages

    def test_go_chains_use_go_paths(self, sampler):
        for _ in range(50):
            result = sampler.sample_multilang()
            if result["language"] == "go" and "source(" in result["chain"]:
                assert ".go" in result["chain"]
                break


class TestNewOperations:
    def test_addArg_in_chain(self, sampler):
        """Verify addArg can appear in generated chains."""
        found = False
        for _ in range(500):
            result = sampler.sample()
            if "addArg(" in result["chain"]:
                found = True
                break
        assert found, "addArg should appear in generated chains"

    def test_addDecorator_in_chain(self, sampler):
        found = False
        for _ in range(500):
            result = sampler.sample()
            if "addDecorator(" in result["chain"]:
                found = True
                break
        assert found, "addDecorator should appear in generated chains"

    def test_ensureImport_in_chain(self, sampler):
        found = False
        for _ in range(500):
            result = sampler.sample()
            if "ensureImport(" in result["chain"]:
                found = True
                break
        assert found, "ensureImport should appear in generated chains"
