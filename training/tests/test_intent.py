"""Tests for training/intent.py — template-based intent generation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import random
import pytest
from training.intent import describe_selector, generate_intent


# ---------------------------------------------------------------------------
# describe_selector tests
# ---------------------------------------------------------------------------

class TestDescribeSelector:
    def test_fn_exported_contains_public_or_exported(self):
        result = describe_selector(".fn:exported")
        assert "public" in result.lower() or "exported" in result.lower()

    def test_fn_name_contains_name(self):
        result = describe_selector(".fn#validate_token")
        assert "validate_token" in result

    def test_cls_name_contains_class_name(self):
        result = describe_selector(".cls#AuthService")
        assert "AuthService" in result

    def test_fn_attr_prefix_contains_pattern(self):
        result = describe_selector('.fn[name^="test_"]')
        assert "test_" in result or "start" in result.lower()

    def test_call_name_contains_name(self):
        result = describe_selector(".call#print")
        assert "print" in result

    def test_fn_has_call_contains_both(self):
        result = describe_selector(".fn:has(.call#print)")
        assert "print" in result

    def test_fn_private_contains_private(self):
        result = describe_selector(".fn:private")
        assert "private" in result.lower()

    def test_bare_fn_contains_function_word(self):
        result = describe_selector(".fn")
        assert "function" in result.lower() or "fn" in result.lower()

    def test_bare_cls_contains_class_word(self):
        result = describe_selector(".cls")
        assert "class" in result.lower() or "cls" in result.lower()

    def test_returns_string(self):
        result = describe_selector(".fn:exported")
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# generate_intent — basic return type tests
# ---------------------------------------------------------------------------

class TestGenerateIntentBasic:
    def setup_method(self):
        self.rng = random.Random(42)

    def test_returns_non_empty_string(self):
        chain = "select('.fn:exported')"
        result = generate_intent(chain, ["select"], "query", self.rng)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_return_metadata_returns_dict(self):
        chain = "select('.fn:exported')"
        result = generate_intent(chain, ["select"], "query", self.rng,
                                 return_metadata=True)
        assert isinstance(result, dict)
        assert "intent" in result
        assert "strategy" in result

    def test_metadata_intent_is_string(self):
        chain = "select('.fn:exported')"
        result = generate_intent(chain, ["select"], "query", self.rng,
                                 return_metadata=True)
        assert isinstance(result["intent"], str)
        assert len(result["intent"]) > 0

    def test_metadata_strategy_is_valid(self):
        chain = "select('.fn:exported')"
        result = generate_intent(chain, ["select"], "query", self.rng,
                                 return_metadata=True)
        assert result["strategy"] in ("template", "paraphrase", "reverse")


# ---------------------------------------------------------------------------
# generate_intent — operation-specific content tests
# ---------------------------------------------------------------------------

class TestGenerateIntentOperations:
    def setup_method(self):
        self.rng = random.Random(42)

    def test_select_mentions_find_or_public(self):
        chain = "select('.fn:exported')"
        result = generate_intent(chain, ["select"], "query", self.rng)
        lower = result.lower()
        assert any(word in lower for word in ("find", "show", "public", "exported", "function"))

    def test_addparam_mentions_add_or_param(self):
        chain = "select('.fn:exported').addParam('timeout: int = 30')"
        result = generate_intent(chain, ["select", "addParam"], "mutation", self.rng)
        lower = result.lower()
        assert "add" in lower or "param" in lower or "timeout" in lower

    def test_rename_mentions_rename_or_new_name(self):
        chain = "select('.fn#process_data').rename('transform_batch')"
        result = generate_intent(chain, ["select", "rename"], "mutation", self.rng)
        lower = result.lower()
        assert "rename" in lower or "transform_batch" in lower

    def test_count_mentions_count_or_how_many(self):
        chain = "select('.fn:exported').count()"
        result = generate_intent(chain, ["select", "count"], "query", self.rng)
        lower = result.lower()
        assert "count" in lower or "how many" in lower

    def test_guard_mentions_error_or_handling(self):
        chain = "select('.fn:exported').guard('ValueError', 'log and reraise')"
        result = generate_intent(chain, ["select", "guard"], "mutation", self.rng)
        lower = result.lower()
        assert any(word in lower for word in ("error", "handling", "guard", "valueerror", "exception"))

    def test_rename_chain_mentions_old_or_new_name(self):
        chain = "select('.fn#get_data').rename('fetch_data')"
        result = generate_intent(chain, ["select", "rename"], "mutation", self.rng)
        assert "fetch_data" in result or "rename" in result.lower() or "get_data" in result

    def test_callers_mentions_who_or_calls(self):
        chain = "select('.fn#validate_token').callers()"
        result = generate_intent(chain, ["select", "callers"], "query", self.rng)
        lower = result.lower()
        assert "call" in lower or "who" in lower

    def test_diff_mentions_changed_or_diff(self):
        chain = "select('.fn#validate_token').at('v1.0').diff()"
        result = generate_intent(chain, ["select", "at", "diff"], "query", self.rng)
        lower = result.lower()
        assert "diff" in lower or "changed" in lower or "since" in lower

    def test_save_mentions_commit_or_save_or_check_in(self):
        chain = "select('.fn:exported').addParam('timeout: int = 30').save('feat: add timeout')"
        result = generate_intent(chain, ["select", "addParam", "save"], "mutation", self.rng)
        lower = result.lower()
        assert "commit" in lower or "save" in lower or "check it in" in lower

    def test_fallback_for_unknown_op(self):
        chain = "select('.fn').unknownOp()"
        result = generate_intent(chain, ["select", "unknownOp"], "query", self.rng)
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# generate_intent — strategy distribution test
# ---------------------------------------------------------------------------

class TestStrategyDistribution:
    def test_strategy_distribution_roughly_matches_ratios(self):
        rng = random.Random(0)
        chain = "select('.fn:exported')"
        counts = {"template": 0, "paraphrase": 0, "reverse": 0}
        n = 200
        for _ in range(n):
            result = generate_intent(chain, ["select"], "query", rng,
                                     return_metadata=True,
                                     paraphrase_ratio=0.3,
                                     reverse_ratio=0.1)
            counts[result["strategy"]] += 1

        # Allow generous tolerance: ±15% absolute
        assert counts["template"] / n > 0.45, f"template too low: {counts}"
        assert counts["paraphrase"] / n > 0.10, f"paraphrase too low: {counts}"
        assert counts["reverse"] / n > 0.00, f"reverse too low: {counts}"
        # reverse should be less common than paraphrase
        assert counts["reverse"] < counts["paraphrase"], f"reverse >= paraphrase: {counts}"
