"""Tests for training/chain_parser.py — chain string parser."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
from training.chain_parser import parse_chain, ChainOp, _split_args


# ---------------------------------------------------------------------------
# _split_args helper
# ---------------------------------------------------------------------------

class TestSplitArgs:
    def test_single_arg(self):
        assert _split_args("'hello'") == ["'hello'"]

    def test_two_simple_args(self):
        assert _split_args("'a', 'b'") == ["'a'", "'b'"]

    def test_strips_whitespace(self):
        assert _split_args("  'a' ,  'b'  ") == ["'a'", "'b'"]

    def test_empty_string(self):
        assert _split_args("") == []

    def test_nested_parens(self):
        # A nested call like select('.fn').at('v1') should not be split at the
        # comma inside the nested call.
        result = _split_args("select('.fn').at('v1'), 'other'")
        assert result == ["select('.fn').at('v1')", "'other'"]

    def test_nested_brackets(self):
        result = _split_args("[1, 2, 3], 'x'")
        assert result == ["[1, 2, 3]", "'x'"]

    def test_nested_braces(self):
        result = _split_args("{'a': 1, 'b': 2}, 'x'")
        assert result == ["{'a': 1, 'b': 2}", "'x'"]

    def test_double_quoted_string_with_comma(self):
        result = _split_args('"hello, world", "foo"')
        assert result == ['"hello, world"', '"foo"']

    def test_single_quoted_string_with_comma(self):
        result = _split_args("'hello, world', 'foo'")
        assert result == ["'hello, world'", "'foo'"]

    def test_escaped_quote_in_single_string(self):
        result = _split_args(r"'it\'s here', 'other'")
        assert result == [r"'it\'s here'", "'other'"]

    def test_escaped_quote_in_double_string(self):
        result = _split_args(r'"say \"hi\"", "other"')
        assert result == [r'"say \"hi\""', '"other"']

    def test_three_args(self):
        result = _split_args("'a', 'b', 'c'")
        assert result == ["'a'", "'b'", "'c'"]

    def test_arrow_predicate_not_split(self):
        # Arrow-style predicates contain a colon but no comma at top level
        result = _split_args("fn: fn.params().count() > 5")
        assert result == ["fn: fn.params().count() > 5"]


# ---------------------------------------------------------------------------
# ChainOp dataclass
# ---------------------------------------------------------------------------

class TestChainOpDataclass:
    def test_name_only(self):
        op = ChainOp(name="black")
        assert op.name == "black"
        assert op.args == []

    def test_name_and_args(self):
        op = ChainOp(name="select", args=["'.fn:exported'"])
        assert op.name == "select"
        assert op.args == ["'.fn:exported'"]

    def test_repr_no_args(self):
        op = ChainOp(name="filmstrip")
        r = repr(op)
        assert "filmstrip" in r

    def test_repr_with_args(self):
        op = ChainOp(name="select", args=["'.fn'"])
        r = repr(op)
        assert "select" in r
        assert ".fn" in r

    def test_default_args_are_independent(self):
        # Verify default_factory is used (mutable default guard)
        op1 = ChainOp(name="a")
        op2 = ChainOp(name="b")
        op1.args.append("x")
        assert op2.args == []


# ---------------------------------------------------------------------------
# Simple chains
# ---------------------------------------------------------------------------

class TestSimpleChains:
    def test_select_only(self):
        ops = parse_chain("select('.fn:exported')")
        assert len(ops) == 1
        assert ops[0].name == "select"
        assert ops[0].args == ["'.fn:exported'"]

    def test_source_find(self):
        ops = parse_chain("source('tests/**/*.py').find('.fn[name^=\"test_\"]')")
        assert len(ops) == 2
        assert ops[0].name == "source"
        assert ops[0].args == ["'tests/**/*.py'"]
        assert ops[1].name == "find"
        assert ops[1].args == ['\'.fn[name^="test_"]\'']

    def test_select_filter_with_predicate(self):
        ops = parse_chain("select('.fn').filter(fn: fn.params().count() > 5)")
        assert len(ops) == 2
        assert ops[0].name == "select"
        assert ops[1].name == "filter"
        assert ops[1].args == ["fn: fn.params().count() > 5"]

    def test_three_op_chain(self):
        ops = parse_chain("select('.call#print').parent('.fn').find('.call#print')")
        assert len(ops) == 3
        assert ops[0].name == "select"
        assert ops[1].name == "parent"
        assert ops[2].name == "find"

    def test_no_arg_method(self):
        ops = parse_chain("select('.fn#process_data').filmstrip()")
        assert len(ops) == 2
        assert ops[1].name == "filmstrip"
        assert ops[1].args == []


# ---------------------------------------------------------------------------
# Mutation chains
# ---------------------------------------------------------------------------

class TestMutationChains:
    def test_rename_with_arg(self):
        ops = parse_chain("select('.fn#process_data').rename('transform_batch')")
        assert len(ops) == 2
        assert ops[1].name == "rename"
        assert ops[1].args == ["'transform_batch'"]

    def test_addparam_with_arg(self):
        ops = parse_chain("select('.fn:exported').addParam('timeout: int = 30')")
        assert len(ops) == 2
        assert ops[1].name == "addParam"
        assert ops[1].args == ["'timeout: int = 30'"]


# ---------------------------------------------------------------------------
# Pipeline chains (multi-op)
# ---------------------------------------------------------------------------

class TestPipelineChains:
    def test_five_op_pipeline(self):
        chain = "select('.fn:exported').addParam('timeout: int = 30').black().test().save('feat: add timeout parameter')"
        ops = parse_chain(chain)
        assert len(ops) == 5
        assert ops[0].name == "select"
        assert ops[1].name == "addParam"
        assert ops[2].name == "black"
        assert ops[2].args == []
        assert ops[3].name == "test"
        assert ops[3].args == []
        assert ops[4].name == "save"
        assert ops[4].args == ["'feat: add timeout parameter'"]

    def test_guard_two_args(self):
        ops = parse_chain("select('.call[name*=\"query\"]').guard('DatabaseError', 'log and reraise')")
        assert len(ops) == 2
        assert ops[1].name == "guard"
        assert len(ops[1].args) == 2
        assert ops[1].args[0] == "'DatabaseError'"
        assert ops[1].args[1] == "'log and reraise'"

    def test_source_pipeline(self):
        chain = "source('src/client/**/*.py').find('.call[name*=\"request\"]').guard('RequestError', 'retry 3 times').black().save('fix: add retry to API calls')"
        ops = parse_chain(chain)
        assert len(ops) == 5
        assert ops[0].name == "source"
        assert ops[1].name == "find"
        assert ops[2].name == "guard"
        assert len(ops[2].args) == 2
        assert ops[3].name == "black"
        assert ops[4].name == "save"


# ---------------------------------------------------------------------------
# Complex / nested chains
# ---------------------------------------------------------------------------

class TestComplexChains:
    def test_nested_select_in_diff(self):
        chain = "select('.fn#validate_token').diff(select('.fn#validate_token').at('last_green_build'))"
        ops = parse_chain(chain)
        assert len(ops) == 2
        assert ops[0].name == "select"
        assert ops[1].name == "diff"
        # The nested chain should be one argument
        assert len(ops[1].args) == 1
        assert "select(" in ops[1].args[0]

    def test_isolate_test_chain(self):
        chain = "select('.fn#process_data .for:first').isolate().test({'items': [1, 2, 3]})"
        ops = parse_chain(chain)
        assert len(ops) == 3
        assert ops[0].name == "select"
        assert ops[1].name == "isolate"
        assert ops[1].args == []
        assert ops[2].name == "test"
        # The dict arg should be kept intact
        assert ops[2].args == ["{'items': [1, 2, 3]}"]

    def test_complex_filter_chain(self):
        chain = "select('.fn').filter(fn: fn.complexity() > 10).filter(fn: fn.coverage() < 0.5)"
        ops = parse_chain(chain)
        assert len(ops) == 3
        assert all(op.name in ("select", "filter") for op in ops)
        assert ops[1].args == ["fn: fn.complexity() > 10"]
        assert ops[2].args == ["fn: fn.coverage() < 0.5"]

    def test_at_with_nested_select_and_inputs(self):
        chain = "select('.fn#validate_token').at('before_refactor').isolate().test(select('.fn#validate_token').inputs().last(10))"
        ops = parse_chain(chain)
        assert len(ops) == 4
        assert ops[0].name == "select"
        assert ops[1].name == "at"
        assert ops[1].args == ["'before_refactor'"]
        assert ops[2].name == "isolate"
        assert ops[3].name == "test"
        assert "select(" in ops[3].args[0]

    def test_reachable_with_kwarg(self):
        chain = "select('.fn#login, .fn#logout, .fn#refresh_token').reachable(max_depth=3)"
        ops = parse_chain(chain)
        assert len(ops) == 2
        assert ops[1].name == "reachable"
        assert ops[1].args == ["max_depth=3"]

    def test_similar_with_float_arg(self):
        chain = "select('.fn[name^=\"validate_\"]').similar(0.7).refactor('validate_credential')"
        ops = parse_chain(chain)
        assert len(ops) == 3
        assert ops[1].name == "similar"
        assert ops[1].args == ["0.7"]
        assert ops[2].name == "refactor"
