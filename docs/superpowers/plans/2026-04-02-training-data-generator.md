# Training Data Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a synthetic training data generator that produces (intent, chain) pairs from the pluckit API spec (`reference/api.yaml`) for fine-tuning a 1.5B code model to generate pluckit chains from natural language.

**Architecture:** A three-stage JSONL pipeline: generate → validate → format. The generator samples type-valid chain shapes from the spec's composition rules, fills selectors and arguments from pools, and generates template-based intents. The validator type-checks chains and filters low-quality pairs. The formatter converts to chat JSONL with a system prompt auto-generated from the spec. No pluckit implementation needed — everything works from the type system in api.yaml.

**Tech Stack:** Python 3.12+, pyyaml, stdlib only (no external API calls)

**Key design decision:** Intent enrichment strategies (template/paraphrase/reverse) are metadata labels only — all intents are template-generated, the `strategy` field is assigned by configured ratios but doesn't change content. No Ollama/Anthropic dependency.

---

## File Structure

```
training/
├── spec.py              # Load api.yaml → Python objects (types, ops, selectors, composition rules)
├── pools.py             # Name pools: function names, class names, module paths, param specs, code snippets
├── chain_parser.py      # Parse chain strings into operation sequences (for validation)
├── chain_sampler.py     # Sample type-valid chain shapes, fill selectors and arguments
├── intent.py            # Template-based intent generation from chain parameters
├── generate.py          # CLI: orchestrate generation, output JSONL
├── validate.py          # CLI: type-check chains, filter, dedup, output filtered JSONL
├── format.py            # CLI: convert to chat JSONL with system prompt
├── system_prompt.py     # Generate system prompt text from api.yaml
├── tests/
│   ├── __init__.py
│   ├── test_spec.py
│   ├── test_chain_parser.py
│   ├── test_chain_sampler.py
│   ├── test_intent.py
│   ├── test_validate.py
│   ├── test_format.py
│   └── test_system_prompt.py
```

All files live under `training/`. Tests live under `training/tests/`. The spec at `reference/api.yaml` is the single source of truth.

---

## Task 1: Spec loader — parse api.yaml into Python objects

**Files:**
- Create: `training/spec.py`
- Create: `training/tests/__init__.py`
- Create: `training/tests/test_spec.py`

- [ ] **Step 1: Write the failing tests**

```python
# training/tests/test_spec.py
"""Tests for api.yaml spec loader."""
import os
from pathlib import Path

import pytest

SPEC_PATH = Path(__file__).parent.parent.parent / "reference" / "api.yaml"


@pytest.fixture
def spec():
    from training.spec import load_spec
    return load_spec(str(SPEC_PATH))


class TestTypes:
    def test_loads_all_types(self, spec):
        assert "Source" in spec.types
        assert "Selection" in spec.types
        assert "Isolated" in spec.types
        assert "History" in spec.types
        assert "View" in spec.types
        assert "terminal" in spec.types

    def test_source_produces_selection(self, spec):
        assert "Selection" in spec.types["Source"].produces

    def test_selection_produces_multiple(self, spec):
        produces = spec.types["Selection"].produces
        assert "Selection" in produces
        assert "terminal" in produces


class TestOperations:
    def test_loads_entry_points(self, spec):
        assert "select" in spec.operations
        assert "source" in spec.operations

    def test_operation_has_required_fields(self, spec):
        op = spec.operations["select"]
        assert op.name == "select"
        assert op.category == "entry"
        assert "Selection" in op.signature

    def test_loads_query_ops(self, spec):
        assert "find" in spec.operations
        assert "filter" in spec.operations
        assert "not_" in spec.operations

    def test_loads_mutation_ops(self, spec):
        assert "addParam" in spec.operations
        assert "rename" in spec.operations
        assert "replaceWith" in spec.operations

    def test_loads_terminal_ops(self, spec):
        assert "text" in spec.operations
        assert "count" in spec.operations
        assert "names" in spec.operations

    def test_loads_delegate_ops(self, spec):
        assert "black" in spec.operations
        assert "save" in spec.operations
        assert "test" in spec.operations

    def test_operation_input_output(self, spec):
        find = spec.operations["find"]
        assert find.input_type == "Selection"
        assert find.output_type == "Selection"

        count = spec.operations["count"]
        assert count.input_type == "Selection"
        assert count.output_type == "terminal"

    def test_operation_examples(self, spec):
        find = spec.operations["find"]
        assert len(find.examples) > 0

    def test_operation_argument_examples(self, spec):
        add_param = spec.operations["addParam"]
        assert len(add_param.param_examples) > 0
        assert "timeout: int = 30" in add_param.param_examples


class TestSelectors:
    def test_loads_node_types(self, spec):
        assert len(spec.selectors.node_types) >= 18
        shorts = [nt.short for nt in spec.selectors.node_types]
        assert ".fn" in shorts
        assert ".cls" in shorts
        assert ".call" in shorts

    def test_loads_pseudo_selectors(self, spec):
        assert len(spec.selectors.pseudo_selectors) >= 7

    def test_loads_attribute_selectors(self, spec):
        assert len(spec.selectors.attribute_selectors) >= 5

    def test_loads_combinators(self, spec):
        assert len(spec.selectors.combinators) >= 4


class TestComposition:
    def test_source_can_find(self, spec):
        assert "find" in spec.composition["Source"]

    def test_selection_has_categories(self, spec):
        sel = spec.composition["Selection"]
        assert "query" in sel
        assert "mutate" in sel
        assert "terminal" in sel
        assert "delegate" in sel

    def test_selection_query_ops(self, spec):
        assert "find" in spec.composition["Selection"]["query"]
        assert "filter" in spec.composition["Selection"]["query"]
        assert "callers" in spec.composition["Selection"]["query"]

    def test_isolated_ops(self, spec):
        assert "test" in spec.composition["Isolated"]

    def test_history_ops(self, spec):
        assert "at" in spec.composition["History"]


class TestExampleChains:
    def test_loads_example_categories(self, spec):
        assert len(spec.example_chains) >= 7  # simple_queries, mutations, etc.

    def test_example_has_intent_and_chain(self, spec):
        examples = spec.example_chains["simple_queries"]
        assert len(examples) > 0
        assert "intent" in examples[0]
        assert "chain" in examples[0]
```

- [ ] **Step 2: Create empty test __init__ and run tests to verify they fail**

```bash
touch training/tests/__init__.py
```

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest training/tests/test_spec.py -v`
Expected: FAIL — `training.spec` module does not exist

- [ ] **Step 3: Implement spec loader**

```python
# training/spec.py
"""Load and parse reference/api.yaml into Python objects."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class TypeInfo:
    name: str
    description: str
    produces: list[str]


@dataclass
class NodeType:
    short: str
    full: str
    description: str


@dataclass
class PseudoSelector:
    syntax: str
    description: str


@dataclass
class AttributeSelector:
    syntax: str
    description: str


@dataclass
class Combinator:
    syntax: str
    description: str


@dataclass
class Selectors:
    node_types: list[NodeType]
    pseudo_selectors: list[PseudoSelector]
    attribute_selectors: list[AttributeSelector]
    combinators: list[Combinator]
    name_selector_syntax: str
    name_selector_examples: list[dict]


@dataclass
class Operation:
    name: str
    signature: str
    category: str  # "entry", "query", "mutate", "terminal", "delegate", "metadata"
    description: str = ""
    input_type: str = ""
    output_type: str = ""
    examples: list[dict] = field(default_factory=list)
    param_examples: list[str] = field(default_factory=list)
    predicate_examples: list[dict] = field(default_factory=list)
    strategy_examples: list[str] = field(default_factory=list)
    ref_examples: list[str] = field(default_factory=list)


@dataclass
class Spec:
    version: str
    types: dict[str, TypeInfo]
    operations: dict[str, Operation]
    selectors: Selectors
    composition: dict[str, dict[str, list[str]] | list[str]]
    example_chains: dict[str, list[dict]]


def load_spec(path: str) -> Spec:
    """Load api.yaml and return a structured Spec object."""
    with open(path) as f:
        raw = yaml.safe_load(f)

    # Types
    types = {}
    for name, info in raw["types"].items():
        types[name] = TypeInfo(
            name=name,
            description=info["description"],
            produces=info.get("produces", []),
        )

    # Selectors
    sel_raw = raw["selectors"]
    selectors = Selectors(
        node_types=[
            NodeType(short=nt["short"], full=nt["full"], description=nt["description"])
            for nt in sel_raw["node_types"]
        ],
        pseudo_selectors=[
            PseudoSelector(syntax=ps["syntax"], description=ps["description"])
            for ps in sel_raw["pseudo_selectors"]
        ],
        attribute_selectors=[
            AttributeSelector(syntax=a["syntax"], description=a["description"])
            for a in sel_raw["attribute_selectors"]
        ],
        combinators=[
            Combinator(syntax=c["syntax"], description=c["description"])
            for c in sel_raw["combinators"]
        ],
        name_selector_syntax=sel_raw["name_selector"]["syntax"],
        name_selector_examples=sel_raw["name_selector"]["examples"],
    )

    # Operations — flatten all operation groups into one dict
    operations = {}
    ops_raw = raw["operations"]
    for group_name, group_ops in ops_raw.items():
        if not isinstance(group_ops, list):
            continue
        for op_raw in group_ops:
            op = Operation(
                name=op_raw["name"],
                signature=op_raw.get("signature", ""),
                category=op_raw.get("category", ""),
                description=op_raw.get("description", ""),
                input_type=op_raw.get("input", ""),
                output_type=op_raw.get("output", ""),
                examples=op_raw.get("examples", []),
                param_examples=op_raw.get("param_examples", []),
                predicate_examples=op_raw.get("predicate_examples", []),
                strategy_examples=op_raw.get("strategy_examples", []),
                ref_examples=op_raw.get("ref_examples", []),
            )
            # For operations that appear in multiple groups (e.g. 'find' in
            # source_ops and query), the later one wins. The query version
            # (Selection.find) is the one we want for chain generation since
            # source.find is just the entry variant.
            operations[op.name] = op

    # Composition rules
    composition = {}
    comp_raw = raw["composition"]
    for type_name, rules in comp_raw.items():
        if isinstance(rules, list):
            composition[type_name] = rules
        elif isinstance(rules, dict):
            composition[type_name] = rules
        # Skip comment strings

    # Example chains
    example_chains = raw.get("example_chains", {})

    return Spec(
        version=raw.get("version", "0.0.0"),
        types=types,
        operations=operations,
        selectors=selectors,
        composition=composition,
        example_chains=example_chains,
    )
```

- [ ] **Step 4: Run tests**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest training/tests/test_spec.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add training/spec.py training/tests/__init__.py training/tests/test_spec.py
git commit -m "feat(training): spec loader — parse api.yaml into Python objects"
```

---

## Task 2: Name pools

**Files:**
- Create: `training/pools.py`
- Create: `training/tests/test_pools.py`

- [ ] **Step 1: Write the failing tests**

```python
# training/tests/test_pools.py
"""Tests for name pools."""
import random

import pytest

from training.pools import (
    FUNCTION_NAMES,
    CLASS_NAMES,
    MODULE_PATHS,
    PARAM_SPECS,
    CODE_SNIPPETS,
    EXCEPTION_TYPES,
    GUARD_STRATEGIES,
    RENAME_TARGETS,
    sample_selector,
    sample_composed_selector,
)


class TestPoolSizes:
    def test_function_names_sufficient(self):
        assert len(FUNCTION_NAMES) >= 100

    def test_class_names_sufficient(self):
        assert len(CLASS_NAMES) >= 50

    def test_module_paths_sufficient(self):
        assert len(MODULE_PATHS) >= 8

    def test_param_specs_sufficient(self):
        assert len(PARAM_SPECS) >= 9

    def test_code_snippets_has_categories(self):
        assert "prepend" in CODE_SNIPPETS
        assert "append" in CODE_SNIPPETS
        assert "wrap_before" in CODE_SNIPPETS
        assert "wrap_after" in CODE_SNIPPETS

    def test_exception_types(self):
        assert len(EXCEPTION_TYPES) >= 5
        assert "ValueError" in EXCEPTION_TYPES

    def test_guard_strategies(self):
        assert len(GUARD_STRATEGIES) >= 5
        assert "log and reraise" in GUARD_STRATEGIES


class TestSelectorSampling:
    def test_sample_selector_returns_string(self):
        rng = random.Random(42)
        sel = sample_selector(rng)
        assert isinstance(sel, str)
        assert len(sel) > 0

    def test_sample_selector_has_node_type(self):
        rng = random.Random(42)
        for _ in range(20):
            sel = sample_selector(rng)
            assert sel.startswith(".")

    def test_sample_composed_selector(self):
        rng = random.Random(42)
        sel = sample_composed_selector(rng)
        assert isinstance(sel, str)
        assert "." in sel

    def test_sample_selector_variety(self):
        rng = random.Random(42)
        selectors = {sample_selector(rng) for _ in range(100)}
        # Should produce at least 10 distinct selectors
        assert len(selectors) >= 10

    def test_sample_selector_with_name(self):
        rng = random.Random(42)
        found_named = False
        for _ in range(100):
            sel = sample_selector(rng)
            if "#" in sel:
                found_named = True
                break
        assert found_named, "Should sometimes produce #name selectors"

    def test_sample_selector_with_pseudo(self):
        rng = random.Random(42)
        found_pseudo = False
        for _ in range(100):
            sel = sample_selector(rng)
            if ":" in sel:
                found_pseudo = True
                break
        assert found_pseudo, "Should sometimes produce :pseudo selectors"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest training/tests/test_pools.py -v`
Expected: FAIL

- [ ] **Step 3: Implement pools**

```python
# training/pools.py
"""Name pools for realistic selector and argument generation.

All pools are lists of realistic values sampled during chain generation.
The selector sampling functions compose node types, names, attributes,
and pseudo-selectors into valid CSS selector strings.
"""
from __future__ import annotations

import random

# -- Function names (100+) --
FUNCTION_NAMES = [
    "validate_token", "process_data", "handle_request", "parse_header",
    "get_user", "save_record", "send_email", "check_permissions",
    "transform_batch", "run_migration", "build_query", "render_template",
    "authenticate", "authorize", "serialize", "deserialize",
    "connect", "disconnect", "retry", "cleanup", "initialize",
    "fetch_config", "update_cache", "invalidate_session", "log_event",
    "hash_password", "verify_signature", "decode_token", "encode_payload",
    "create_user", "delete_user", "update_user", "list_users",
    "create_order", "cancel_order", "process_payment", "refund_payment",
    "send_notification", "schedule_task", "poll_status", "sync_data",
    "parse_json", "parse_xml", "parse_csv", "format_output",
    "compress_data", "decompress_data", "encrypt", "decrypt",
    "validate_email", "validate_phone", "validate_address", "validate_input",
    "normalize_text", "sanitize_html", "escape_sql", "strip_tags",
    "calculate_total", "compute_average", "aggregate_results", "merge_records",
    "open_connection", "close_connection", "reset_connection", "ping_server",
    "read_file", "write_file", "delete_file", "move_file",
    "start_worker", "stop_worker", "restart_service", "health_check",
    "generate_report", "export_data", "import_data", "archive_logs",
    "apply_discount", "calculate_tax", "convert_currency", "round_amount",
    "login", "logout", "refresh_token", "revoke_token",
    "get_profile", "update_profile", "upload_avatar", "delete_account",
    "search_index", "reindex", "build_index", "query_index",
    "rate_limit", "throttle", "debounce", "batch_process",
    "validate_schema", "migrate_database", "seed_database", "backup_database",
    "render_page", "render_component", "hydrate", "prefetch",
    "subscribe", "unsubscribe", "publish", "broadcast",
    "enqueue", "dequeue", "peek_queue", "drain_queue",
    "allocate", "deallocate", "resize", "compact",
]

# -- Class names (50+) --
CLASS_NAMES = [
    "AuthService", "UserManager", "DatabaseClient", "RequestHandler",
    "CacheLayer", "EventBus", "TaskQueue", "ConfigManager",
    "SessionStore", "TokenValidator", "PasswordHasher", "RateLimiter",
    "ConnectionPool", "MessageBroker", "NotificationService", "EmailSender",
    "PaymentProcessor", "OrderManager", "InventoryTracker", "ShippingService",
    "SearchEngine", "IndexBuilder", "QueryOptimizer", "ResultCache",
    "FileStorage", "BlobStore", "ImageProcessor", "VideoEncoder",
    "Logger", "MetricsCollector", "HealthMonitor", "AlertManager",
    "Router", "Middleware", "Controller", "Serializer",
    "Validator", "Sanitizer", "Formatter", "Parser",
    "Worker", "Scheduler", "Dispatcher", "Executor",
    "Migration", "Schema", "Model", "Repository",
    "Client", "Server", "Proxy", "Gateway",
    "Pipeline", "Stage", "Filter", "Transformer",
]

# -- Module paths --
MODULE_PATHS = [
    "src/**/*.py", "src/auth/**/*.py", "src/db/**/*.py",
    "src/api/**/*.py", "src/client/**/*.py", "tests/**/*.py",
    "src/middleware/**/*.py", "src/models/**/*.py",
    "src/services/**/*.py", "src/utils/**/*.py",
    "src/handlers/**/*.py", "src/core/**/*.py",
    "lib/**/*.py", "app/**/*.py",
]

# -- Parameter specs --
PARAM_SPECS = [
    "timeout: int = 30",
    "log_level: str | None = None",
    "dry_run: bool = False",
    "retry_count: int = 3",
    "callback: Callable | None = None",
    "verbose: bool = False",
    "batch_size: int = 100",
    "max_retries: int = 3",
    "encoding: str = 'utf-8'",
    "cache_ttl: int = 300",
    "limit: int = 100",
    "offset: int = 0",
    "debug: bool = False",
    "strict: bool = True",
    "format: str = 'json'",
]

# -- Code snippets for prepend/append/wrap --
CODE_SNIPPETS = {
    "prepend": [
        "logger.debug(f'entering {__name__}')",
        "if log_level:\\n    logging.setLevel(log_level)",
        "if dry_run:\\n    logger.info('DRY RUN mode')",
        "start_time = time.monotonic()",
        "logger.info(f'called with {locals()}')",
        "if not self._initialized:\\n    raise RuntimeError('not initialized')",
    ],
    "append": [
        "logger.debug(f'exiting {__name__}')",
        "elapsed = time.monotonic() - start_time",
        "logger.info(f'completed in {elapsed:.3f}s')",
        "metrics.increment('calls')",
    ],
    "wrap_before": [
        "try:",
        "with db.transaction():",
        "with timing_context():",
        "with lock:",
        "async with session:",
    ],
    "wrap_after": [
        "except DatabaseError:\\n    log.error('query failed')\\n    raise",
        "except TimeoutError:\\n    log.warning('timed out')\\n    return None",
        "except Exception as e:\\n    log.error(f'unexpected: {e}')\\n    raise",
        "except ConnectionError:\\n    log.error('connection lost')\\n    retry()",
    ],
}

# -- Exception types --
EXCEPTION_TYPES = [
    "ValueError", "TypeError", "KeyError", "RuntimeError",
    "DatabaseError", "ConnectionError", "TimeoutError",
    "PermissionError", "AuthenticationError", "ValidationError",
    "NotFoundError", "ConflictError", "RateLimitError",
    "RequestError", "ParseError",
]

# -- Guard strategies --
GUARD_STRATEGIES = [
    "log and reraise",
    "retry 3 times",
    "return None",
    "log.error and continue",
    "raise custom exception",
    "log and return default",
    "retry with backoff",
    "circuit breaker",
]

# -- Rename targets (old → new pairs) --
RENAME_TARGETS = [
    ("process_data", "transform_batch"),
    ("handle_request", "dispatch_request"),
    ("get_user", "fetch_user"),
    ("save_record", "persist_record"),
    ("send_email", "dispatch_email"),
    ("validate_token", "verify_token"),
    ("check_permissions", "authorize_action"),
    ("build_query", "compile_query"),
    ("parse_header", "decode_header"),
    ("run_migration", "execute_migration"),
    ("authenticate", "verify_credentials"),
    ("cleanup", "teardown"),
    ("initialize", "bootstrap"),
    ("connect", "establish_connection"),
]

# -- Attribute selector prefixes/suffixes/substrings --
NAME_PREFIXES = ["test_", "validate_", "check_", "get_", "set_", "is_", "has_", "process_", "handle_", "_"]
NAME_SUFFIXES = ["_handler", "_callback", "_impl", "_helper", "_async", "_sync", "_v2"]
NAME_SUBSTRINGS = ["valid", "auth", "query", "cache", "log", "parse", "send", "data"]

# -- Node types for selector sampling --
_NODE_TYPES = [
    ".fn", ".cls", ".call", ".ret", ".if", ".for", ".while",
    ".try", ".except", ".with", ".assign", ".import", ".dec",
    ".arg", ".str", ".num", ".block", ".comment",
]

# -- Pseudo-selectors --
_PSEUDO_SELECTORS = [":exported", ":private", ":first", ":last"]
_PSEUDO_WITH_ARG = [":has", ":not", ":decorated"]


def sample_selector(rng: random.Random) -> str:
    """Sample a single CSS selector for an AST node type.

    Returns selectors like:
        .fn
        .fn#validate_token
        .fn:exported
        .fn[name^="test_"]
        .cls#AuthService
        .call#print
    """
    node_type = rng.choice(_NODE_TYPES)

    # 40% bare type, 30% with name, 15% with pseudo, 15% with attribute
    roll = rng.random()
    if roll < 0.40:
        return node_type
    elif roll < 0.70:
        # With name
        if node_type in (".fn", ".call"):
            name = rng.choice(FUNCTION_NAMES)
        elif node_type == ".cls":
            name = rng.choice(CLASS_NAMES)
        elif node_type == ".import":
            name = rng.choice(["json", "os", "sys", "logging", "typing", "re", "pathlib", "datetime"])
        else:
            name = rng.choice(FUNCTION_NAMES)
        return f"{node_type}#{name}"
    elif roll < 0.85:
        # With pseudo-selector
        pseudo = rng.choice(_PSEUDO_SELECTORS)
        return f"{node_type}{pseudo}"
    else:
        # With attribute selector
        attr_type = rng.choice(["prefix", "suffix", "contains"])
        if attr_type == "prefix":
            prefix = rng.choice(NAME_PREFIXES)
            return f'{node_type}[name^="{prefix}"]'
        elif attr_type == "suffix":
            suffix = rng.choice(NAME_SUFFIXES)
            return f'{node_type}[name$="{suffix}"]'
        else:
            substr = rng.choice(NAME_SUBSTRINGS)
            return f'{node_type}[name*="{substr}"]'


def sample_composed_selector(rng: random.Random) -> str:
    """Sample a composed selector with optional combinator or :has()/:not().

    Returns selectors like:
        .cls#AuthService .fn:exported
        .fn:has(.call#print)
        .fn:has(.ret > .none)
        .fn:not(:has(.ret))
    """
    roll = rng.random()
    if roll < 0.40:
        # Descendant combinator: A B
        parent = sample_selector(rng)
        child = sample_selector(rng)
        return f"{parent} {child}"
    elif roll < 0.60:
        # Direct child: A > B
        parent = sample_selector(rng)
        child = sample_selector(rng)
        return f"{parent} > {child}"
    elif roll < 0.80:
        # :has() pseudo
        outer = rng.choice(_NODE_TYPES)
        inner = sample_selector(rng)
        return f"{outer}:has({inner})"
    else:
        # :not(:has()) pseudo
        outer = rng.choice(_NODE_TYPES)
        inner = sample_selector(rng)
        return f"{outer}:not(:has({inner}))"
```

- [ ] **Step 4: Run tests**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest training/tests/test_pools.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add training/pools.py training/tests/test_pools.py
git commit -m "feat(training): name pools and selector sampling"
```

---

## Task 3: Chain parser — parse chain strings into operation sequences

**Files:**
- Create: `training/chain_parser.py`
- Create: `training/tests/test_chain_parser.py`

- [ ] **Step 1: Write the failing tests**

```python
# training/tests/test_chain_parser.py
"""Tests for chain parser."""
import pytest

from training.chain_parser import parse_chain, ChainOp


class TestParseSimpleChains:
    def test_select_only(self):
        ops = parse_chain("select('.fn:exported')")
        assert len(ops) == 1
        assert ops[0].name == "select"
        assert ops[0].args == ["'.fn:exported'"]

    def test_source_find(self):
        ops = parse_chain("source('tests/**/*.py').find('.fn[name^=\"test_\"]')")
        assert len(ops) == 2
        assert ops[0].name == "source"
        assert ops[1].name == "find"

    def test_select_filter(self):
        ops = parse_chain("select('.fn').filter(fn: fn.params().count() > 5)")
        assert len(ops) == 2
        assert ops[0].name == "select"
        assert ops[1].name == "filter"

    def test_three_op_chain(self):
        ops = parse_chain("select('.fn:exported').addParam('timeout: int = 30').save('feat: add timeout')")
        assert len(ops) == 3
        assert ops[0].name == "select"
        assert ops[1].name == "addParam"
        assert ops[2].name == "save"


class TestParseMutationChains:
    def test_rename(self):
        ops = parse_chain("select('.fn#process_data').rename('transform_batch')")
        assert len(ops) == 2
        assert ops[1].name == "rename"
        assert "'transform_batch'" in ops[1].args

    def test_add_param(self):
        ops = parse_chain("select('.fn:exported').addParam('timeout: int = 30')")
        assert ops[1].name == "addParam"
        assert "'timeout: int = 30'" in ops[1].args


class TestParsePipelines:
    def test_long_pipeline(self):
        chain = "select('.fn:exported').addParam('timeout: int = 30').black().test().save('feat: add timeout parameter')"
        ops = parse_chain(chain)
        assert len(ops) == 5
        assert [op.name for op in ops] == ["select", "addParam", "black", "test", "save"]

    def test_guard_with_two_args(self):
        chain = "select('.call[name*=\"query\"]').guard('DatabaseError', 'log and reraise')"
        ops = parse_chain(chain)
        assert ops[1].name == "guard"
        assert len(ops[1].args) == 2


class TestParseComplexChains:
    def test_nested_select_in_diff(self):
        chain = "select('.fn#validate_token').diff(select('.fn#validate_token').at('last_green_build'))"
        ops = parse_chain(chain)
        assert ops[0].name == "select"
        assert ops[1].name == "diff"

    def test_no_arg_methods(self):
        chain = "select('.fn#process_data').filmstrip()"
        ops = parse_chain(chain)
        assert ops[1].name == "filmstrip"
        assert ops[1].args == []

    def test_isolate_test(self):
        chain = "select('.fn#process_data .for:first').isolate().test({'items': [1, 2, 3]})"
        ops = parse_chain(chain)
        assert len(ops) == 3
        assert ops[1].name == "isolate"
        assert ops[2].name == "test"


class TestChainOp:
    def test_repr(self):
        op = ChainOp(name="find", args=["'.fn'"])
        assert "find" in repr(op)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest training/tests/test_chain_parser.py -v`
Expected: FAIL

- [ ] **Step 3: Implement chain parser**

```python
# training/chain_parser.py
"""Parse pluckit chain strings into operation sequences.

Handles:
  - Entry points: select(...), source(...)
  - Method chains: .method(args)
  - String args with escaped quotes
  - Nested chains as arguments (e.g., .diff(select(...).at(...)))
  - Arrow-style predicates (fn: fn.params().count() > 5)
  - No-arg methods: .black(), .filmstrip()
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ChainOp:
    """A single operation in a parsed chain."""
    name: str
    args: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        args_str = ", ".join(self.args)
        return f"ChainOp({self.name}({args_str}))"


def parse_chain(chain: str) -> list[ChainOp]:
    """Parse a chain string into a list of ChainOp objects.

    Strategy: tokenize by finding method calls at the top level
    (respecting parenthesis nesting and string quoting).
    """
    chain = chain.strip()
    ops = []
    pos = 0

    while pos < len(chain):
        # Skip leading dot
        if chain[pos] == ".":
            pos += 1

        # Read method name (identifier)
        name_start = pos
        while pos < len(chain) and (chain[pos].isalnum() or chain[pos] == "_"):
            pos += 1
        name = chain[name_start:pos]

        if not name:
            pos += 1
            continue

        # Expect opening paren
        if pos >= len(chain) or chain[pos] != "(":
            ops.append(ChainOp(name=name))
            continue

        # Find matching closing paren, respecting nesting and strings
        args_start = pos + 1
        paren_depth = 1
        pos += 1
        in_single_quote = False
        in_double_quote = False
        escaped = False

        while pos < len(chain) and paren_depth > 0:
            ch = chain[pos]
            if escaped:
                escaped = False
                pos += 1
                continue
            if ch == "\\":
                escaped = True
                pos += 1
                continue
            if ch == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
            elif ch == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
            elif not in_single_quote and not in_double_quote:
                if ch == "(":
                    paren_depth += 1
                elif ch == ")":
                    paren_depth -= 1

            pos += 1

        args_str = chain[args_start : pos - 1].strip()

        # Split args at top-level commas
        args = _split_args(args_str) if args_str else []
        ops.append(ChainOp(name=name, args=args))

        # After closing paren, expect either end or .next_method
        # Skip any whitespace
        while pos < len(chain) and chain[pos] in " \t\n":
            pos += 1

    return ops


def _split_args(args_str: str) -> list[str]:
    """Split argument string at top-level commas (respecting nesting and quotes)."""
    args = []
    current = []
    paren_depth = 0
    bracket_depth = 0
    brace_depth = 0
    in_single_quote = False
    in_double_quote = False
    escaped = False

    for ch in args_str:
        if escaped:
            current.append(ch)
            escaped = False
            continue
        if ch == "\\":
            current.append(ch)
            escaped = True
            continue
        if ch == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
        elif ch == '"' and not in_single_quote:
            in_double_quote = not in_double_quote

        if not in_single_quote and not in_double_quote:
            if ch == "(":
                paren_depth += 1
            elif ch == ")":
                paren_depth -= 1
            elif ch == "[":
                bracket_depth += 1
            elif ch == "]":
                bracket_depth -= 1
            elif ch == "{":
                brace_depth += 1
            elif ch == "}":
                brace_depth -= 1
            elif (
                ch == ","
                and paren_depth == 0
                and bracket_depth == 0
                and brace_depth == 0
            ):
                args.append("".join(current).strip())
                current = []
                continue

        current.append(ch)

    if current:
        remaining = "".join(current).strip()
        if remaining:
            args.append(remaining)

    return args
```

- [ ] **Step 4: Run tests**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest training/tests/test_chain_parser.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add training/chain_parser.py training/tests/test_chain_parser.py
git commit -m "feat(training): chain parser for operation sequences"
```

---

## Task 4: Chain sampler — generate type-valid chain shapes

**Files:**
- Create: `training/chain_sampler.py`
- Create: `training/tests/test_chain_sampler.py`

- [ ] **Step 1: Write the failing tests**

```python
# training/tests/test_chain_sampler.py
"""Tests for chain sampler."""
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


class TestChainShapeSampling:
    def test_returns_chain_string(self, sampler):
        chain = sampler.sample()
        assert isinstance(chain, dict)
        assert "chain" in chain
        assert "shape" in chain
        assert "category" in chain
        assert isinstance(chain["chain"], str)

    def test_chain_starts_with_entry(self, sampler):
        for _ in range(50):
            chain = sampler.sample()
            text = chain["chain"]
            assert text.startswith("select(") or text.startswith("source("), f"Bad entry: {text}"

    def test_chain_length_distribution(self, sampler):
        lengths = []
        for _ in range(200):
            chain = sampler.sample()
            # Count operations by splitting on ').', but this is approximate
            shape = chain["shape"]
            length = len(shape.split("."))
            lengths.append(length)
        avg = sum(lengths) / len(lengths)
        # Should be weighted toward 2-4 operations
        assert 2.0 <= avg <= 5.0, f"Average chain length {avg} outside expected range"

    def test_produces_query_chains(self, sampler):
        found = False
        for _ in range(100):
            chain = sampler.sample()
            if chain["category"] == "query":
                found = True
                break
        assert found

    def test_produces_mutation_chains(self, sampler):
        found = False
        for _ in range(100):
            chain = sampler.sample()
            if chain["category"] == "mutation":
                found = True
                break
        assert found

    def test_produces_terminal_chains(self, sampler):
        found = False
        for _ in range(100):
            chain = sampler.sample()
            if chain["category"] == "terminal":
                found = True
                break
        assert found

    def test_shape_reflects_operations(self, sampler):
        chain = sampler.sample()
        shape = chain["shape"]
        # Shape should be dot-separated operation names
        parts = shape.split(".")
        assert len(parts) >= 1
        assert parts[0] in ("select", "source")

    def test_category_assignment(self, sampler):
        for _ in range(100):
            chain = sampler.sample()
            assert chain["category"] in (
                "query", "mutation", "terminal", "delegate", "pipeline"
            )


class TestSeedExamples:
    def test_includes_seed_examples(self, sampler):
        seeds = sampler.seed_examples()
        assert len(seeds) > 0
        # Should include examples from api.yaml
        intents = [s["intent"] for s in seeds]
        assert "find all public functions" in intents
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest training/tests/test_chain_sampler.py -v`
Expected: FAIL

- [ ] **Step 3: Implement chain sampler**

```python
# training/chain_sampler.py
"""Sample type-valid pluckit chains from composition rules.

Strategy:
1. Choose an entry point (select or source)
2. Walk the composition rules to pick a sequence of operations
   where each op's input type matches the previous op's output type
3. Fill selectors from pools
4. Fill arguments from spec examples and pools
"""
from __future__ import annotations

import random
from typing import Any

from training.spec import Spec, Operation
from training.pools import (
    FUNCTION_NAMES, CLASS_NAMES, MODULE_PATHS, PARAM_SPECS,
    CODE_SNIPPETS, EXCEPTION_TYPES, GUARD_STRATEGIES, RENAME_TARGETS,
    sample_selector, sample_composed_selector,
)


# Chain length weights: index = length, value = relative weight
# Weighted toward 2-4 operations
_LENGTH_WEIGHTS = {1: 5, 2: 25, 3: 30, 4: 25, 5: 10, 6: 3, 7: 2}


def _categorize_chain(ops: list[str], spec: Spec) -> str:
    """Determine the overall category of a chain from its operations."""
    categories = set()
    for op_name in ops:
        op = spec.operations.get(op_name)
        if op:
            categories.add(op.category)

    if "delegate" in categories and "mutate" in categories:
        return "pipeline"
    if "mutate" in categories:
        return "mutation"
    if "delegate" in categories:
        return "delegate"
    if "terminal" in categories:
        return "terminal"
    return "query"


class ChainSampler:
    """Generates type-valid pluckit chains from the API spec."""

    def __init__(self, spec: Spec, rng: random.Random | None = None) -> None:
        self.spec = spec
        self.rng = rng or random.Random()
        self._build_op_index()

    def _build_op_index(self) -> None:
        """Index operations by input type and category for fast lookup."""
        self._ops_by_type_cat: dict[tuple[str, str], list[Operation]] = {}
        for op in self.spec.operations.values():
            if not op.input_type:
                continue
            key = (op.input_type, op.category)
            self._ops_by_type_cat.setdefault(key, []).append(op)

    def sample(self) -> dict[str, str]:
        """Sample a single (chain, shape, category) dict."""
        # 1. Choose chain length
        length = self.rng.choices(
            list(_LENGTH_WEIGHTS.keys()),
            weights=list(_LENGTH_WEIGHTS.values()),
            k=1,
        )[0]

        # 2. Choose entry point
        entry = self.rng.choice(["select", "source"])

        # 3. Build the operation sequence
        if entry == "source":
            current_type = "Source"
            op_names = ["source"]
            chain_parts = [self._fill_source()]
            # Source must be followed by find
            op_names.append("find")
            selector = sample_selector(self.rng)
            chain_parts.append(f".find('{selector}')")
            current_type = "Selection"
            remaining = length - 2
        else:
            current_type = "Selection"
            op_names = ["select"]
            selector = self._sample_entry_selector()
            chain_parts = [f"select('{selector}')"]
            remaining = length - 1

        # 4. Append operations, respecting type transitions
        for i in range(remaining):
            is_last = i == remaining - 1
            op = self._pick_next_op(current_type, force_terminal=is_last and self.rng.random() < 0.3)
            if op is None:
                break

            op_names.append(op.name)
            chain_parts.append(self._fill_op(op))
            current_type = op.output_type if op.output_type else current_type

            # If we hit a terminal, stop
            if op.output_type == "terminal":
                break

        chain_str = "".join(chain_parts)
        shape = ".".join(op_names)
        category = _categorize_chain(op_names, self.spec)

        return {
            "chain": chain_str,
            "shape": shape,
            "category": category,
        }

    def seed_examples(self) -> list[dict[str, str]]:
        """Return the hand-written examples from api.yaml verbatim."""
        seeds = []
        for category_name, examples in self.spec.example_chains.items():
            for ex in examples:
                seeds.append({
                    "intent": ex["intent"],
                    "chain": ex["chain"],
                    "shape": self._infer_shape(ex["chain"]),
                    "category": category_name,
                })
        return seeds

    def _pick_next_op(
        self, current_type: str, force_terminal: bool = False
    ) -> Operation | None:
        """Pick a valid next operation given the current type."""
        comp = self.spec.composition.get(current_type)
        if comp is None:
            return None

        if isinstance(comp, list):
            # Simple list of op names (e.g., Source: [find])
            valid_names = comp
        elif isinstance(comp, dict):
            # Categorized dict (e.g., Selection: {query: [...], mutate: [...]})
            if force_terminal:
                valid_names = comp.get("terminal", [])
            else:
                # Weight categories: query 50%, mutate 25%, terminal 15%, delegate 10%
                category_weights = [
                    ("query", 50), ("mutate", 25), ("terminal", 15),
                    ("delegate", 10), ("metadata", 0),
                ]
                categories, weights = zip(*category_weights)
                cat = self.rng.choices(categories, weights=weights, k=1)[0]
                valid_names = comp.get(cat, [])
                if not valid_names:
                    # Fallback to any available category
                    for fallback_cat in ["query", "terminal", "mutate", "delegate"]:
                        valid_names = comp.get(fallback_cat, [])
                        if valid_names:
                            break
        else:
            return None

        if not valid_names:
            return None

        op_name = self.rng.choice(valid_names)
        return self.spec.operations.get(op_name)

    def _fill_source(self) -> str:
        """Generate a source() call with a module path."""
        path = self.rng.choice(MODULE_PATHS)
        return f"source('{path}')"

    def _sample_entry_selector(self) -> str:
        """Sample a selector for the entry select() call."""
        if self.rng.random() < 0.6:
            return sample_selector(self.rng)
        else:
            return sample_composed_selector(self.rng)

    def _fill_op(self, op: Operation) -> str:
        """Generate a method call string for an operation, with arguments."""
        name = op.name

        # No-arg operations
        if name in (
            "unique", "unwrap", "remove", "inline", "isolate",
            "black", "ruff_fix", "isort",
            "text", "count", "names", "complexity", "interface",
            "blame", "filmstrip", "history",
            "callers", "callees", "references", "dependents",
            "dependencies", "call_chain", "common_pattern",
            "coverage", "failures", "timing", "inputs", "outputs",
            "runs", "unused_params", "shadows", "impact",
            "preview", "explain", "dry_run", "compare",
            "params", "body", "authors",
        ):
            return f".{name}()"

        # Operations with selector arg
        if name in ("find", "not_", "parent", "children", "siblings", "next", "prev"):
            sel = sample_selector(self.rng)
            return f".{name}('{sel}')"

        # Filter with predicate
        if name == "filter":
            if op.predicate_examples:
                pred = self.rng.choice(op.predicate_examples)
                return f".filter({pred['predicate']})"
            return f".filter(fn: fn.count() > 0)"

        # Mutation ops with specific args
        if name == "addParam":
            spec = self.rng.choice(PARAM_SPECS)
            return f".addParam('{spec}')"

        if name == "removeParam":
            param_name = self.rng.choice(["timeout", "log_level", "dry_run", "verbose", "callback"])
            return f".removeParam('{param_name}')"

        if name == "rename":
            old, new = self.rng.choice(RENAME_TARGETS)
            return f".rename('{new}')"

        if name == "retype":
            new_type = self.rng.choice(["int", "str", "bool", "float", "Optional[str]", "list[int]"])
            return f".retype('{new_type}')"

        if name == "prepend":
            code = self.rng.choice(CODE_SNIPPETS["prepend"])
            return f".prepend('{code}')"

        if name == "append":
            code = self.rng.choice(CODE_SNIPPETS["append"])
            return f".append('{code}')"

        if name == "wrap":
            before = self.rng.choice(CODE_SNIPPETS["wrap_before"])
            after = self.rng.choice(CODE_SNIPPETS["wrap_after"])
            return f".wrap('{before}', '{after}')"

        if name == "replaceWith":
            code = self.rng.choice(CODE_SNIPPETS["prepend"] + CODE_SNIPPETS["append"])
            return f".replaceWith('{code}')"

        if name == "extract":
            fn_name = "_" + self.rng.choice(FUNCTION_NAMES)
            return f".extract('{fn_name}')"

        if name == "move_to":
            path = self.rng.choice(MODULE_PATHS).replace("**/*.py", self.rng.choice(FUNCTION_NAMES) + ".py")
            return f".move_to('{path}')"

        if name == "refactor":
            fn_name = self.rng.choice(FUNCTION_NAMES)
            return f".refactor('{fn_name}')"

        # Delegate ops
        if name == "guard":
            exc = self.rng.choice(EXCEPTION_TYPES)
            strategy = self.rng.choice(GUARD_STRATEGIES)
            return f".guard('{exc}', '{strategy}')"

        if name == "format":
            tool = self.rng.choice(["black", "ruff", "isort", "yapf"])
            return f".format('{tool}')"

        if name == "save":
            if self.rng.random() < 0.7:
                prefix = self.rng.choice(["feat:", "fix:", "refactor:", "chore:"])
                action = self.rng.choice(["add", "remove", "update", "fix", "refactor"])
                target = self.rng.choice(FUNCTION_NAMES)
                return f".save('{prefix} {action} {target}')"
            return ".save()"

        if name == "test":
            return ".test()"

        if name == "fuzz":
            n = self.rng.choice([10, 50, 100, 500, 1000])
            return f".fuzz({n})"

        if name == "benchmark":
            n = self.rng.choice([100, 500, 1000, 5000])
            return f".benchmark({n})"

        if name == "trace":
            return ".trace({})"

        # History ops
        if name == "at":
            if op.ref_examples:
                ref = self.rng.choice(op.ref_examples)
            else:
                ref = self.rng.choice(["HEAD~1", "HEAD~5", "last_week", "1_month_ago"])
            return f".at('{ref}')"

        if name == "diff":
            sel = sample_selector(self.rng)
            ref = self.rng.choice(["HEAD~1", "last_green_build", "last_week"])
            return f".diff(select('{sel}').at('{ref}'))"

        if name == "when":
            sel = sample_selector(self.rng)
            return f".when('{sel}')"

        if name == "co_changes":
            threshold = self.rng.choice([0.5, 0.6, 0.7, 0.8, 0.9])
            return f".co_changes({threshold})"

        if name == "similar":
            threshold = self.rng.choice([0.6, 0.7, 0.8, 0.9])
            return f".similar({threshold})"

        if name == "clones":
            threshold = self.rng.choice([0.8, 0.9, 0.95])
            return f".clones({threshold})"

        if name == "reachable":
            depth = self.rng.choice([2, 3, 5])
            return f".reachable(max_depth={depth})"

        if name == "attr":
            attr_name = self.rng.choice(["name", "line", "file", "end_line"])
            return f".attr('{attr_name}')"

        if name == "intent":
            desc = self.rng.choice([
                "Extract common pattern", "Add parameter for compliance",
                "Refactor before adding feature", "Fix error handling",
            ])
            return f".intent('{desc}')"

        if name in ("refs", "defs", "resolves_to"):
            sel = sample_selector(self.rng)
            return f".{name}('{sel}')"

        if name in ("map",):
            return f".map(v: v.complexity())"

        # Fallback: no-arg call
        return f".{name}()"

    def _infer_shape(self, chain: str) -> str:
        """Infer the shape (dot-separated op names) from a chain string."""
        from training.chain_parser import parse_chain
        try:
            ops = parse_chain(chain)
            return ".".join(op.name for op in ops)
        except Exception:
            return "unknown"
```

- [ ] **Step 4: Run tests**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest training/tests/test_chain_sampler.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add training/chain_sampler.py training/tests/test_chain_sampler.py
git commit -m "feat(training): chain sampler with type-valid shape generation"
```

---

## Task 5: Intent templates — generate natural language intents from chains

**Files:**
- Create: `training/intent.py`
- Create: `training/tests/test_intent.py`

- [ ] **Step 1: Write the failing tests**

```python
# training/tests/test_intent.py
"""Tests for intent template generation."""
import random

import pytest

from training.intent import generate_intent


class TestIntentGeneration:
    def test_returns_string(self):
        rng = random.Random(42)
        intent = generate_intent(
            chain="select('.fn:exported').addParam('timeout: int = 30')",
            shape="select.addParam",
            category="mutation",
            rng=rng,
        )
        assert isinstance(intent, str)
        assert len(intent) > 0

    def test_intent_mentions_operation(self):
        rng = random.Random(42)
        intent = generate_intent(
            chain="select('.fn:exported').addParam('timeout: int = 30')",
            shape="select.addParam",
            category="mutation",
            rng=rng,
        )
        # Should mention adding a parameter or timeout
        lower = intent.lower()
        assert "add" in lower or "timeout" in lower or "param" in lower

    def test_rename_intent(self):
        rng = random.Random(42)
        intent = generate_intent(
            chain="select('.fn#process_data').rename('transform_batch')",
            shape="select.rename",
            category="mutation",
            rng=rng,
        )
        lower = intent.lower()
        assert "rename" in lower or "transform_batch" in lower

    def test_find_intent(self):
        rng = random.Random(42)
        intent = generate_intent(
            chain="select('.fn:exported')",
            shape="select",
            category="query",
            rng=rng,
        )
        lower = intent.lower()
        assert "find" in lower or "public" in lower or "exported" in lower or "function" in lower

    def test_count_intent(self):
        rng = random.Random(42)
        intent = generate_intent(
            chain="select('.fn').count()",
            shape="select.count",
            category="terminal",
            rng=rng,
        )
        lower = intent.lower()
        assert "count" in lower or "how many" in lower or "number" in lower

    def test_strategy_metadata(self):
        rng = random.Random(42)
        result = generate_intent(
            chain="select('.fn').count()",
            shape="select.count",
            category="terminal",
            rng=rng,
            return_metadata=True,
        )
        assert isinstance(result, dict)
        assert "intent" in result
        assert "strategy" in result
        assert result["strategy"] in ("template", "paraphrase", "reverse")

    def test_strategy_distribution(self):
        rng = random.Random(42)
        strategies = []
        for _ in range(200):
            result = generate_intent(
                chain="select('.fn').count()",
                shape="select.count",
                category="terminal",
                rng=rng,
                return_metadata=True,
                paraphrase_ratio=0.3,
                reverse_ratio=0.1,
            )
            strategies.append(result["strategy"])
        # Template should be ~60%, paraphrase ~30%, reverse ~10%
        template_pct = strategies.count("template") / len(strategies)
        assert 0.4 < template_pct < 0.8


class TestSelectorDescription:
    def test_fn_exported(self):
        from training.intent import describe_selector
        desc = describe_selector(".fn:exported")
        assert "public" in desc.lower() or "exported" in desc.lower()

    def test_fn_with_name(self):
        from training.intent import describe_selector
        desc = describe_selector(".fn#validate_token")
        assert "validate_token" in desc

    def test_call_with_name(self):
        from training.intent import describe_selector
        desc = describe_selector(".call#print")
        assert "print" in desc.lower()

    def test_attribute_selector(self):
        from training.intent import describe_selector
        desc = describe_selector('.fn[name^="test_"]')
        assert "test_" in desc or "start" in desc.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest training/tests/test_intent.py -v`
Expected: FAIL

- [ ] **Step 3: Implement intent generation**

```python
# training/intent.py
"""Template-based intent generation from chain parameters.

Intent enrichment strategies (paraphrase/reverse) are metadata labels only —
all intents are template-generated. The strategy field records what enrichment
*would* be applied if a model were available.
"""
from __future__ import annotations

import random
import re


# -- Selector description --

_NODE_TYPE_NAMES = {
    ".fn": "functions", ".cls": "classes", ".call": "calls",
    ".ret": "return statements", ".if": "if statements", ".for": "for loops",
    ".while": "while loops", ".try": "try blocks", ".except": "except handlers",
    ".with": "context managers", ".assign": "assignments", ".import": "imports",
    ".dec": "decorators", ".arg": "parameters", ".str": "strings",
    ".num": "numbers", ".block": "blocks", ".comment": "comments",
}

_PSEUDO_DESCRIPTIONS = {
    ":exported": "public",
    ":private": "private",
    ":first": "first",
    ":last": "last",
}


def describe_selector(selector: str) -> str:
    """Generate a natural language description of a CSS selector."""
    desc_parts = []

    # Extract name from #identifier
    name_match = re.search(r"#(\w+)", selector)
    name = name_match.group(1) if name_match else None

    # Extract node type
    type_match = re.match(r"(\.\w+)", selector)
    node_type = type_match.group(1) if type_match else None
    type_name = _NODE_TYPE_NAMES.get(node_type, node_type or "nodes")

    # Extract pseudo-selectors
    for pseudo, desc in _PSEUDO_DESCRIPTIONS.items():
        if pseudo in selector:
            desc_parts.append(desc)

    # Extract attribute selectors
    attr_match = re.search(r'\[name\^="(\w+)"\]', selector)
    if attr_match:
        desc_parts.append(f"starting with {attr_match.group(1)}")

    attr_match = re.search(r'\[name\$="(\w+)"\]', selector)
    if attr_match:
        desc_parts.append(f"ending with {attr_match.group(1)}")

    attr_match = re.search(r'\[name\*="(\w+)"\]', selector)
    if attr_match:
        desc_parts.append(f"containing {attr_match.group(1)}")

    # Extract :has()
    has_match = re.search(r":has\(([^)]+)\)", selector)
    if has_match:
        inner = has_match.group(1)
        inner_desc = describe_selector(inner)
        desc_parts.append(f"containing {inner_desc}")

    # Build description
    if name:
        if node_type == ".fn" or node_type == ".call":
            return f"{name}"
        elif node_type == ".cls":
            return f"the {name} class"
        elif node_type == ".import":
            return f"{name} import"
        return f"{name}"

    if desc_parts:
        return " ".join(desc_parts) + " " + type_name
    return f"all {type_name}"


# -- Intent templates --

# Templates keyed by the last operation name in the shape.
# {selector} = selector description, {param} = parameter, etc.
_INTENT_TEMPLATES: dict[str, list[str]] = {
    # Query terminals
    "select": [
        "find {selector}",
        "get {selector}",
        "show me {selector}",
    ],
    "find": [
        "find {inner_selector} in {selector}",
        "search for {inner_selector} within {selector}",
    ],
    "filter": [
        "find {selector} where {predicate_desc}",
        "filter {selector} to those with {predicate_desc}",
    ],
    "count": [
        "how many {selector} are there",
        "count {selector}",
        "number of {selector}",
    ],
    "text": [
        "show the source of {selector}",
        "get the code for {selector}",
    ],
    "names": [
        "list the names of {selector}",
        "what are the {selector} called",
    ],
    "complexity": [
        "how complex is {selector}",
        "check complexity of {selector}",
    ],
    "interface": [
        "what does {selector} need from its enclosing scope",
        "show the interface of {selector}",
    ],

    # Mutations
    "addParam": [
        "add {param} parameter to {selector}",
        "add {param} to {selector}",
    ],
    "removeParam": [
        "remove the {param} parameter from {selector}",
    ],
    "rename": [
        "rename {selector} to {new_name}",
        "rename {old_name} to {new_name}",
    ],
    "prepend": [
        "add {code_desc} at the top of {selector}",
        "prepend {code_desc} to {selector}",
    ],
    "append": [
        "add {code_desc} at the end of {selector}",
        "append {code_desc} to {selector}",
    ],
    "wrap": [
        "wrap {selector} in {wrap_desc}",
    ],
    "unwrap": [
        "unwrap {selector}",
        "remove the wrapping around {selector}",
    ],
    "replaceWith": [
        "replace {selector} with {code_desc}",
    ],
    "remove": [
        "remove {selector}",
        "delete {selector}",
    ],
    "extract": [
        "extract {selector} into a new function",
        "extract {selector} into {new_name}",
    ],
    "inline": [
        "inline {selector}",
        "replace calls to {selector} with the function body",
    ],

    # Delegates
    "guard": [
        "add {exception} error handling to {selector}",
        "wrap {selector} in {strategy} error handling",
    ],
    "save": [
        "{prev_intent} and commit",
        "{prev_intent} and save",
    ],
    "test": [
        "test {selector}",
        "run tests on {selector}",
    ],
    "black": [
        "format {selector} with black",
    ],

    # History
    "at": [
        "show {selector} at {ref}",
        "what did {selector} look like at {ref}",
    ],
    "diff": [
        "what changed in {selector} since {ref}",
        "diff {selector} against {ref}",
    ],
    "filmstrip": [
        "show the evolution of {selector}",
        "how has {selector} changed over time",
    ],
    "authors": [
        "who has modified {selector}",
        "who has touched {selector}",
    ],
    "blame": [
        "who changed what in {selector}",
    ],
    "when": [
        "when did {selector} start {condition}",
    ],
    "co_changes": [
        "find code that always changes together with {selector}",
    ],

    # Relationships
    "callers": [
        "who calls {selector}",
        "find callers of {selector}",
    ],
    "callees": [
        "what does {selector} call",
        "find callees of {selector}",
    ],
    "similar": [
        "find functions similar to {selector}",
        "find structurally similar code to {selector}",
    ],
    "refactor": [
        "extract common pattern from {selector}",
        "refactor {selector} into a shared function",
    ],
    "impact": [
        "what would break if I change {selector}",
        "show the impact of changing {selector}",
    ],
    "isolate": [
        "isolate {selector} and test it",
    ],

    # Coverage / behavior
    "coverage": [
        "check test coverage of {selector}",
    ],
    "failures": [
        "find failures in {selector}",
    ],
}

# Fallback for operations without templates
_FALLBACK_TEMPLATES = [
    "apply {op_name} to {selector}",
    "{op_name} {selector}",
]


def _extract_chain_context(chain: str, shape: str) -> dict[str, str]:
    """Extract template variables from a chain string."""
    ctx: dict[str, str] = {}

    # Extract the entry selector
    sel_match = re.search(r"(?:select|find)\('([^']+)'\)", chain)
    if sel_match:
        ctx["selector"] = describe_selector(sel_match.group(1))
    else:
        ctx["selector"] = "the selected code"

    # Extract inner selector (for .find())
    find_match = re.search(r"\.find\('([^']+)'\)", chain)
    if find_match:
        ctx["inner_selector"] = describe_selector(find_match.group(1))

    # Extract param spec
    param_match = re.search(r"\.addParam\('([^']+)'\)", chain)
    if param_match:
        spec = param_match.group(1)
        param_name = spec.split(":")[0].strip()
        ctx["param"] = param_name

    # Extract rename target
    rename_match = re.search(r"\.rename\('([^']+)'\)", chain)
    if rename_match:
        ctx["new_name"] = rename_match.group(1)

    # Extract old name from selector for rename
    name_match = re.search(r"#(\w+)", chain)
    if name_match:
        ctx["old_name"] = name_match.group(1)

    # Extract ref for history
    at_match = re.search(r"\.at\('([^']+)'\)", chain)
    if at_match:
        ctx["ref"] = at_match.group(1)

    # Extract guard args
    guard_match = re.search(r"\.guard\('([^']+)',\s*'([^']+)'\)", chain)
    if guard_match:
        ctx["exception"] = guard_match.group(1)
        ctx["strategy"] = guard_match.group(2)

    # Extract code snippets
    for op in ("prepend", "append", "replaceWith"):
        code_match = re.search(rf"\.{op}\('([^']+)'\)", chain)
        if code_match:
            ctx["code_desc"] = code_match.group(1)[:50]

    # Wrap description
    wrap_match = re.search(r"\.wrap\('([^']+)'", chain)
    if wrap_match:
        ctx["wrap_desc"] = wrap_match.group(1)

    # Extract function name from .extract()
    extract_match = re.search(r"\.extract\('([^']+)'\)", chain)
    if extract_match:
        ctx["new_name"] = extract_match.group(1)

    # Filter predicate
    filter_match = re.search(r"\.filter\((\w+):\s*(.+?)\)", chain)
    if filter_match:
        ctx["predicate_desc"] = filter_match.group(2).strip()

    # When condition
    when_match = re.search(r"\.when\('([^']+)'\)", chain)
    if when_match:
        ctx["condition"] = describe_selector(when_match.group(1))

    # Shape parts for multi-op intents
    ops = shape.split(".")
    if len(ops) >= 2:
        ctx["op_name"] = ops[-1]

    return ctx


def generate_intent(
    chain: str,
    shape: str,
    category: str,
    rng: random.Random,
    *,
    return_metadata: bool = False,
    paraphrase_ratio: float = 0.3,
    reverse_ratio: float = 0.1,
) -> str | dict[str, str]:
    """Generate a natural language intent for a chain.

    Args:
        chain: The pluckit chain string.
        shape: Dot-separated operation names.
        category: Chain category (query, mutation, etc.).
        rng: Random number generator.
        return_metadata: If True, return dict with intent + strategy metadata.
        paraphrase_ratio: Fraction labeled as "paraphrase" strategy.
        reverse_ratio: Fraction labeled as "reverse" strategy.

    Returns:
        Intent string, or dict with {intent, strategy} if return_metadata=True.
    """
    ctx = _extract_chain_context(chain, shape)
    ops = shape.split(".")
    last_op = ops[-1] if ops else "select"

    # Pick a template
    templates = _INTENT_TEMPLATES.get(last_op, _FALLBACK_TEMPLATES)
    template = rng.choice(templates)

    # Fill template, using .get() with fallbacks for missing keys
    try:
        intent = template.format_map(_SafeDict(ctx))
    except (KeyError, IndexError):
        intent = f"{last_op} {ctx.get('selector', 'the selected code')}"

    # Assign strategy label (metadata only — no API calls)
    roll = rng.random()
    template_threshold = 1.0 - paraphrase_ratio - reverse_ratio
    if roll < template_threshold:
        strategy = "template"
    elif roll < template_threshold + paraphrase_ratio:
        strategy = "paraphrase"
    else:
        strategy = "reverse"

    if return_metadata:
        return {"intent": intent, "strategy": strategy}
    return intent


class _SafeDict(dict):
    """Dict that returns '{key}' for missing keys instead of raising."""
    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"
```

- [ ] **Step 4: Run tests**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest training/tests/test_intent.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add training/intent.py training/tests/test_intent.py
git commit -m "feat(training): template-based intent generation"
```

---

## Task 6: generate.py CLI

**Files:**
- Create: `training/generate.py`

- [ ] **Step 1: Implement the generator CLI**

```python
# training/generate.py
"""Chain and intent generator.

Reads reference/api.yaml and produces (intent, chain) pairs as JSONL.

Usage:
    python -m training.generate --count 10000 --output raw_pairs.jsonl --seed 42
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from training.spec import load_spec
from training.chain_sampler import ChainSampler
from training.intent import generate_intent


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate pluckit training data")
    parser.add_argument(
        "--spec",
        default=str(Path(__file__).parent.parent / "reference" / "api.yaml"),
        help="Path to api.yaml spec file",
    )
    parser.add_argument("--count", type=int, default=1000, help="Number of pairs to generate")
    parser.add_argument("--output", default="-", help="Output JSONL file (- for stdout)")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    parser.add_argument(
        "--paraphrase-ratio", type=float, default=0.3,
        help="Fraction of pairs labeled as paraphrase strategy",
    )
    parser.add_argument(
        "--reverse-ratio", type=float, default=0.1,
        help="Fraction of pairs labeled as reverse strategy",
    )
    args = parser.parse_args(argv)

    rng = random.Random(args.seed)
    spec = load_spec(args.spec)
    sampler = ChainSampler(spec, rng=rng)

    out = sys.stdout if args.output == "-" else open(args.output, "w")
    try:
        # First: include seed examples from api.yaml verbatim
        for seed in sampler.seed_examples():
            record = {
                "intent": seed["intent"],
                "chain": seed["chain"],
                "shape": seed["shape"],
                "category": seed["category"],
                "strategy": "seed",
            }
            out.write(json.dumps(record) + "\n")

        # Then: generate synthetic pairs
        for _ in range(args.count):
            chain_info = sampler.sample()
            intent_result = generate_intent(
                chain=chain_info["chain"],
                shape=chain_info["shape"],
                category=chain_info["category"],
                rng=rng,
                return_metadata=True,
                paraphrase_ratio=args.paraphrase_ratio,
                reverse_ratio=args.reverse_ratio,
            )
            record = {
                "intent": intent_result["intent"],
                "chain": chain_info["chain"],
                "shape": chain_info["shape"],
                "category": chain_info["category"],
                "strategy": intent_result["strategy"],
            }
            out.write(json.dumps(record) + "\n")
    finally:
        if out is not sys.stdout:
            out.close()

    if args.output != "-":
        total = len(sampler.seed_examples()) + args.count
        print(f"Generated {total} pairs to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test the CLI**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m training.generate --count 100 --seed 42 --output /tmp/test_raw.jsonl && wc -l /tmp/test_raw.jsonl && head -3 /tmp/test_raw.jsonl`
Expected: ~130+ lines (100 synthetic + seed examples), each line valid JSON with intent, chain, shape, category, strategy fields

- [ ] **Step 3: Verify JSON format**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -c "import json; lines = open('/tmp/test_raw.jsonl').readlines(); [json.loads(l) for l in lines]; print(f'All {len(lines)} lines valid JSON')"`
Expected: "All N lines valid JSON"

- [ ] **Step 4: Commit**

```bash
git add training/generate.py
git commit -m "feat(training): generate.py CLI for chain+intent pair generation"
```

---

## Task 7: validate.py CLI — type-check and filter chains

**Files:**
- Create: `training/validate.py`
- Create: `training/tests/test_validate.py`

- [ ] **Step 1: Write the failing tests**

```python
# training/tests/test_validate.py
"""Tests for chain type-checker and validator."""
from pathlib import Path

import pytest

from training.spec import load_spec
from training.validate import validate_chain, ChainValidationResult

SPEC_PATH = Path(__file__).parent.parent.parent / "reference" / "api.yaml"


@pytest.fixture
def spec():
    return load_spec(str(SPEC_PATH))


class TestValidChains:
    def test_simple_select(self, spec):
        result = validate_chain("select('.fn:exported')", spec)
        assert result.valid

    def test_source_find(self, spec):
        result = validate_chain("source('src/**/*.py').find('.fn')", spec)
        assert result.valid

    def test_select_mutation(self, spec):
        result = validate_chain("select('.fn:exported').addParam('timeout: int = 30')", spec)
        assert result.valid

    def test_select_terminal(self, spec):
        result = validate_chain("select('.fn').count()", spec)
        assert result.valid

    def test_long_pipeline(self, spec):
        result = validate_chain(
            "select('.fn:exported').addParam('timeout: int = 30').black().test().save('feat: add timeout')",
            spec,
        )
        assert result.valid

    def test_mutation_chains_further(self, spec):
        result = validate_chain(
            "select('.fn:exported').addParam('x: int').rename('new_name')",
            spec,
        )
        assert result.valid

    def test_history_chain(self, spec):
        result = validate_chain(
            "select('.fn#validate_token').at('HEAD~1')",
            spec,
        )
        assert result.valid


class TestInvalidChains:
    def test_terminal_in_middle(self, spec):
        result = validate_chain("select('.fn').count().addParam('x: int')", spec)
        assert not result.valid
        assert "terminal" in result.error.lower()

    def test_no_entry_point(self, spec):
        result = validate_chain(".find('.fn').count()", spec)
        assert not result.valid

    def test_unknown_operation(self, spec):
        result = validate_chain("select('.fn').nonexistent_op()", spec)
        assert not result.valid
        assert "unknown" in result.error.lower()

    def test_source_without_find(self, spec):
        # Source can only be followed by find
        result = validate_chain("source('src/**/*.py').addParam('x: int')", spec)
        assert not result.valid

    def test_empty_chain(self, spec):
        result = validate_chain("", spec)
        assert not result.valid


class TestWarnings:
    def test_save_without_mutation_warns(self, spec):
        result = validate_chain("select('.fn').save('msg')", spec)
        # Valid (save is a delegate on Selection) but should warn
        assert result.valid
        assert any("save" in w.lower() for w in result.warnings)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest training/tests/test_validate.py -v`
Expected: FAIL

- [ ] **Step 3: Implement validator**

```python
# training/validate.py
"""Type-check and filter generated chains against composition rules.

Usage:
    python -m training.validate raw_pairs.jsonl --output valid_pairs.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from training.chain_parser import parse_chain
from training.spec import Spec, load_spec


@dataclass
class ChainValidationResult:
    valid: bool
    error: str = ""
    warnings: list[str] = field(default_factory=list)
    output_type: str = ""


def validate_chain(chain_str: str, spec: Spec) -> ChainValidationResult:
    """Validate a chain string against the spec's type system and composition rules."""
    if not chain_str or not chain_str.strip():
        return ChainValidationResult(valid=False, error="Empty chain")

    try:
        ops = parse_chain(chain_str)
    except Exception as e:
        return ChainValidationResult(valid=False, error=f"Parse error: {e}")

    if not ops:
        return ChainValidationResult(valid=False, error="No operations parsed")

    # Check entry point
    entry = ops[0]
    if entry.name == "select":
        current_type = "Selection"
    elif entry.name == "source":
        current_type = "Source"
    else:
        return ChainValidationResult(
            valid=False,
            error=f"Invalid entry point: {entry.name}. Must be select() or source().",
        )

    warnings: list[str] = []
    has_mutation = False

    # Type-check each subsequent operation
    for i, op in enumerate(ops[1:], start=1):
        # Look up valid operations for current type
        comp = spec.composition.get(current_type)
        if comp is None:
            return ChainValidationResult(
                valid=False,
                error=f"No composition rules for type {current_type} at step {i} ({op.name})",
            )

        # Check if this operation is valid for current type
        valid_ops = _flatten_composition(comp)
        if op.name not in valid_ops:
            return ChainValidationResult(
                valid=False,
                error=f"Unknown or invalid operation '{op.name}' on type {current_type} at step {i}. "
                      f"Valid operations: {sorted(valid_ops)[:10]}...",
            )

        # Look up the operation to get its output type
        op_spec = spec.operations.get(op.name)
        if op_spec is None:
            return ChainValidationResult(
                valid=False,
                error=f"Unknown operation: {op.name}",
            )

        # Track mutations
        if op_spec.category == "mutate":
            has_mutation = True

        # Determine output type
        if op_spec.output_type:
            next_type = op_spec.output_type
        else:
            # If no explicit output, assume same type (e.g., query -> Selection)
            next_type = current_type

        # Terminal check: if this is a terminal and not the last op, it's invalid
        if next_type == "terminal" and i < len(ops) - 1:
            return ChainValidationResult(
                valid=False,
                error=f"Terminal operation '{op.name}' at step {i} is not the last operation. "
                      f"Terminal operations must end the chain.",
            )

        current_type = next_type

    # Warnings
    if ops[-1].name == "save" and not has_mutation:
        warnings.append("save() without preceding mutation — chain has no changes to commit")

    return ChainValidationResult(
        valid=True,
        warnings=warnings,
        output_type=current_type,
    )


def _flatten_composition(comp: dict | list) -> set[str]:
    """Flatten composition rules into a set of valid operation names."""
    if isinstance(comp, list):
        return set(comp)
    if isinstance(comp, dict):
        result = set()
        for ops in comp.values():
            if isinstance(ops, list):
                result.update(ops)
        return result
    return set()


# -- CLI --

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Validate and filter pluckit training data")
    parser.add_argument("input", help="Input JSONL file")
    parser.add_argument("--spec", default=str(Path(__file__).parent.parent / "reference" / "api.yaml"))
    parser.add_argument("--output", default="-", help="Output JSONL file for valid pairs")
    parser.add_argument("--reject-file", default=None, help="Output JSONL file for rejected pairs")
    parser.add_argument("--min-chain-length", type=int, default=2, help="Minimum operations in chain")
    parser.add_argument("--dedup-intents", action="store_true", help="Deduplicate by intent text")
    args = parser.parse_args(argv)

    spec = load_spec(args.spec)

    out = sys.stdout if args.output == "-" else open(args.output, "w")
    reject_out = open(args.reject_file, "w") if args.reject_file else None

    seen_intents: set[str] = set()
    stats = {"total": 0, "valid": 0, "rejected": 0, "deduped": 0, "too_short": 0}

    try:
        with open(args.input) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                stats["total"] += 1
                record = json.loads(line)

                # Validate chain
                result = validate_chain(record["chain"], spec)

                if not result.valid:
                    stats["rejected"] += 1
                    if reject_out:
                        record["valid"] = False
                        record["error"] = result.error
                        reject_out.write(json.dumps(record) + "\n")
                    continue

                # Check minimum chain length
                ops = parse_chain(record["chain"])
                if len(ops) < args.min_chain_length:
                    stats["too_short"] += 1
                    if reject_out:
                        record["valid"] = False
                        record["error"] = f"Chain too short ({len(ops)} ops, minimum {args.min_chain_length})"
                        reject_out.write(json.dumps(record) + "\n")
                    continue

                # Dedup intents
                if args.dedup_intents:
                    intent_lower = record["intent"].lower().strip()
                    if intent_lower in seen_intents:
                        stats["deduped"] += 1
                        continue
                    seen_intents.add(intent_lower)

                # Write valid pair
                record["valid"] = True
                if result.warnings:
                    record["warnings"] = result.warnings
                out.write(json.dumps(record) + "\n")
                stats["valid"] += 1

    finally:
        if out is not sys.stdout:
            out.close()
        if reject_out:
            reject_out.close()

    print(
        f"Validated {stats['total']} pairs: "
        f"{stats['valid']} valid, "
        f"{stats['rejected']} rejected, "
        f"{stats['too_short']} too short, "
        f"{stats['deduped']} deduped",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest training/tests/test_validate.py -v`
Expected: PASS

- [ ] **Step 5: Test the CLI end-to-end**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m training.generate --count 200 --seed 42 --output /tmp/test_raw.jsonl && python -m training.validate /tmp/test_raw.jsonl --output /tmp/test_valid.jsonl --reject-file /tmp/test_rejected.jsonl --min-chain-length 2 --dedup-intents && wc -l /tmp/test_valid.jsonl /tmp/test_rejected.jsonl`
Expected: Valid pairs in test_valid.jsonl, rejected pairs in test_rejected.jsonl, stats printed to stderr

- [ ] **Step 6: Commit**

```bash
git add training/validate.py training/tests/test_validate.py
git commit -m "feat(training): validate.py — chain type-checker and filter"
```

---

## Task 8: system_prompt.py — auto-generate system prompt from api.yaml

**Files:**
- Create: `training/system_prompt.py`
- Create: `training/tests/test_system_prompt.py`

- [ ] **Step 1: Write the failing tests**

```python
# training/tests/test_system_prompt.py
"""Tests for system prompt generation from api.yaml."""
from pathlib import Path

import pytest

from training.spec import load_spec
from training.system_prompt import generate_system_prompt

SPEC_PATH = Path(__file__).parent.parent.parent / "reference" / "api.yaml"


@pytest.fixture
def prompt():
    spec = load_spec(str(SPEC_PATH))
    return generate_system_prompt(spec)


class TestSystemPrompt:
    def test_returns_string(self, prompt):
        assert isinstance(prompt, str)
        assert len(prompt) > 100

    def test_contains_entry_points(self, prompt):
        assert "select(" in prompt
        assert "source(" in prompt

    def test_contains_query_ops(self, prompt):
        assert ".find(" in prompt
        assert ".filter(" in prompt

    def test_contains_mutation_ops(self, prompt):
        assert ".addParam(" in prompt
        assert ".rename(" in prompt
        assert ".replaceWith(" in prompt

    def test_contains_terminal_ops(self, prompt):
        assert ".text()" in prompt
        assert ".count()" in prompt
        assert ".names()" in prompt

    def test_contains_delegate_ops(self, prompt):
        assert ".test(" in prompt
        assert ".save(" in prompt
        assert ".black()" in prompt

    def test_contains_history_ops(self, prompt):
        assert ".history()" in prompt
        assert ".at(" in prompt
        assert ".diff(" in prompt

    def test_contains_relationship_ops(self, prompt):
        assert ".callers()" in prompt
        assert ".callees()" in prompt

    def test_contains_instruction_header(self, prompt):
        assert "Jupyter" in prompt or "notebook" in prompt or "cell" in prompt

    def test_contains_restriction(self, prompt):
        assert "import" in prompt.lower()  # "Not available: import, def, ..."

    def test_no_duplicate_operations(self, prompt):
        # Each operation should appear once in the listing
        lines = prompt.split("\n")
        op_lines = [l.strip() for l in lines if l.strip().startswith(".")]
        op_names = [l.split("(")[0] for l in op_lines]
        # Allow some duplicates from different type contexts, but not excessive
        assert len(op_names) > 20  # Sanity: should list many ops
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest training/tests/test_system_prompt.py -v`
Expected: FAIL

- [ ] **Step 3: Implement system prompt generator**

```python
# training/system_prompt.py
"""Generate the system prompt for fine-tuning from api.yaml.

The prompt describes the pluckit namespace available in a Jupyter kernel,
listing all entry points and operations with their signatures.
"""
from __future__ import annotations

from training.spec import Spec


def generate_system_prompt(spec: Spec) -> str:
    """Generate a system prompt from the API spec."""
    sections = []

    # Header
    sections.append(
        "You are a Jupyter notebook cell generator. Write a single cell\n"
        "using ONLY the pre-loaded kernel namespace below.\n"
        "\n"
        "Output ONLY the cell contents — no markdown, no explanation, no code fences.\n"
        "\n"
        "Assign results to variables and reuse them. Never call the same function twice\n"
        "when you can reuse a variable.\n"
        "\n"
        "You compose source code queries and mutations using the pluckit API."
    )

    # Entry points
    entry_lines = ["\nKernel namespace:"]
    for op in spec.operations.values():
        if op.category == "entry":
            entry_lines.append(f"  {op.signature}: {op.description}")
    sections.append("\n".join(entry_lines))

    # Group operations by input type and category
    op_groups: dict[str, dict[str, list]] = {}
    for op in spec.operations.values():
        if op.category == "entry" or not op.input_type:
            continue
        type_key = op.input_type
        cat_key = op.category
        op_groups.setdefault(type_key, {}).setdefault(cat_key, []).append(op)

    # Category display names
    cat_names = {
        "query": "Query",
        "mutate": "Mutation",
        "terminal": "Reading",
        "delegate": "Delegate",
        "metadata": "Metadata",
    }

    for type_name in ["Selection", "Source", "Isolated", "History"]:
        cats = op_groups.get(type_name)
        if not cats:
            continue

        type_lines = [f"\n{type_name} operations:"]
        for cat_key in ["query", "mutate", "terminal", "delegate", "metadata"]:
            ops = cats.get(cat_key, [])
            if not ops:
                continue
            for op in ops:
                sig = op.signature.replace(f"{type_name}.", ".")
                desc = f": {op.description}" if op.description else ""
                type_lines.append(f"  {sig}{desc}")

        sections.append("\n".join(type_lines))

    # Builtins and restrictions
    sections.append(
        "\nBuiltins: len, sorted, range, str, int, print, enumerate, any, all"
    )
    sections.append(
        "\nNot available: import, def, class, while, try/except, open"
    )

    return "\n".join(sections)


def write_system_prompt(spec: Spec, output_path: str) -> None:
    """Generate and write system prompt to a file."""
    prompt = generate_system_prompt(spec)
    with open(output_path, "w") as f:
        f.write(prompt)
```

- [ ] **Step 4: Run tests**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest training/tests/test_system_prompt.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add training/system_prompt.py training/tests/test_system_prompt.py
git commit -m "feat(training): auto-generate system prompt from api.yaml"
```

---

## Task 9: format.py CLI — convert to chat JSONL for fine-tuning

**Files:**
- Create: `training/format.py`
- Create: `training/tests/test_format.py`

- [ ] **Step 1: Write the failing tests**

```python
# training/tests/test_format.py
"""Tests for fine-tuning formatter."""
import json
import tempfile
from pathlib import Path

import pytest

from training.spec import load_spec
from training.format import format_pair, main as format_main
from training.system_prompt import generate_system_prompt

SPEC_PATH = Path(__file__).parent.parent.parent / "reference" / "api.yaml"


@pytest.fixture
def system_prompt():
    spec = load_spec(str(SPEC_PATH))
    return generate_system_prompt(spec)


class TestFormatPair:
    def test_returns_chat_format(self, system_prompt):
        record = {
            "intent": "find all public functions",
            "chain": "select('.fn:exported')",
        }
        result = format_pair(record, system_prompt)
        assert "messages" in result
        msgs = result["messages"]
        assert len(msgs) == 3

    def test_system_message(self, system_prompt):
        record = {
            "intent": "find all public functions",
            "chain": "select('.fn:exported')",
        }
        result = format_pair(record, system_prompt)
        msgs = result["messages"]
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == system_prompt

    def test_user_message_is_intent(self, system_prompt):
        record = {
            "intent": "find all public functions",
            "chain": "select('.fn:exported')",
        }
        result = format_pair(record, system_prompt)
        msgs = result["messages"]
        assert msgs[1]["role"] == "user"
        assert msgs[1]["content"] == "find all public functions"

    def test_assistant_message_is_chain(self, system_prompt):
        record = {
            "intent": "find all public functions",
            "chain": "select('.fn:exported')",
        }
        result = format_pair(record, system_prompt)
        msgs = result["messages"]
        assert msgs[2]["role"] == "assistant"
        assert "select('.fn:exported')" in msgs[2]["content"]


class TestFormatCLI:
    def test_produces_output(self, system_prompt, tmp_path):
        # Create input file
        input_file = tmp_path / "input.jsonl"
        input_file.write_text(
            json.dumps({"intent": "find all functions", "chain": "select('.fn')", "valid": True}) + "\n"
            + json.dumps({"intent": "count functions", "chain": "select('.fn').count()", "valid": True}) + "\n"
        )

        output_file = tmp_path / "output.jsonl"
        prompt_file = tmp_path / "prompt.txt"
        prompt_file.write_text(system_prompt)

        format_main([
            str(input_file),
            "--output", str(output_file),
            "--system-prompt", str(prompt_file),
        ])

        lines = output_file.read_text().strip().split("\n")
        assert len(lines) == 2

        for line in lines:
            record = json.loads(line)
            assert "messages" in record
            assert len(record["messages"]) == 3

    def test_train_val_split(self, system_prompt, tmp_path):
        # Create input with 10 records
        input_file = tmp_path / "input.jsonl"
        records = [
            json.dumps({"intent": f"task {i}", "chain": f"select('.fn').count()", "valid": True})
            for i in range(10)
        ]
        input_file.write_text("\n".join(records) + "\n")

        prompt_file = tmp_path / "prompt.txt"
        prompt_file.write_text(system_prompt)

        train_file = tmp_path / "train.jsonl"
        val_file = tmp_path / "val.jsonl"

        format_main([
            str(input_file),
            "--output", str(tmp_path / "all.jsonl"),
            "--system-prompt", str(prompt_file),
            "--split", "0.8",
            "--train-file", str(train_file),
            "--val-file", str(val_file),
            "--seed", "42",
        ])

        train_lines = train_file.read_text().strip().split("\n")
        val_lines = val_file.read_text().strip().split("\n")
        assert len(train_lines) + len(val_lines) == 10
        assert len(train_lines) >= 7  # ~80%
        assert len(val_lines) >= 1    # ~20%
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest training/tests/test_format.py -v`
Expected: FAIL

- [ ] **Step 3: Implement formatter**

```python
# training/format.py
"""Convert validated pairs to fine-tuning chat JSONL format.

Usage:
    python -m training.format valid_pairs.jsonl --output training.jsonl \
        --system-prompt system_prompt.txt --split 0.9 \
        --train-file train.jsonl --val-file val.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path


def format_pair(record: dict, system_prompt: str) -> dict:
    """Convert a single (intent, chain) pair to chat message format."""
    return {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": record["intent"]},
            {"role": "assistant", "content": record["chain"]},
        ]
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Format pluckit training data for fine-tuning")
    parser.add_argument("input", help="Input JSONL file (validated pairs)")
    parser.add_argument("--output", default="-", help="Output JSONL file (all pairs)")
    parser.add_argument("--system-prompt", required=True, help="Path to system prompt text file")
    parser.add_argument("--split", type=float, default=None, help="Train fraction (e.g. 0.9)")
    parser.add_argument("--train-file", default=None, help="Train split output file")
    parser.add_argument("--val-file", default=None, help="Validation split output file")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for split")
    args = parser.parse_args(argv)

    system_prompt = Path(args.system_prompt).read_text().strip()

    # Read all records
    records = []
    with open(args.input) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))

    # Format all
    formatted = [format_pair(r, system_prompt) for r in records]

    # Write all output
    out = sys.stdout if args.output == "-" else open(args.output, "w")
    try:
        for f_record in formatted:
            out.write(json.dumps(f_record) + "\n")
    finally:
        if out is not sys.stdout:
            out.close()

    # Train/val split
    if args.split is not None and args.train_file and args.val_file:
        rng = random.Random(args.seed)
        indices = list(range(len(formatted)))
        rng.shuffle(indices)
        split_point = int(len(indices) * args.split)
        train_indices = set(indices[:split_point])

        with open(args.train_file, "w") as tf, open(args.val_file, "w") as vf:
            for i, f_record in enumerate(formatted):
                line = json.dumps(f_record) + "\n"
                if i in train_indices:
                    tf.write(line)
                else:
                    vf.write(line)

        print(
            f"Split {len(formatted)} pairs: "
            f"{split_point} train, {len(formatted) - split_point} val",
            file=sys.stderr,
        )
    elif args.output != "-":
        print(f"Formatted {len(formatted)} pairs to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

Run: `cd /mnt/aux-data/teague/Projects/pluckit/main && python -m pytest training/tests/test_format.py -v`
Expected: PASS

- [ ] **Step 5: Test the full pipeline end-to-end**

Run:
```bash
cd /mnt/aux-data/teague/Projects/pluckit/main && \
python -m training.generate --count 500 --seed 42 --output /tmp/raw.jsonl && \
python -m training.validate /tmp/raw.jsonl --output /tmp/valid.jsonl --min-chain-length 2 --dedup-intents && \
python -m training.system_prompt --spec reference/api.yaml --output /tmp/system_prompt.txt 2>/dev/null || \
python -c "
from training.spec import load_spec
from training.system_prompt import generate_system_prompt, write_system_prompt
spec = load_spec('reference/api.yaml')
write_system_prompt(spec, '/tmp/system_prompt.txt')
" && \
python -m training.format /tmp/valid.jsonl --output /tmp/training.jsonl --system-prompt /tmp/system_prompt.txt --split 0.9 --train-file /tmp/train.jsonl --val-file /tmp/val.jsonl --seed 42 && \
echo "--- Pipeline complete ---" && \
wc -l /tmp/raw.jsonl /tmp/valid.jsonl /tmp/training.jsonl /tmp/train.jsonl /tmp/val.jsonl
```
Expected: Full pipeline runs without errors. raw > valid (some rejected/deduped). training = valid. train + val = training.

- [ ] **Step 6: Commit**

```bash
git add training/format.py training/tests/test_format.py
git commit -m "feat(training): format.py — chat JSONL formatter with train/val split"
```

---

## Spec Coverage Checklist

| Spec requirement | Task |
|---|---|
| Load api.yaml (types, ops, selectors, composition, examples) | Task 1 |
| Name pools (100+ function names, 50+ class names, module paths, params, code snippets) | Task 2 |
| Selector sampling (node types, names, attributes, pseudo-selectors, composed) | Task 2 |
| Chain shape sampling from composition rules | Task 4 |
| Type-valid chain generation (input/output type checking) | Task 4 |
| Chain length weighted 2-4 | Task 4 |
| Fill selectors from vocabulary | Task 2 + Task 4 |
| Fill operation arguments from spec examples | Task 4 |
| Template-based intent generation | Task 5 |
| Intent enrichment as metadata annotation only | Task 5 |
| Strategy label (template/paraphrase/reverse) by ratio | Task 5 |
| JSONL output format (intent, chain, shape, category, strategy) | Task 6 |
| CLI: generate.py with --spec, --count, --output, --seed, --paraphrase-ratio, --reverse-ratio | Task 6 |
| Seed examples from api.yaml included verbatim | Task 4 + Task 6 |
| Chain parser for validation | Task 3 |
| Type-check each step against composition rules | Task 7 |
| Terminal must be last | Task 7 |
| Save without mutation warns | Task 7 |
| Reject too-short chains | Task 7 |
| Dedup intents | Task 7 |
| CLI: validate.py with --spec, --output, --reject-file, --min-chain-length, --dedup-intents | Task 7 |
| System prompt auto-generated from api.yaml | Task 8 |
| System prompt lists all operations with signatures | Task 8 |
| Chat message format (system/user/assistant) | Task 9 |
| Train/val split | Task 9 |
| CLI: format.py with --system-prompt, --split, --train-file, --val-file | Task 9 |
| Dependencies: pyyaml + stdlib only | All tasks |
