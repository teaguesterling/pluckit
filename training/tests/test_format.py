"""Tests for training/format.py — chat JSONL formatter for fine-tuning."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from training.format import format_pair, format_pair_completion, generate_operations_comment, main as format_main
from training.spec import load_spec
from training.system_prompt import generate_system_prompt

SPEC_PATH = Path(__file__).parent.parent.parent / "reference" / "api.yaml"


@pytest.fixture(scope="module")
def system_prompt():
    spec = load_spec(SPEC_PATH)
    return generate_system_prompt(spec)


@pytest.fixture
def sample_record():
    return {
        "intent": "Find all exported functions",
        "chain": "select('.fn:exported').names()",
    }


# ---------------------------------------------------------------------------
# format_pair unit tests
# ---------------------------------------------------------------------------

class TestFormatPair:
    def test_returns_dict_with_messages_key(self, sample_record, system_prompt):
        result = format_pair(sample_record, system_prompt)
        assert isinstance(result, dict)
        assert "messages" in result

    def test_messages_has_three_entries(self, sample_record, system_prompt):
        result = format_pair(sample_record, system_prompt)
        assert len(result["messages"]) == 3

    def test_message_roles_are_system_user_assistant(self, sample_record, system_prompt):
        result = format_pair(sample_record, system_prompt)
        roles = [msg["role"] for msg in result["messages"]]
        assert roles == ["system", "user", "assistant"]

    def test_system_message_content_matches_prompt(self, sample_record, system_prompt):
        result = format_pair(sample_record, system_prompt)
        assert result["messages"][0]["content"] == system_prompt

    def test_user_message_content_is_intent(self, sample_record, system_prompt):
        result = format_pair(sample_record, system_prompt)
        assert result["messages"][1]["content"] == sample_record["intent"]

    def test_assistant_message_content_is_chain(self, sample_record, system_prompt):
        result = format_pair(sample_record, system_prompt)
        assert result["messages"][2]["content"] == sample_record["chain"]

    def test_each_message_has_role_and_content_keys(self, sample_record, system_prompt):
        result = format_pair(sample_record, system_prompt)
        for msg in result["messages"]:
            assert "role" in msg
            assert "content" in msg

    def test_no_extra_keys_in_messages(self, sample_record, system_prompt):
        result = format_pair(sample_record, system_prompt)
        for msg in result["messages"]:
            assert set(msg.keys()) == {"role", "content"}

    def test_different_records_produce_different_user_content(self, system_prompt):
        record_a = {"intent": "Count functions", "chain": "select('.fn').count()"}
        record_b = {"intent": "Get function names", "chain": "select('.fn').names()"}
        result_a = format_pair(record_a, system_prompt)
        result_b = format_pair(record_b, system_prompt)
        assert result_a["messages"][1]["content"] != result_b["messages"][1]["content"]
        assert result_a["messages"][2]["content"] != result_b["messages"][2]["content"]


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------

def _make_input_jsonl(records: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def _make_system_prompt_file(prompt: str, path: Path) -> None:
    path.write_text(prompt, encoding="utf-8")


def _run_cli(argv: list[str]) -> None:
    """Import and call main() with the given argv."""
    from training.format import main
    main(argv)


class TestCLIOutput:
    def test_output_line_count_matches_input(self, system_prompt):
        records = [
            {"intent": f"intent {i}", "chain": f"select('.fn').count()"}
            for i in range(5)
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            input_file = tmpdir / "input.jsonl"
            output_file = tmpdir / "output.jsonl"
            prompt_file = tmpdir / "system_prompt.txt"

            _make_input_jsonl(records, input_file)
            _make_system_prompt_file(system_prompt, prompt_file)

            _run_cli([
                str(input_file),
                "--output", str(output_file),
                "--system-prompt", str(prompt_file),
            ])

            lines = output_file.read_text(encoding="utf-8").strip().splitlines()
            assert len(lines) == 5

    def test_each_output_line_is_valid_json(self, system_prompt):
        records = [
            {"intent": f"intent {i}", "chain": "select('.fn').names()"}
            for i in range(3)
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            input_file = tmpdir / "input.jsonl"
            output_file = tmpdir / "output.jsonl"
            prompt_file = tmpdir / "system_prompt.txt"

            _make_input_jsonl(records, input_file)
            _make_system_prompt_file(system_prompt, prompt_file)

            _run_cli([
                str(input_file),
                "--output", str(output_file),
                "--system-prompt", str(prompt_file),
            ])

            for line in output_file.read_text(encoding="utf-8").strip().splitlines():
                obj = json.loads(line)
                assert "messages" in obj

    def test_output_records_have_correct_structure(self, system_prompt):
        records = [{"intent": "Find exports", "chain": "select('.fn:exported').names()"}]
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            input_file = tmpdir / "input.jsonl"
            output_file = tmpdir / "output.jsonl"
            prompt_file = tmpdir / "system_prompt.txt"

            _make_input_jsonl(records, input_file)
            _make_system_prompt_file(system_prompt, prompt_file)

            _run_cli([
                str(input_file),
                "--output", str(output_file),
                "--system-prompt", str(prompt_file),
            ])

            obj = json.loads(output_file.read_text(encoding="utf-8").strip())
            roles = [m["role"] for m in obj["messages"]]
            assert roles == ["system", "user", "assistant"]


class TestCLISplit:
    def test_split_produces_train_and_val_files(self, system_prompt):
        records = [
            {"intent": f"intent {i}", "chain": "select('.fn').count()"}
            for i in range(10)
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            input_file = tmpdir / "input.jsonl"
            output_file = tmpdir / "output.jsonl"
            train_file = tmpdir / "train.jsonl"
            val_file = tmpdir / "val.jsonl"
            prompt_file = tmpdir / "system_prompt.txt"

            _make_input_jsonl(records, input_file)
            _make_system_prompt_file(system_prompt, prompt_file)

            _run_cli([
                str(input_file),
                "--output", str(output_file),
                "--system-prompt", str(prompt_file),
                "--split", "0.8",
                "--train-file", str(train_file),
                "--val-file", str(val_file),
            ])

            assert train_file.exists()
            assert val_file.exists()

    def test_split_80_20_on_10_records(self, system_prompt):
        records = [
            {"intent": f"intent {i}", "chain": "select('.fn').count()"}
            for i in range(10)
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            input_file = tmpdir / "input.jsonl"
            output_file = tmpdir / "output.jsonl"
            train_file = tmpdir / "train.jsonl"
            val_file = tmpdir / "val.jsonl"
            prompt_file = tmpdir / "system_prompt.txt"

            _make_input_jsonl(records, input_file)
            _make_system_prompt_file(system_prompt, prompt_file)

            _run_cli([
                str(input_file),
                "--output", str(output_file),
                "--system-prompt", str(prompt_file),
                "--split", "0.8",
                "--train-file", str(train_file),
                "--val-file", str(val_file),
                "--seed", "42",
            ])

            train_lines = train_file.read_text(encoding="utf-8").strip().splitlines()
            val_lines = val_file.read_text(encoding="utf-8").strip().splitlines()

            assert len(train_lines) == 8
            assert len(val_lines) == 2
            assert len(train_lines) + len(val_lines) == 10

    def test_split_seed_is_deterministic(self, system_prompt):
        records = [
            {"intent": f"intent {i}", "chain": "select('.fn').count()"}
            for i in range(10)
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            prompt_file = tmpdir / "system_prompt.txt"
            _make_system_prompt_file(system_prompt, prompt_file)

            def run_split(suffix):
                input_file = tmpdir / f"input_{suffix}.jsonl"
                output_file = tmpdir / f"output_{suffix}.jsonl"
                train_file = tmpdir / f"train_{suffix}.jsonl"
                val_file = tmpdir / f"val_{suffix}.jsonl"
                _make_input_jsonl(records, input_file)
                _run_cli([
                    str(input_file),
                    "--output", str(output_file),
                    "--system-prompt", str(prompt_file),
                    "--split", "0.8",
                    "--train-file", str(train_file),
                    "--val-file", str(val_file),
                    "--seed", "42",
                ])
                return train_file.read_text(encoding="utf-8")

            result_a = run_split("a")
            result_b = run_split("b")
            assert result_a == result_b

    def test_split_no_overlap_between_train_and_val(self, system_prompt):
        records = [
            {"intent": f"intent {i}", "chain": "select('.fn').count()"}
            for i in range(10)
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            input_file = tmpdir / "input.jsonl"
            output_file = tmpdir / "output.jsonl"
            train_file = tmpdir / "train.jsonl"
            val_file = tmpdir / "val.jsonl"
            prompt_file = tmpdir / "system_prompt.txt"

            _make_input_jsonl(records, input_file)
            _make_system_prompt_file(system_prompt, prompt_file)

            _run_cli([
                str(input_file),
                "--output", str(output_file),
                "--system-prompt", str(prompt_file),
                "--split", "0.8",
                "--train-file", str(train_file),
                "--val-file", str(val_file),
            ])

            train_intents = {
                json.loads(line)["messages"][1]["content"]
                for line in train_file.read_text(encoding="utf-8").strip().splitlines()
            }
            val_intents = {
                json.loads(line)["messages"][1]["content"]
                for line in val_file.read_text(encoding="utf-8").strip().splitlines()
            }
            assert train_intents.isdisjoint(val_intents)


# ---------------------------------------------------------------------------
# Context field tests
# ---------------------------------------------------------------------------

class TestFormatPairWithContext:
    def test_context_included_in_user_message(self, system_prompt):
        record = {
            "intent": "Fix the TypeError",
            "chain": "select('.fn').replaceWith('old', 'new')",
            "context": "TypeError: expected str, got None\n  File 'auth.py', line 23",
        }
        result = format_pair(record, system_prompt)
        user_msg = result["messages"][1]["content"]
        assert "TypeError" in user_msg
        assert "```" in user_msg  # code fences

    def test_no_context_no_fences(self, system_prompt):
        record = {
            "intent": "find all functions",
            "chain": "select('.fn')",
        }
        result = format_pair(record, system_prompt)
        user_msg = result["messages"][1]["content"]
        assert "```" not in user_msg
        assert user_msg == "find all functions"


# ---------------------------------------------------------------------------
# Completion format tests
# ---------------------------------------------------------------------------

class TestCompletionFormat:
    def test_format_pair_completion(self):
        ops_spec = "# .find(selector) -> Selection  -- find descendants"
        record = {
            "intent": "find all public functions",
            "chain": "select('.fn:exported')",
        }
        result = format_pair_completion(record, ops_spec)
        assert "prompt" in result
        assert "completion" in result
        assert "from code_tools import" in result["prompt"]
        assert "# TODO:" in result["prompt"]
        assert result["completion"] == "select('.fn:exported')"

    def test_completion_includes_context(self):
        ops_spec = "# .find(selector) -> Selection"
        record = {
            "intent": "Fix the None return",
            "chain": "select('.fn').replaceWith('return None', 'raise ValueError()')",
            "context": "def validate(x):\n    return None",
        }
        result = format_pair_completion(record, ops_spec)
        assert "# def validate(x):" in result["prompt"]
        assert "# TODO: Fix the None return" in result["prompt"]

    def test_completion_includes_ops_spec(self):
        ops_spec = "# Available operations:\n# select(selector) -> Selection"
        record = {
            "intent": "count functions",
            "chain": "select('.fn').count()",
        }
        result = format_pair_completion(record, ops_spec)
        assert "Available operations" in result["prompt"]


# ---------------------------------------------------------------------------
# generate_operations_comment tests
# ---------------------------------------------------------------------------

class TestGenerateOperationsComment:
    def test_returns_string(self):
        spec = load_spec(SPEC_PATH)
        result = generate_operations_comment(spec)
        assert isinstance(result, str)
        assert "select" in result
        assert "source" in result
        assert ".find" in result

    def test_includes_mutation_ops(self):
        spec = load_spec(SPEC_PATH)
        result = generate_operations_comment(spec)
        assert "addParam" in result or "rename" in result

    def test_includes_query_ops(self):
        spec = load_spec(SPEC_PATH)
        result = generate_operations_comment(spec)
        assert "find" in result
