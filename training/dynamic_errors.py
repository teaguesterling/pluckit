"""Dynamic error and code-context generation for training data.

Instead of sampling from fixed pools, generates error scenarios parametrically
by combining error patterns, function names, file paths, and line numbers.
This produces far more unique (intent, chain, context) triples.
"""
from __future__ import annotations

import random


# =============================================================================
# Error pattern templates — combine with function/file/line for unique triples
# =============================================================================

# Each pattern has:
#   template: error message with {fn}, {var}, {type}, {file}, {line} placeholders
#   fix_ops: list of (chain_suffix_template, intent_templates) tuples
#   languages: which languages this pattern applies to

_PYTHON_ERROR_PATTERNS = [
    # --- TypeError: None ---
    {
        "template": "TypeError: argument '{var}' expected {type}, got None",
        "fix": lambda fn, var, file, line, rng: {
            "chain": f"source('{file}').find('.fn#{fn}').at_line({line}).prepend('if {var} is None:\\n    raise TypeError(\"{var} must be {rng.choice(['str', 'int', 'bytes'])}, not None\")')",
            "intents": [
                f"{fn} crashes when {var} is None — add a type check",
                f"add None guard for {var} in {fn}",
                f"fix the TypeError in {fn} — {var} can be None",
                f"handle None {var} in {fn} at line {line}",
                f"{fn}() throws TypeError on None input",
            ],
        },
    },
    {
        "template": "TypeError: 'NoneType' object is not iterable",
        "fix": lambda fn, var, file, line, rng: {
            "chain": f"source('{file}').find('.fn#{fn}').at_line({line}).prepend('if {var} is None:\\n    {var} = []')",
            "intents": [
                f"{fn} fails when {var} is None — default to empty list",
                f"fix: iterating over None in {fn}",
                f"add fallback for None {var} in {fn}",
                f"the loop in {fn} crashes on None — add a default",
            ],
        },
    },
    {
        "template": "TypeError: unsupported operand type(s) for +: 'int' and 'str'",
        "fix": lambda fn, var, file, line, rng: {
            "chain": f"source('{file}').find('.fn#{fn}').at_line({line}).replaceWith('{var} + ', 'str({var}) + ')",
            "intents": [
                f"type mismatch in {fn} — convert {var} to string before concatenation",
                f"fix TypeError in {fn}: can't add int and str",
                f"{fn} has a type error at line {line} — needs str() conversion",
            ],
        },
    },
    # --- AttributeError ---
    {
        "template": "AttributeError: 'NoneType' has no attribute '{attr}'",
        "fix": lambda fn, var, file, line, rng: {
            "chain": f"source('{file}').find('.fn#{fn}').at_line({line}).prepend('if {var} is None:\\n    raise ValueError(\"{var} is required\")')",
            "intents": [
                f"{fn} crashes on None — {var}.{rng.choice(['decode', 'strip', 'id', 'name', 'status'])}() fails",
                f"add null check in {fn} before accessing .{rng.choice(['decode', 'strip', 'id', 'name'])}",
                f"fix AttributeError in {fn} at line {line}",
                f"{var} can be None in {fn} — guard against it",
            ],
        },
    },
    # --- KeyError ---
    {
        "template": "KeyError: '{key}'",
        "fix": lambda fn, var, file, line, rng: {
            "chain": f"source('{file}').find('.fn#{fn}').at_line({line}).replaceWith(\"{var}['{var}']\", \"{var}.get('{var}', {rng.choice(['None', '\"\"', '0', '{}', '[]'])})\")",
            "intents": [
                f"KeyError in {fn} — use .get() with default instead of direct access",
                f"fix: {fn} crashes when '{var}' key is missing",
                f"handle missing key '{var}' in {fn}",
                f"the dict access in {fn} at line {line} needs a default",
            ],
        },
    },
    # --- ValueError ---
    {
        "template": "ValueError: invalid literal for int() with base 10: '{val}'",
        "fix": lambda fn, var, file, line, rng: {
            "chain": f"source('{file}').find('.fn#{fn}').at_line({line}).wrap('try:', 'except ValueError:\\n    return None')",
            "intents": [
                f"int() conversion in {fn} fails on bad input — wrap in try/except",
                f"fix ValueError in {fn} — handle non-numeric strings",
                f"add error handling for int parsing in {fn}",
                f"{fn} crashes on non-integer input at line {line}",
            ],
        },
    },
    # --- Connection errors ---
    {
        "template": "ConnectionError: Failed to connect to {service}",
        "fix": lambda fn, var, file, line, rng: {
            "chain": f"source('{file}').find('.fn#{fn}').guard('ConnectionError', '{rng.choice(['retry 3 times', 'log and reraise', 'return None'])}')",
            "intents": [
                f"{fn} has no error handling for connection failures",
                f"add retry logic to {fn} for ConnectionError",
                f"handle connection failures in {fn}",
                f"{fn} crashes when {rng.choice(['the database', 'the API', 'the service'])} is down",
            ],
        },
    },
    # --- FileNotFoundError ---
    {
        "template": "FileNotFoundError: [Errno 2] No such file or directory: '{path}'",
        "fix": lambda fn, var, file, line, rng: {
            "chain": f"source('{file}').find('.fn#{fn}').at_line({line}).wrap('try:', 'except FileNotFoundError as e:\\n    raise ConfigError(f\"missing file: {{e}}\") from e')",
            "intents": [
                f"{fn} doesn't handle missing files",
                f"add FileNotFoundError handling to {fn}",
                f"fix: {fn} crashes when the file doesn't exist",
                f"wrap the file operation in {fn} with proper error handling",
            ],
        },
    },
    # --- IndexError ---
    {
        "template": "IndexError: list index out of range",
        "fix": lambda fn, var, file, line, rng: {
            "chain": f"source('{file}').find('.fn#{fn}').at_line({line}).prepend('if not {var}:\\n    return {rng.choice(['None', '[]', '\"\"'])}')",
            "intents": [
                f"{fn} crashes on empty list at line {line}",
                f"add bounds check in {fn} before indexing",
                f"fix IndexError in {fn} — check if list is empty first",
                f"guard against empty {var} in {fn}",
            ],
        },
    },
    # --- ZeroDivisionError ---
    {
        "template": "ZeroDivisionError: division by zero",
        "fix": lambda fn, var, file, line, rng: {
            "chain": f"source('{file}').find('.fn#{fn}').at_line({line}).prepend('if {var} == 0:\\n    raise ValueError(\"{var} cannot be zero\")')",
            "intents": [
                f"division by zero in {fn} — add a zero check",
                f"fix ZeroDivisionError in {fn} at line {line}",
                f"{fn} divides by {var} without checking for zero",
                f"add guard for zero {var} in {fn}",
            ],
        },
    },
    # --- Silent return None ---
    {
        "template": "Silent bug: {fn} returns None instead of raising",
        "fix": lambda fn, var, file, line, rng: {
            "chain": f"select('.fn#{fn}').replaceWith('return None', 'raise {rng.choice(['ValueError', 'RuntimeError', 'NotFoundError'])}(\"{fn} failed\")')",
            "intents": [
                f"{fn} silently returns None — it should raise",
                f"fix the silent failure in {fn}",
                f"replace return None with an exception in {fn}",
                f"{fn} swallows errors by returning None",
                f"the None return in {fn} is hiding a bug",
            ],
        },
    },
    # --- Bare except ---
    {
        "template": "Code smell: bare except in {fn}",
        "fix": lambda fn, var, file, line, rng: {
            "chain": f"source('{file}').find('.fn#{fn}').find('.except').replaceWith('except:', 'except {rng.choice(['Exception', 'ValueError', 'RuntimeError'])} as e:\\n    logger.exception(e)\\n    raise')",
            "intents": [
                f"the except block in {fn} catches everything — narrow it",
                f"fix bare except in {fn} — it's swallowing errors",
                f"replace bare except with specific exception type in {fn}",
                f"the error handling in {fn} is too broad",
            ],
        },
    },
    # --- Missing import ---
    {
        "template": "ImportError: cannot import name '{name}' from '{module}'",
        "fix": lambda fn, var, file, line, rng: {
            "chain": f"source('{file}').find('.import#{var}').replaceWith('{var}', '{rng.choice(['Optional', 'Any', 'Union', 'List', 'Dict'])}')",
            "intents": [
                f"fix ImportError in {file} — wrong import name",
                f"the import of {var} from {rng.choice(['typing', 'collections', 'os'])} is wrong",
            ],
        },
    },
]

_GO_ERROR_PATTERNS = [
    # --- Nil pointer ---
    {
        "template": "panic: runtime error: invalid memory address or nil pointer dereference",
        "fix": lambda fn, var, file, line, rng: {
            "chain": f"source('{file}').find('.fn#{fn}').at_line({line}).prepend('if {var} == nil {{\\n    return {rng.choice(['nil, fmt.Errorf(\"nil ' + var + '\")', 'fmt.Errorf(\"nil ' + var + '\")'])}\\n}}')",
            "intents": [
                f"nil pointer dereference in {fn} — add nil check for {var}",
                f"{fn} panics on nil {var}",
                f"add nil guard in {fn} at line {line}",
                f"fix panic in {fn}: {var} can be nil",
            ],
        },
    },
    # --- Error ignored ---
    {
        "template": "error return value of '{call}' is not checked",
        "fix": lambda fn, var, file, line, rng: {
            "chain": f"source('{file}').find('.fn#{fn}').find('.call#{var}').wrap('if err := ', '; err != nil {{\\n    return fmt.Errorf(\"{var}: %w\", err)\\n}}')",
            "intents": [
                f"{fn} ignores error from {var}() — handle it",
                f"add error check for {var}() in {fn}",
                f"the {var} call in {fn} needs error handling",
                f"fix: unchecked error from {var} in {fn}",
            ],
        },
    },
    # --- Missing context ---
    {
        "template": "undefined: ctx",
        "fix": lambda fn, var, file, line, rng: {
            "chain": f"source('{file}').find('.fn#{fn}').addParam('ctx context.Context', before='*')",
            "intents": [
                f"{fn} needs a context.Context parameter",
                f"add ctx to {fn} — it's missing context propagation",
                f"fix: {fn} doesn't accept context.Context",
                f"propagate context through {fn}",
            ],
        },
    },
    # --- Goroutine leak ---
    {
        "template": "goroutine leak: {fn} spawns goroutines without cleanup",
        "fix": lambda fn, var, file, line, rng: {
            "chain": f"source('{file}').find('.fn#{fn}').find('.call').containing('go ').wrap('', 'defer wg.Done()')",
            "intents": [
                f"{fn} leaks goroutines — add WaitGroup",
                f"fix goroutine leak in {fn}",
                f"the goroutines in {fn} are never cleaned up",
            ],
        },
    },
    # --- Data race ---
    {
        "template": "WARNING: DATA RACE in {fn}",
        "fix": lambda fn, var, file, line, rng: {
            "chain": f"source('{file}').find('.fn#{fn}').prepend('{rng.choice(['mu.Lock()\\ndefer mu.Unlock()', 'mu.RLock()\\ndefer mu.RUnlock()'])}')",
            "intents": [
                f"data race in {fn} — add mutex",
                f"fix concurrent access in {fn}",
                f"{fn} has a race condition — needs synchronization",
            ],
        },
    },
]

_TS_ERROR_PATTERNS = [
    # --- Undefined property ---
    {
        "template": "TypeError: Cannot read properties of undefined (reading '{prop}')",
        "fix": lambda fn, var, file, line, rng: {
            "chain": f"source('{file}').find('.fn#{fn}').at_line({line}).replaceWith('{var}.{rng.choice(['name', 'id', 'status', 'email', 'value'])}', '{var}?.{rng.choice(['name', 'id', 'status', 'email', 'value'])} ?? {rng.choice(['\"\"', '\"Unknown\"', 'null', '0'])}')",
            "intents": [
                f"fix undefined property access in {fn} at line {line}",
                f"{fn} crashes when {var} is undefined — add optional chaining",
                f"add null safety to {fn} — {var} can be undefined",
                f"fix TypeError in {fn}: {var} might not exist",
            ],
        },
    },
    # --- Type mismatch ---
    {
        "template": "Type '{actual}' is not assignable to type '{expected}'",
        "fix": lambda fn, var, file, line, rng: {
            "chain": f"source('{file}').find('.fn#{fn}').at_line({line}).replaceWith(': {rng.choice(['any', 'string | undefined', 'null'])}', ': {rng.choice(['string', 'number', 'boolean', 'User', 'Response'])}')",
            "intents": [
                f"type error in {fn} — wrong type annotation",
                f"fix type mismatch in {fn} at line {line}",
                f"{fn} has a type assignment error",
            ],
        },
    },
    # --- Missing null check ---
    {
        "template": "TypeError: Cannot read properties of null (reading '{prop}')",
        "fix": lambda fn, var, file, line, rng: {
            "chain": f"source('{file}').find('.fn#{fn}').at_line({line}).prepend('if ({var} === null || {var} === undefined) throw new Error(\"{var} is required\")')",
            "intents": [
                f"{fn} doesn't check for null {var}",
                f"add null check for {var} in {fn}",
                f"fix: {fn} crashes on null {var} at line {line}",
            ],
        },
    },
    # --- Unhandled promise ---
    {
        "template": "Unhandled promise rejection in {fn}",
        "fix": lambda fn, var, file, line, rng: {
            "chain": f"source('{file}').find('.fn#{fn}').wrap('try {{', '}} catch (err) {{\\n    console.error(\"{fn} failed:\", err)\\n    throw err\\n}}')",
            "intents": [
                f"{fn} has no error handling for async operations",
                f"add try/catch around {fn}",
                f"fix unhandled promise rejection in {fn}",
                f"the async code in {fn} needs error handling",
            ],
        },
    },
    # --- Any type ---
    {
        "template": "TypeScript: {fn} uses 'any' type",
        "fix": lambda fn, var, file, line, rng: {
            "chain": f"source('{file}').find('.fn#{fn}').returnType('{rng.choice(['Promise<Data>', 'User[]', 'boolean', 'string', 'Record<string, unknown>'])}')",
            "intents": [
                f"{fn} returns any — add a proper return type",
                f"fix: {fn} is typed as any",
                f"add type annotations to {fn}",
                f"replace the any type in {fn} with a proper type",
            ],
        },
    },
]

# =============================================================================
# Name pools for parametric generation
# =============================================================================

_PYTHON_FILES = [
    "src/auth.py", "src/api/handlers.py", "src/db/client.py",
    "src/utils.py", "src/models.py", "src/services.py",
    "src/middleware.py", "src/config.py", "src/parser.py",
    "src/serialize.py", "src/cache.py", "src/data.py",
    "src/io.py", "src/math_utils.py", "src/validate.py",
    "src/async_utils.py", "src/logging.py", "src/api/client.py",
    "lib/helpers.py", "src/core/base.py",
]

_GO_FILES = [
    "main.go", "cmd/server.go", "handlers/api.go",
    "internal/db/query.go", "internal/user.go", "internal/config.go",
    "internal/cache.go", "internal/worker.go", "pkg/auth/token.go",
    "pkg/client.go", "pkg/parser.go",
]

_TS_FILES = [
    "src/utils.ts", "src/services/user.ts", "src/api/client.ts",
    "src/components/List.tsx", "src/components/Profile.tsx",
    "src/state/reducer.ts", "src/state/store.ts", "src/services/auth.ts",
    "src/services/data.ts", "src/app.ts", "lib/helpers.ts",
]

_PYTHON_FUNCTIONS = [
    "validate_token", "process_data", "handle_request", "parse_header",
    "get_user", "save_record", "send_email", "authenticate_user",
    "query_database", "fetch_resource", "load_config", "compute_average",
    "cache_result", "evict_expired", "read_file", "serialize",
    "parse_int", "format_output", "normalize_payload", "decode_jwt",
    "log_event", "setup_logging", "run_async", "get_profile",
]

_GO_FUNCTIONS = [
    "HandleRequest", "ProcessUser", "ValidateToken", "QueryUsers",
    "FetchAll", "ParseConfig", "StartServer", "NewClient",
    "SerializeData", "ConnectDB", "StartWorker", "SetCache",
    "GetConfig", "ValidateInput", "ReadResponse", "WriteResponse",
]

_TS_FUNCTIONS = [
    "fetchUser", "getDisplayName", "handleError", "filterRecords",
    "renderComponent", "dispatchAction", "formatDate", "deepClone",
    "retryRequest", "transformData", "sendMessage", "validateSchema",
    "parseResponse", "updateState", "loadData", "generateToken",
]

_VARIABLES = ["data", "result", "user", "token", "response", "config",
              "items", "payload", "record", "value", "input", "output",
              "conn", "session", "cache", "query", "request", "buffer"]


def generate_parametric_error(rng: random.Random, language: str | None = None) -> dict:
    """Generate a unique error scenario by combining patterns parametrically.

    Returns dict with: chain, intent, context, language, shape, category
    """
    if language is None:
        language = rng.choice(["python", "python", "python", "go", "typescript"])

    if language == "python":
        patterns = _PYTHON_ERROR_PATTERNS
        fn = rng.choice(_PYTHON_FUNCTIONS)
        file = rng.choice(_PYTHON_FILES)
        var = rng.choice(_VARIABLES)
    elif language == "go":
        patterns = _GO_ERROR_PATTERNS
        fn = rng.choice(_GO_FUNCTIONS)
        file = rng.choice(_GO_FILES)
        var = rng.choice(_VARIABLES)
    else:
        patterns = _TS_ERROR_PATTERNS
        fn = rng.choice(_TS_FUNCTIONS)
        file = rng.choice(_TS_FILES)
        var = rng.choice(_VARIABLES)

    pattern = rng.choice(patterns)
    line = str(rng.randint(5, 150))

    # Generate the fix (chain + intent options)
    fix = pattern["fix"](fn, var, file, line, rng)
    chain = fix["chain"]
    intent = rng.choice(fix["intents"])

    # Build error message for context
    error_msg = pattern["template"].format(
        fn=fn, var=var, type=rng.choice(["str", "int", "bytes", "dict"]),
        file=file, line=line, attr=rng.choice(["decode", "strip", "id", "name"]),
        key=var, val=rng.choice(["abc", "N/A", "none", "undefined"]),
        service=rng.choice(["database", "API", "Redis", "S3"]),
        path=rng.choice(["/tmp/data.csv", "config.yaml", ".env"]),
        name=rng.choice(["Optional", "dataclass", "BaseModel"]),
        module=rng.choice(["typing", "pydantic", "dataclasses"]),
        call=rng.choice(["json.Unmarshal", "http.Get", "os.Open", "rows.Close"]),
        prop=rng.choice(["name", "id", "status", "email", "length"]),
        actual=rng.choice(["string | undefined", "null", "any"]),
        expected=rng.choice(["string", "number", "User", "boolean"]),
    )

    context = f"{error_msg}\n  File \"{file}\", line {line}, in {fn}"

    from training.chain_parser import parse_chain
    try:
        ops = parse_chain(chain)
        shape = ".".join(op.name for op in ops)
    except Exception:
        shape = "unknown"

    return {
        "chain": chain,
        "intent": intent,
        "context": context,
        "language": language,
        "shape": shape,
        "category": "error_fix",
    }
