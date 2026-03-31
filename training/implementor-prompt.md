# Training Data Generator — Implementor Prompt

Build a synthetic training data generator for fine-tuning a 1.5B code model to
produce pluckit chains from natural language intent.

## Context

pluckit is a fluent API for querying and mutating source code. The API spec
lives at `../reference/api.yaml`. The spec defines types, selectors, operations,
composition rules, and example chains.

The goal: generate thousands of (intent, chain) pairs that are type-valid
according to the composition rules. These pairs train a Qwen 2.5 Coder 1.5B
model (via LoRA fine-tuning) to generate pluckit chains from natural language.

The generator does NOT need pluckit to be implemented. It validates chains
against the type system in the spec, not against a running system.

## What to build

### 1. `generate.py` — Chain and intent generator

Reads `../reference/api.yaml` and produces (intent, chain) pairs.

**Chain generation strategy:**

1. **Sample a chain shape** from the composition rules.
   - Choose a starting type (Source or Selection via entry point)
   - Choose a sequence of operations where each operation's input type matches
     the previous operation's output type
   - End with either a terminal operation or a delegate
   - Chain length: 1-7 operations (weighted toward 2-4)

2. **Fill selectors** by sampling from the selector vocabulary.
   - Node types: `.fn`, `.cls`, `.call`, etc.
   - Names: sample from a name pool (realistic function/class/variable names)
   - Attributes: `[name^="test_"]`, `[name*="valid"]`, `[params>=3]`
   - Pseudo-selectors: `:exported`, `:has(...)`, `:not(...)`
   - Compose selectors: `.cls#Auth .fn:exported`, `.fn:has(.call#print)`

3. **Fill operation arguments** from the examples in the spec.
   - `addParam`: sample from `param_examples`
   - `guard`: sample from `strategy_examples`
   - `at`: sample from `ref_examples`
   - `filter`: sample from `predicate_examples`
   - String arguments (rename targets, code snippets): sample from pools

4. **Generate intent** using one of three strategies (configurable mix):

   **Strategy A: Template-based (60% of pairs)**
   Define intent templates per chain shape:
   ```
   "select.filter" → "find all {node_type}s where {predicate_description}"
   "select.addParam.save" → "add {param} to all {selector_description}"
   "select.rename" → "rename {old} to {new} across the codebase"
   "select.similar.refactor" → "extract common pattern from {selector_description}"
   ```
   Fill templates from the chain's actual parameters.

   **Strategy B: Paraphrase (30% of pairs)**
   Generate a template-based intent, then paraphrase it using a small model
   (Ollama qwen2.5-coder:1.5b or Haiku). This adds natural variation.
   Falls back to template if model unavailable.

   **Strategy C: Reverse generation (10% of pairs)**
   Give the chain to a model and ask "what would a developer say to produce this?"
   More expensive but produces the most natural intents.
   Falls back to template if model unavailable.

**Name pools** (for realistic selectors and arguments):

```python
FUNCTION_NAMES = [
    "validate_token", "process_data", "handle_request", "parse_header",
    "get_user", "save_record", "send_email", "check_permissions",
    "transform_batch", "run_migration", "build_query", "render_template",
    "authenticate", "authorize", "serialize", "deserialize",
    "connect", "disconnect", "retry", "cleanup", "initialize",
    # ... extend to 100+
]

CLASS_NAMES = [
    "AuthService", "UserManager", "DatabaseClient", "RequestHandler",
    "CacheLayer", "EventBus", "TaskQueue", "ConfigManager",
    # ... extend to 50+
]

MODULE_PATHS = [
    "src/**/*.py", "src/auth/**/*.py", "src/db/**/*.py",
    "src/api/**/*.py", "src/client/**/*.py", "tests/**/*.py",
    "src/middleware/**/*.py", "src/models/**/*.py",
]

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
]

CODE_SNIPPETS = {
    "prepend": [
        "logger.debug(f'entering {__name__}')",
        "if log_level:\\n    logging.setLevel(log_level)",
        "if dry_run:\\n    logger.info('DRY RUN mode')",
        "start_time = time.monotonic()",
    ],
    "append": [
        "logger.debug(f'exiting {__name__}')",
        "elapsed = time.monotonic() - start_time",
    ],
    "wrap_before": [
        "try:",
        "with db.transaction():",
        "with timing_context():",
    ],
    "wrap_after": [
        "except DatabaseError:\\n    log.error('query failed')\\n    raise",
        "except TimeoutError:\\n    log.warning('timed out')\\n    return None",
        "except Exception as e:\\n    log.error(f'unexpected: {e}')\\n    raise",
    ],
}
```

**Output format** (JSONL, one pair per line):

```json
{"intent": "add timeout parameter to all public functions", "chain": "select('.fn:exported').addParam('timeout: int = 30')", "shape": "select.addParam", "category": "mutation"}
```

**CLI:**

```
python generate.py \
    --spec ../reference/api.yaml \
    --count 10000 \
    --output raw_pairs.jsonl \
    --paraphrase-model qwen2.5-coder:1.5b \  # optional, for strategy B/C
    --paraphrase-ratio 0.3 \                   # 30% paraphrased
    --reverse-ratio 0.1 \                      # 10% reverse-generated
    --seed 42
```

### 2. `validate.py` — Type checker

Validates generated chains against the composition rules.

**What it checks:**

1. **Parse the chain** into a sequence of operations.
   - Entry point: `source(...)` or `select(...)`
   - Operations: `.method(args)` calls
   - Handle chaining: `select(...).find(...).filter(...)...`

2. **Type-check each step.**
   - Look up the operation in the spec
   - Verify the input type matches what the previous step produced
   - Verify the arguments are syntactically valid (strings, callables, etc.)
   - Track the output type for the next step

3. **Check composition rules.**
   - Terminal operations must be last
   - Mutation operations return Selection (chainable)
   - Delegate operations that return Selection are chainable
   - `.save()` must follow at least one mutation or delegate

4. **Filter low-quality pairs.**
   - Reject chains shorter than 2 operations (too trivial)
   - Reject duplicate intents (keep most diverse chains)
   - Reject implausible filter predicates (e.g., `params().count() > 100`)
   - Flag but don't reject chains with unusual compositions (for manual review)

**Output:** filtered JSONL with a `valid` field and optional `warnings`.

**CLI:**

```
python validate.py raw_pairs.jsonl \
    --spec ../reference/api.yaml \
    --output valid_pairs.jsonl \
    --min-chain-length 2 \
    --dedup-intents \
    --reject-file rejected.jsonl
```

### 3. `format.py` — Fine-tuning formatter

Converts validated pairs into the chat format expected by fine-tuning frameworks.

**Output format** (JSONL, chat messages):

```json
{
    "messages": [
        {
            "role": "system",
            "content": "<system prompt from system_prompt.txt>"
        },
        {
            "role": "user",
            "content": "add timeout parameter to all public functions"
        },
        {
            "role": "assistant",
            "content": "fns = select('.fn:exported')\nfns.addParam('timeout: int = 30')\nfns.test()\nfns.save('feat: add timeout parameter')"
        }
    ]
}
```

The system prompt should be the lackpy Jupyter cell prompt with the pluckit
namespace description (generated from the api.yaml).

**CLI:**

```
python format.py valid_pairs.jsonl \
    --output training.jsonl \
    --system-prompt system_prompt.txt \
    --split 0.9 \                     # 90% train, 10% validation
    --train-file train.jsonl \
    --val-file val.jsonl
```

### 4. `system_prompt.txt` — Generated from api.yaml

The system prompt for the fine-tuned model. Generated from the spec so it stays
in sync with the API.

```
You are a Jupyter notebook cell generator. Write a single cell
using ONLY the pre-loaded kernel namespace below.

Output ONLY the cell contents — no markdown, no explanation, no code fences.

Assign results to variables and reuse them. Never call the same function twice
when you can reuse a variable.

You compose source code queries and mutations using the pluckit API.

Kernel namespace:
  select(selector) -> Selection: Select AST nodes with CSS selectors
  source(glob) -> Source: Create a source from file patterns

Selection operations:
  .find(selector) -> Selection: Narrow to descendants
  .filter(predicate) -> Selection: Filter by condition
  .callers() -> Selection: Functions that call this
  .callees() -> Selection: Functions this calls
  .similar(threshold) -> Selection: Structurally similar nodes
  .reachable(max_depth?) -> Selection: All reachable in call graph
  .history() -> History: All versions
  .at(ref) -> Selection: Version at point in time
  .isolate() -> Isolated: Extract runnable block
  .impact() -> View: Blast radius with tests
  ...
  <remaining operations from api.yaml>

Builtins: len, sorted, range, str, int, print, enumerate, any, all

Not available: import, def, class, while, try/except, open
```

Generate this from api.yaml rather than maintaining it by hand.

## Design principles

1. **No pluckit implementation needed.** The generator and validator work from
   the type system in api.yaml. Chains are structurally valid, not runtime-tested.

2. **Deterministic core, optional model enrichment.** The chain generator is
   deterministic (given a seed). Intent paraphrasing and reverse generation are
   optional model-powered enrichments that fall back to templates.

3. **Composable pipeline.** Generate → validate → format. Each stage reads JSONL
   and writes JSONL. Each can be run independently or piped together.

4. **Extensible.** When the API spec changes (new operations, new selectors),
   regenerate training data from the updated spec. No manual example authoring.

5. **Seeded with real examples.** The `example_chains` section of api.yaml
   provides hand-written seed examples. The generator uses these as templates
   and also includes them verbatim in the training set.

## Testing

- `test_generate.py`: Test that generated chains parse correctly and cover all
  operation categories
- `test_validate.py`: Test that the type checker accepts valid chains and rejects
  invalid ones (e.g., terminal in the middle, type mismatch)
- `test_format.py`: Test that output matches expected chat format
- `test_system_prompt.py`: Test that the system prompt is generated correctly
  from api.yaml and includes all operations

## Dependencies

```
pyyaml          # api.yaml parsing
ollama          # optional: intent paraphrasing (Tier 2)
anthropic       # optional: intent paraphrasing (Tier 3)
```

Core generation (template-based intents) needs only pyyaml and stdlib.
