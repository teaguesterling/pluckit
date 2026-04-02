"""Tests for training/spec.py — spec loader for api.yaml."""
import pytest
from pathlib import Path

# The spec module lives at training/spec.py, one level up from this test file.
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from training.spec import load_spec, Spec, TypeInfo, Operation, Selectors


SPEC_PATH = Path(__file__).parent.parent.parent / "reference" / "api.yaml"


@pytest.fixture(scope="module")
def spec():
    return load_spec(SPEC_PATH)


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

class TestVersion:
    def test_version_is_string(self, spec):
        assert isinstance(spec.version, str)

    def test_version_value(self, spec):
        assert spec.version == "0.1.0"


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class TestTypes:
    def test_loads_all_six_types(self, spec):
        expected = {"Source", "Selection", "Isolated", "History", "View", "terminal"}
        assert set(spec.types.keys()) == expected

    def test_type_info_has_name(self, spec):
        for name, t in spec.types.items():
            assert t.name == name

    def test_type_info_has_description(self, spec):
        for t in spec.types.values():
            assert isinstance(t.description, str)
            assert len(t.description) > 0

    def test_source_produces_selection(self, spec):
        assert spec.types["Source"].produces == ["Selection"]

    def test_selection_produces_multiple(self, spec):
        produces = spec.types["Selection"].produces
        assert len(produces) >= 4
        assert "Selection" in produces
        assert "terminal" in produces

    def test_terminal_produces_nothing(self, spec):
        assert spec.types["terminal"].produces == []

    def test_isolated_produces_terminal(self, spec):
        assert "terminal" in spec.types["Isolated"].produces

    def test_history_produces_selection_and_terminal(self, spec):
        produces = spec.types["History"].produces
        assert "Selection" in produces
        assert "terminal" in produces


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

class TestOperations:
    def test_operations_is_dict(self, spec):
        assert isinstance(spec.operations, dict)

    def test_loads_entry_point_select(self, spec):
        assert "select" in spec.operations

    def test_loads_entry_point_source(self, spec):
        assert "source" in spec.operations

    def test_operation_has_required_fields(self, spec):
        for name, op in spec.operations.items():
            assert op.name == name, f"op.name mismatch for {name}"
            assert isinstance(op.category, str), f"category missing for {name}"
            assert isinstance(op.signature, str), f"signature missing for {name}"

    def test_loads_query_ops(self, spec):
        for op_name in ["find", "filter", "not_", "unique", "parent", "children"]:
            assert op_name in spec.operations, f"{op_name} not found"

    def test_loads_mutation_ops(self, spec):
        for op_name in ["addParam", "removeParam", "rename", "prepend", "append",
                        "wrap", "unwrap", "replaceWith", "remove"]:
            assert op_name in spec.operations, f"{op_name} not found"

    def test_loads_terminal_ops(self, spec):
        for op_name in ["text", "attr", "count", "names", "complexity", "interface"]:
            assert op_name in spec.operations, f"{op_name} not found"

    def test_loads_delegate_ops(self, spec):
        for op_name in ["black", "ruff_fix", "guard", "save", "test", "fuzz"]:
            assert op_name in spec.operations, f"{op_name} not found"

    def test_select_category_is_entry(self, spec):
        assert spec.operations["select"].category == "entry"

    def test_select_has_no_input_type(self, spec):
        assert spec.operations["select"].input_type is None

    def test_select_output_type(self, spec):
        assert spec.operations["select"].output_type == "Selection"

    def test_find_input_output_types(self, spec):
        find = spec.operations["find"]
        # find has two definitions (Source.find and Selection.find);
        # either input is acceptable — just verify output is Selection
        assert find.output_type == "Selection"

    def test_addparam_category_is_mutate(self, spec):
        assert spec.operations["addParam"].category == "mutate"

    def test_text_category_is_terminal(self, spec):
        assert spec.operations["text"].category == "terminal"

    def test_select_has_examples(self, spec):
        examples = spec.operations["select"].examples
        assert examples is not None
        assert len(examples) >= 1
        assert "call" in examples[0]
        assert "intent" in examples[0]

    def test_addparam_has_param_examples(self, spec):
        param_examples = spec.operations["addParam"].param_examples
        assert param_examples is not None
        assert len(param_examples) >= 3

    def test_at_has_ref_examples(self, spec):
        ref_examples = spec.operations["at"].ref_examples
        assert ref_examples is not None
        assert len(ref_examples) >= 4

    def test_guard_has_strategy_examples(self, spec):
        strategy_examples = spec.operations["guard"].strategy_examples
        assert strategy_examples is not None
        assert len(strategy_examples) >= 3

    def test_filter_has_predicate_examples(self, spec):
        predicate_examples = spec.operations["filter"].predicate_examples
        assert predicate_examples is not None
        assert len(predicate_examples) >= 3
        assert "predicate" in predicate_examples[0]
        assert "intent" in predicate_examples[0]

    def test_operations_without_optional_fields_have_none(self, spec):
        # 'count' has no examples defined in the yaml
        count_op = spec.operations["count"]
        assert count_op.examples is None or isinstance(count_op.examples, list)

    def test_total_operation_count(self, spec):
        # There are many operations defined; just verify we got a reasonable number
        assert len(spec.operations) >= 30


# ---------------------------------------------------------------------------
# Selectors
# ---------------------------------------------------------------------------

class TestSelectors:
    def test_selectors_is_selectors_object(self, spec):
        assert isinstance(spec.selectors, Selectors)

    def test_loads_18_plus_node_types(self, spec):
        assert len(spec.selectors.node_types) >= 18

    def test_node_types_have_short_full_description(self, spec):
        for nt in spec.selectors.node_types:
            assert "short" in nt
            assert "full" in nt
            assert "description" in nt

    def test_loads_7_plus_pseudo_selectors(self, spec):
        assert len(spec.selectors.pseudo_selectors) >= 7

    def test_pseudo_selectors_have_syntax_and_description(self, spec):
        for ps in spec.selectors.pseudo_selectors:
            assert "syntax" in ps
            assert "description" in ps

    def test_loads_5_plus_attribute_selectors(self, spec):
        assert len(spec.selectors.attribute_selectors) >= 5

    def test_loads_4_plus_combinators(self, spec):
        assert len(spec.selectors.combinators) >= 4

    def test_name_selector_syntax(self, spec):
        assert spec.selectors.name_selector_syntax == "#<identifier>"

    def test_name_selector_examples(self, spec):
        examples = spec.selectors.name_selector_examples
        assert len(examples) >= 2
        assert "selector" in examples[0]
        assert "description" in examples[0]


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------

class TestComposition:
    def test_composition_is_dict(self, spec):
        assert isinstance(spec.composition, dict)

    def test_source_has_find(self, spec):
        source_comp = spec.composition["Source"]
        # Source composition is a list
        assert isinstance(source_comp, list)
        assert "find" in source_comp

    def test_selection_has_category_dicts(self, spec):
        sel_comp = spec.composition["Selection"]
        assert isinstance(sel_comp, dict)
        assert "query" in sel_comp
        assert "mutate" in sel_comp
        assert "terminal" in sel_comp
        assert "delegate" in sel_comp

    def test_selection_query_has_expected_ops(self, spec):
        query_ops = spec.composition["Selection"]["query"]
        for op_name in ["find", "filter", "parent", "children", "callers"]:
            assert op_name in query_ops

    def test_selection_mutate_has_expected_ops(self, spec):
        mutate_ops = spec.composition["Selection"]["mutate"]
        for op_name in ["addParam", "rename", "prepend", "remove"]:
            assert op_name in mutate_ops

    def test_selection_terminal_has_expected_ops(self, spec):
        terminal_ops = spec.composition["Selection"]["terminal"]
        for op_name in ["text", "count", "names", "complexity"]:
            assert op_name in terminal_ops

    def test_isolated_has_ops(self, spec):
        isolated_comp = spec.composition["Isolated"]
        assert isinstance(isolated_comp, list)
        assert len(isolated_comp) >= 3

    def test_history_has_ops(self, spec):
        history_comp = spec.composition["History"]
        assert isinstance(history_comp, list)
        assert len(history_comp) >= 2


# ---------------------------------------------------------------------------
# Example chains
# ---------------------------------------------------------------------------

class TestExampleChains:
    def test_example_chains_is_dict(self, spec):
        assert isinstance(spec.example_chains, dict)

    def test_loads_7_plus_categories(self, spec):
        assert len(spec.example_chains) >= 7

    def test_expected_categories_present(self, spec):
        for category in ["simple_queries", "mutations", "pipelines", "history",
                         "isolation", "with_intent", "views"]:
            assert category in spec.example_chains, f"category '{category}' missing"

    def test_examples_have_intent_and_chain(self, spec):
        for category, examples in spec.example_chains.items():
            assert isinstance(examples, list), f"{category} should be a list"
            for ex in examples:
                assert "intent" in ex, f"missing 'intent' in {category}"
                assert "chain" in ex, f"missing 'chain' in {category}"

    def test_simple_queries_has_multiple_examples(self, spec):
        assert len(spec.example_chains["simple_queries"]) >= 5

    def test_chain_values_are_strings(self, spec):
        for category, examples in spec.example_chains.items():
            for ex in examples:
                assert isinstance(ex["chain"], str), \
                    f"chain in {category} should be a string"
                assert isinstance(ex["intent"], str), \
                    f"intent in {category} should be a string"
