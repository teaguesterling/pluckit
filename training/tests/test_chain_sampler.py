"""Tests for training/chain_sampler.py — ChainSampler."""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
from training.spec import load_spec
from training.chain_sampler import ChainSampler

SPEC_PATH = Path(__file__).parent.parent.parent / "reference" / "api.yaml"
VALID_CATEGORIES = {"query", "mutation", "terminal", "delegate", "pipeline"}


@pytest.fixture(scope="module")
def spec():
    return load_spec(SPEC_PATH)


@pytest.fixture
def sampler(spec):
    return ChainSampler(spec, rng=random.Random(42))


# ---------------------------------------------------------------------------
# sample() basic contract
# ---------------------------------------------------------------------------

class TestSampleBasic:
    def test_returns_dict_with_required_keys(self, sampler):
        result = sampler.sample()
        assert isinstance(result, dict)
        assert "chain" in result
        assert "shape" in result
        assert "category" in result

    def test_chain_starts_with_select_or_source(self, sampler):
        for _ in range(30):
            result = sampler.sample()
            chain = result["chain"]
            assert chain.startswith("select(") or chain.startswith("source("), (
                f"Chain does not start with select( or source(: {chain!r}"
            )

    def test_source_chains_must_have_find(self, sampler):
        """source() must be followed by .find()."""
        rng = random.Random(0)
        s = ChainSampler(spec=sampler._spec, rng=rng)
        found_source = False
        for _ in range(200):
            result = s.sample()
            chain = result["chain"]
            if chain.startswith("source("):
                found_source = True
                assert ".find(" in chain, (
                    f"source() chain missing .find(): {chain!r}"
                )
        # We should encounter at least one source chain in 200 samples
        assert found_source, "Never generated a source() chain in 200 samples"

    def test_chain_is_string(self, sampler):
        result = sampler.sample()
        assert isinstance(result["chain"], str)

    def test_shape_is_string(self, sampler):
        result = sampler.sample()
        assert isinstance(result["shape"], str)

    def test_category_is_valid(self, sampler):
        result = sampler.sample()
        assert result["category"] in VALID_CATEGORIES


# ---------------------------------------------------------------------------
# shape contract
# ---------------------------------------------------------------------------

class TestShape:
    def test_shape_starts_with_select_or_source(self, sampler):
        for _ in range(30):
            result = sampler.sample()
            shape = result["shape"]
            assert shape.startswith("select") or shape.startswith("source"), (
                f"Shape does not start with select/source: {shape!r}"
            )

    def test_shape_is_dot_separated_names(self, sampler):
        for _ in range(30):
            result = sampler.sample()
            shape = result["shape"]
            parts = shape.split(".")
            for part in parts:
                assert part.isidentifier(), (
                    f"Shape segment {part!r} is not a valid identifier in {shape!r}"
                )

    def test_shape_matches_chain_operations(self, sampler):
        """Shape segments should correspond to operation names in the chain."""
        from training.chain_parser import parse_chain
        for _ in range(30):
            result = sampler.sample()
            ops = parse_chain(result["chain"])
            expected_shape = ".".join(op.name for op in ops)
            assert result["shape"] == expected_shape, (
                f"Shape mismatch: {result['shape']!r} != {expected_shape!r}"
            )


# ---------------------------------------------------------------------------
# length distribution
# ---------------------------------------------------------------------------

class TestLengthDistribution:
    def test_average_length_in_range(self, spec):
        rng = random.Random(1)
        sampler = ChainSampler(spec, rng=rng)
        lengths = []
        for _ in range(500):
            result = sampler.sample()
            # Count dots in shape (number of ops minus entry)
            n_ops = len(result["shape"].split("."))
            lengths.append(n_ops)
        avg = sum(lengths) / len(lengths)
        assert 2.0 <= avg <= 5.0, f"Average chain length {avg:.2f} out of expected range [2, 5]"

    def test_length_1_chains_exist(self, spec):
        rng = random.Random(2)
        sampler = ChainSampler(spec, rng=rng)
        found_single = False
        for _ in range(500):
            result = sampler.sample()
            if len(result["shape"].split(".")) == 1:
                found_single = True
                break
        assert found_single, "Never generated a length-1 chain in 500 samples"

    def test_length_exceeds_one(self, spec):
        rng = random.Random(3)
        sampler = ChainSampler(spec, rng=rng)
        found_multi = False
        for _ in range(50):
            result = sampler.sample()
            if len(result["shape"].split(".")) > 1:
                found_multi = True
                break
        assert found_multi, "Never generated a chain longer than 1 in 50 samples"


# ---------------------------------------------------------------------------
# category diversity
# ---------------------------------------------------------------------------

class TestCategoryDiversity:
    def test_produces_query_chains(self, spec):
        rng = random.Random(10)
        sampler = ChainSampler(spec, rng=rng)
        categories = {sampler.sample()["category"] for _ in range(200)}
        assert "query" in categories, "Never generated a query chain in 200 samples"

    def test_produces_mutation_chains(self, spec):
        rng = random.Random(11)
        sampler = ChainSampler(spec, rng=rng)
        categories = {sampler.sample()["category"] for _ in range(200)}
        assert "mutation" in categories, "Never generated a mutation chain in 200 samples"

    def test_produces_terminal_chains(self, spec):
        rng = random.Random(12)
        sampler = ChainSampler(spec, rng=rng)
        categories = {sampler.sample()["category"] for _ in range(200)}
        assert "terminal" in categories, "Never generated a terminal chain in 200 samples"

    def test_all_categories_valid(self, spec):
        rng = random.Random(13)
        sampler = ChainSampler(spec, rng=rng)
        for _ in range(200):
            result = sampler.sample()
            assert result["category"] in VALID_CATEGORIES, (
                f"Invalid category: {result['category']!r}"
            )


# ---------------------------------------------------------------------------
# seed_examples()
# ---------------------------------------------------------------------------

class TestSeedExamples:
    def test_returns_list(self, sampler):
        examples = sampler.seed_examples()
        assert isinstance(examples, list)

    def test_non_empty(self, sampler):
        examples = sampler.seed_examples()
        assert len(examples) > 0

    def test_each_example_has_required_keys(self, sampler):
        for ex in sampler.seed_examples():
            assert "chain" in ex, f"Missing 'chain' in {ex}"
            assert "shape" in ex, f"Missing 'shape' in {ex}"
            assert "category" in ex, f"Missing 'category' in {ex}"

    def test_intents_match_api_yaml(self, sampler, spec):
        """seed_examples returns all example chains from api.yaml."""
        # Collect all intents from the spec
        all_spec_chains = []
        for group_examples in spec.example_chains.values():
            for ex in group_examples:
                all_spec_chains.append(ex["chain"])

        seed_chains = {ex["chain"] for ex in sampler.seed_examples()}
        for chain in all_spec_chains:
            assert chain in seed_chains, (
                f"Chain from api.yaml not found in seed_examples: {chain!r}"
            )

    def test_shapes_are_dot_separated(self, sampler):
        for ex in sampler.seed_examples():
            shape = ex["shape"]
            parts = shape.split(".")
            for part in parts:
                assert part.isidentifier(), (
                    f"Shape segment {part!r} not a valid identifier in {shape!r}"
                )

    def test_categories_are_valid(self, sampler):
        for ex in sampler.seed_examples():
            assert ex["category"] in VALID_CATEGORIES, (
                f"Invalid category {ex['category']!r} in seed example"
            )


# ---------------------------------------------------------------------------
# Reproducibility via rng seed
# ---------------------------------------------------------------------------

class TestReproducibility:
    def test_same_seed_same_output(self, spec):
        s1 = ChainSampler(spec, rng=random.Random(99))
        s2 = ChainSampler(spec, rng=random.Random(99))
        results1 = [s1.sample() for _ in range(20)]
        results2 = [s2.sample() for _ in range(20)]
        assert results1 == results2

    def test_different_seeds_different_outputs(self, spec):
        s1 = ChainSampler(spec, rng=random.Random(1))
        s2 = ChainSampler(spec, rng=random.Random(2))
        results1 = [s1.sample() for _ in range(20)]
        results2 = [s2.sample() for _ in range(20)]
        # At least one should differ
        assert results1 != results2


# ---------------------------------------------------------------------------
# _categorize_chain
# ---------------------------------------------------------------------------

class TestCategorizeChain:
    def test_pure_query_ops(self, sampler):
        # shape with only query ops
        from training.chain_sampler import ChainSampler
        cat = sampler._categorize_chain(["query", "query"])
        assert cat == "query"

    def test_mutate_ops(self, sampler):
        cat = sampler._categorize_chain(["query", "mutate"])
        assert cat == "mutation"

    def test_terminal_ops(self, sampler):
        cat = sampler._categorize_chain(["query", "terminal"])
        assert cat == "terminal"

    def test_delegate_ops(self, sampler):
        cat = sampler._categorize_chain(["query", "delegate"])
        assert cat == "delegate"

    def test_delegate_plus_mutate_is_pipeline(self, sampler):
        cat = sampler._categorize_chain(["mutate", "delegate"])
        assert cat == "pipeline"

    def test_entry_only_is_query(self, sampler):
        cat = sampler._categorize_chain(["entry"])
        assert cat == "query"


# ---------------------------------------------------------------------------
# Error-driven sampling
# ---------------------------------------------------------------------------

class TestErrorDrivenSampling:
    def test_returns_required_fields(self, sampler):
        pair = sampler.sample_error_driven()
        assert "chain" in pair
        assert "intent" in pair
        assert "context" in pair
        assert "language" in pair
        assert pair["category"] == "error_fix"

    def test_context_contains_error(self, sampler):
        pair = sampler.sample_error_driven()
        # Context should contain an error message
        assert "Error" in pair["context"] or "error" in pair["context"] or "panic" in pair["context"]

    def test_intent_starts_with_fix(self, sampler):
        pair = sampler.sample_error_driven()
        assert pair["intent"].startswith("Fix:")


# ---------------------------------------------------------------------------
# Code-contextual sampling
# ---------------------------------------------------------------------------

class TestCodeContextualSampling:
    def test_returns_required_fields(self, sampler):
        pair = sampler.sample_code_contextual()
        assert "chain" in pair
        assert "intent" in pair
        assert "context" in pair
        assert "language" in pair

    def test_context_contains_code(self, sampler):
        pair = sampler.sample_code_contextual()
        # Context should be actual code
        assert len(pair["context"]) > 10


# ---------------------------------------------------------------------------
# Multi-language sampling
# ---------------------------------------------------------------------------

class TestMultilangSampling:
    def test_returns_required_fields(self, sampler):
        pair = sampler.sample_multilang()
        assert "chain" in pair
        assert "language" in pair
        assert pair["language"] in ("python", "go", "typescript")

    def test_produces_different_languages(self, sampler):
        languages = set()
        for _ in range(50):
            pair = sampler.sample_multilang()
            languages.add(pair["language"])
        assert len(languages) >= 2
