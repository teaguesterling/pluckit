"""Tests for training.pools — name pools and selector samplers."""
from __future__ import annotations

import random

import pytest

from training.pools import (
    CLASS_NAMES,
    CODE_SNIPPETS,
    EXCEPTION_TYPES,
    FUNCTION_NAMES,
    GUARD_STRATEGIES,
    MODULE_PATHS,
    PARAM_SPECS,
    RENAME_TARGETS,
    sample_composed_selector,
    sample_selector,
)


# ---------------------------------------------------------------------------
# Pool size minimums
# ---------------------------------------------------------------------------

class TestPoolSizes:
    def test_function_names_minimum(self):
        assert len(FUNCTION_NAMES) >= 100

    def test_class_names_minimum(self):
        assert len(CLASS_NAMES) >= 50

    def test_module_paths_minimum(self):
        assert len(MODULE_PATHS) >= 8

    def test_param_specs_minimum(self):
        assert len(PARAM_SPECS) >= 9

    def test_exception_types_minimum(self):
        assert len(EXCEPTION_TYPES) >= 5

    def test_guard_strategies_minimum(self):
        assert len(GUARD_STRATEGIES) >= 5

    def test_rename_targets_not_empty(self):
        assert len(RENAME_TARGETS) >= 1


# ---------------------------------------------------------------------------
# Pool types
# ---------------------------------------------------------------------------

class TestPoolTypes:
    def test_function_names_are_strings(self):
        assert all(isinstance(n, str) for n in FUNCTION_NAMES)

    def test_class_names_are_strings(self):
        assert all(isinstance(n, str) for n in CLASS_NAMES)

    def test_module_paths_are_strings(self):
        assert all(isinstance(p, str) for p in MODULE_PATHS)

    def test_param_specs_are_strings(self):
        assert all(isinstance(s, str) for s in PARAM_SPECS)

    def test_exception_types_are_strings(self):
        assert all(isinstance(e, str) for e in EXCEPTION_TYPES)

    def test_guard_strategies_are_strings(self):
        assert all(isinstance(g, str) for g in GUARD_STRATEGIES)

    def test_rename_targets_are_tuples(self):
        for item in RENAME_TARGETS:
            assert isinstance(item, tuple)
            assert len(item) == 2
            assert all(isinstance(s, str) for s in item)


# ---------------------------------------------------------------------------
# CODE_SNIPPETS structure
# ---------------------------------------------------------------------------

class TestCodeSnippets:
    def test_has_prepend_key(self):
        assert "prepend" in CODE_SNIPPETS

    def test_has_append_key(self):
        assert "append" in CODE_SNIPPETS

    def test_has_wrap_before_key(self):
        assert "wrap_before" in CODE_SNIPPETS

    def test_has_wrap_after_key(self):
        assert "wrap_after" in CODE_SNIPPETS

    def test_prepend_is_list_of_strings(self):
        assert isinstance(CODE_SNIPPETS["prepend"], list)
        assert all(isinstance(s, str) for s in CODE_SNIPPETS["prepend"])

    def test_append_is_list_of_strings(self):
        assert isinstance(CODE_SNIPPETS["append"], list)
        assert all(isinstance(s, str) for s in CODE_SNIPPETS["append"])

    def test_wrap_before_is_list_of_strings(self):
        assert isinstance(CODE_SNIPPETS["wrap_before"], list)
        assert all(isinstance(s, str) for s in CODE_SNIPPETS["wrap_before"])

    def test_wrap_after_is_list_of_strings(self):
        assert isinstance(CODE_SNIPPETS["wrap_after"], list)
        assert all(isinstance(s, str) for s in CODE_SNIPPETS["wrap_after"])

    def test_all_categories_nonempty(self):
        for key in ("prepend", "append", "wrap_before", "wrap_after"):
            assert len(CODE_SNIPPETS[key]) >= 1, f"{key} must have at least one snippet"


# ---------------------------------------------------------------------------
# sample_selector
# ---------------------------------------------------------------------------

class TestSampleSelector:
    def _samples(self, n: int = 100, seed: int = 42) -> list[str]:
        rng = random.Random(seed)
        return [sample_selector(rng) for _ in range(n)]

    def test_returns_string(self):
        rng = random.Random(0)
        result = sample_selector(rng)
        assert isinstance(result, str)

    def test_starts_with_dot(self):
        for s in self._samples():
            assert s.startswith("."), f"Expected '.' prefix: {s!r}"

    def test_variety_in_100_samples(self):
        samples = self._samples(100)
        assert len(set(samples)) >= 10, "Expected 10+ distinct selectors in 100 samples"

    def test_produces_hash_name_selectors(self):
        """At least some samples should have #name."""
        samples = self._samples(200, seed=1)
        assert any("#" in s for s in samples), "Expected at least one #name selector"

    def test_produces_pseudo_selectors(self):
        """At least some samples should have a pseudo-class (:exported etc.)."""
        samples = self._samples(200, seed=2)
        assert any(":" in s for s in samples), "Expected at least one :pseudo selector"

    def test_produces_attribute_selectors(self):
        """At least some samples should have an attribute ([...])."""
        samples = self._samples(200, seed=3)
        assert any("[" in s for s in samples), "Expected at least one attribute selector"

    def test_uses_valid_node_types(self):
        """All selectors must begin with a known .node-type token."""
        valid_types = {
            ".fn", ".cls", ".call", ".ret", ".if", ".for", ".while", ".try",
            ".except", ".with", ".assign", ".import", ".dec", ".arg",
            ".str", ".num", ".block", ".comment",
        }
        for s in self._samples(100):
            # The selector starts with .type optionally followed by #, :, [
            node_part = s.split("#")[0].split(":")[0].split("[")[0]
            assert node_part in valid_types, f"Unknown node type in {s!r}"

    def test_reproducible_with_same_seed(self):
        rng1 = random.Random(99)
        rng2 = random.Random(99)
        results1 = [sample_selector(rng1) for _ in range(20)]
        results2 = [sample_selector(rng2) for _ in range(20)]
        assert results1 == results2


# ---------------------------------------------------------------------------
# sample_composed_selector
# ---------------------------------------------------------------------------

class TestSampleComposedSelector:
    def _samples(self, n: int = 100, seed: int = 42) -> list[str]:
        rng = random.Random(seed)
        return [sample_composed_selector(rng) for _ in range(n)]

    def test_returns_string(self):
        rng = random.Random(0)
        result = sample_composed_selector(rng)
        assert isinstance(result, str)

    def test_contains_dot(self):
        for s in self._samples():
            assert "." in s, f"Expected '.' in composed selector: {s!r}"

    def test_has_variety(self):
        samples = self._samples(100)
        assert len(set(samples)) >= 5, "Expected 5+ distinct composed selectors in 100 samples"

    def test_produces_descendant_selectors(self):
        """Descendant (space-separated) should appear with 40% probability."""
        samples = self._samples(200, seed=10)
        # Descendant: "A B" — contains space but not " > " or ":has" or ":not"
        descendant = [
            s for s in samples
            if " " in s and ">" not in s and ":has" not in s and ":not" not in s
        ]
        assert len(descendant) > 0, "Expected descendant selectors (A B)"

    def test_produces_child_selectors(self):
        """Direct child (A > B) should appear."""
        samples = self._samples(300, seed=11)
        assert any(">" in s for s in samples), "Expected child selectors (A > B)"

    def test_produces_has_selectors(self):
        """':has()' combinator should appear."""
        samples = self._samples(300, seed=12)
        assert any(":has(" in s for s in samples), "Expected :has() selectors"

    def test_produces_not_has_selectors(self):
        """':not(:has())' should appear."""
        samples = self._samples(300, seed=13)
        assert any(":not(:has(" in s for s in samples), "Expected :not(:has()) selectors"

    def test_reproducible_with_same_seed(self):
        rng1 = random.Random(77)
        rng2 = random.Random(77)
        results1 = [sample_composed_selector(rng1) for _ in range(20)]
        results2 = [sample_composed_selector(rng2) for _ in range(20)]
        assert results1 == results2
