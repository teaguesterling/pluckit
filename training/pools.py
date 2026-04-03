"""Name pools and selector sampling functions for training data generation.

All module-level lists are pure data — no side effects on import.
Sampling functions take a ``random.Random`` instance for reproducibility.
"""
from __future__ import annotations

import random

# ---------------------------------------------------------------------------
# Node types used in CSS-like selectors
# ---------------------------------------------------------------------------

_NODE_TYPES: list[str] = [
    ".fn", ".cls", ".call", ".ret", ".if", ".for", ".while", ".try",
    ".except", ".with", ".assign", ".import", ".dec", ".arg",
    ".str", ".num", ".block", ".comment",
]

# ---------------------------------------------------------------------------
# FUNCTION_NAMES — 100+ realistic Python function names
# ---------------------------------------------------------------------------

FUNCTION_NAMES: list[str] = [
    # auth / tokens
    "validate_token", "refresh_token", "revoke_token", "decode_jwt",
    "encode_jwt", "check_permissions", "authenticate_user", "authorize_request",
    "verify_signature", "generate_token",
    # data processing
    "process_data", "transform_records", "normalize_payload", "flatten_dict",
    "merge_configs", "deep_merge", "chunk_list", "paginate_results",
    "batch_process", "stream_records",
    # I/O / networking
    "handle_request", "send_response", "fetch_resource", "post_data",
    "upload_file", "download_file", "stream_response", "retry_request",
    "build_url", "parse_url",
    # database
    "query_database", "insert_record", "update_record", "delete_record",
    "bulk_insert", "execute_query", "fetch_one", "fetch_all",
    "begin_transaction", "commit_transaction",
    # validation
    "validate_schema", "validate_email", "validate_phone", "validate_date",
    "validate_range", "sanitize_input", "clean_html", "strip_tags",
    "parse_int", "parse_float",
    # caching
    "get_from_cache", "set_in_cache", "invalidate_cache", "warm_cache",
    "cache_result", "evict_expired", "compute_cache_key", "hash_key",
    # logging / monitoring
    "log_event", "log_error", "log_warning", "emit_metric",
    "record_span", "start_trace", "end_trace", "report_exception",
    "capture_breadcrumb", "flush_logs",
    # file / path helpers
    "read_file", "write_file", "append_file", "copy_file",
    "move_file", "delete_file", "list_files", "ensure_dir",
    "resolve_path", "get_extension",
    # serialization
    "serialize", "deserialize", "to_json", "from_json",
    "to_yaml", "from_yaml", "to_csv", "from_csv",
    "encode_base64", "decode_base64",
    # async helpers
    "run_async", "gather_tasks", "cancel_tasks", "wait_for_all",
    "schedule_task", "debounce", "throttle", "rate_limit",
    # string utils
    "slugify", "truncate", "pad_left", "pad_right",
    "camel_to_snake", "snake_to_camel", "pluralize", "format_duration",
    "strip_whitespace", "normalize_unicode",
    # misc
    "get_env", "load_config", "parse_args", "setup_logging",
    "health_check", "ping", "shutdown", "reload_config",
    "compute_hash", "generate_uuid",
]

# ---------------------------------------------------------------------------
# CLASS_NAMES — 50+ realistic class names
# ---------------------------------------------------------------------------

CLASS_NAMES: list[str] = [
    # services
    "AuthService", "UserService", "PaymentService", "NotificationService",
    "EmailService", "SearchService", "ReportService", "AuditService",
    "SchedulerService", "CacheService",
    # managers
    "UserManager", "SessionManager", "ConnectionManager", "TaskManager",
    "ConfigManager", "PluginManager", "ResourceManager", "QueueManager",
    # clients
    "DatabaseClient", "HttpClient", "RedisClient", "S3Client",
    "ApiClient", "GrpcClient", "WebSocketClient", "MessageBusClient",
    # repositories
    "UserRepository", "OrderRepository", "ProductRepository", "EventRepository",
    # handlers
    "RequestHandler", "ErrorHandler", "EventHandler", "WebhookHandler",
    "MessageHandler", "SignalHandler",
    # processors
    "DataProcessor", "BatchProcessor", "StreamProcessor", "ImageProcessor",
    "FileProcessor",
    # parsers / serializers
    "JsonParser", "XmlParser", "CsvParser", "QueryBuilder",
    "ResponseSerializer", "RequestValidator",
    # middleware / interceptors
    "AuthMiddleware", "LoggingMiddleware", "RateLimitMiddleware",
    "CorsMiddleware", "TracingInterceptor",
    # models / schemas
    "UserModel", "OrderSchema", "ConfigSchema", "EventSchema",
    # misc
    "TokenBucket", "CircuitBreaker", "RetryPolicy", "BackoffStrategy",
    "HealthChecker", "MetricsCollector",
]

# ---------------------------------------------------------------------------
# MODULE_PATHS — 8+ glob patterns
# ---------------------------------------------------------------------------

MODULE_PATHS: list[str] = [
    "src/**/*.py",
    "tests/**/*.py",
    "lib/**/*.py",
    "app/**/*.py",
    "scripts/*.py",
    "src/api/**/*.py",
    "src/core/*.py",
    "src/utils/*.py",
    "src/models/**/*.py",
    "src/services/**/*.py",
    "plugins/**/*.py",
    "migrations/*.py",
]

# ---------------------------------------------------------------------------
# PARAM_SPECS — 9+ parameter specifications
# ---------------------------------------------------------------------------

PARAM_SPECS: list[str] = [
    "timeout: int = 30",
    "log_level: str | None = None",
    "max_retries: int = 3",
    "verbose: bool = False",
    "encoding: str = 'utf-8'",
    "strict: bool = True",
    "callback: Callable | None = None",
    "headers: dict[str, str] | None = None",
    "base_url: str = 'https://api.example.com'",
    "page_size: int = 100",
    "timeout_ms: float = 5000.0",
    "raise_on_error: bool = True",
    "session: Session | None = None",
]

# ---------------------------------------------------------------------------
# CODE_SNIPPETS — dict with 4 categories, each a list of code strings
# ---------------------------------------------------------------------------

CODE_SNIPPETS: dict[str, list[str]] = {
    "prepend": [
        "logger = logging.getLogger(__name__)",
        "from __future__ import annotations",
        "import logging",
        "from typing import TYPE_CHECKING",
        "if TYPE_CHECKING:\n    from .types import Context",
        "SENTINEL = object()",
        "_cache: dict = {}",
        "log = structlog.get_logger()",
    ],
    "append": [
        "return None",
        "return result",
        "raise NotImplementedError",
        "return []",
        "return {}",
        "pass",
        "return True",
        "return False",
    ],
    "wrap_before": [
        "try:",
        "with lock:",
        "with contextlib.suppress(Exception):",
        "async with session:",
        "if not dry_run:",
        "with tracer.start_active_span(name):",
        "for attempt in range(max_retries):",
    ],
    "wrap_after": [
        "except Exception as exc:\n    logger.exception(exc)\n    raise",
        "except ValueError:\n    return default",
        "finally:\n    cleanup()",
        "except TimeoutError:\n    raise RetryError from None",
        "except Exception:\n    pass",
        "finally:\n    span.finish()",
        "else:\n    break",
    ],
}

# ---------------------------------------------------------------------------
# EXCEPTION_TYPES — 5+ exception names
# ---------------------------------------------------------------------------

EXCEPTION_TYPES: list[str] = [
    "ValueError",
    "RuntimeError",
    "TimeoutError",
    "PermissionError",
    "NotImplementedError",
    "KeyError",
    "TypeError",
    "ConnectionError",
    "FileNotFoundError",
    "AttributeError",
]

# ---------------------------------------------------------------------------
# GUARD_STRATEGIES — 5+ strategy strings
# ---------------------------------------------------------------------------

GUARD_STRATEGIES: list[str] = [
    "log and reraise",
    "retry 3 times",
    "return default value",
    "raise custom exception",
    "suppress and continue",
    "rollback transaction",
    "emit metric and reraise",
    "log warning and return None",
]

# ---------------------------------------------------------------------------
# RENAME_TARGETS — list of (old_name, new_name) tuples
# ---------------------------------------------------------------------------

RENAME_TARGETS: list[tuple[str, str]] = [
    ("get_data", "fetch_data"),
    ("do_request", "send_request"),
    ("check", "validate"),
    ("run", "execute"),
    ("make_client", "build_client"),
    ("parse", "deserialize"),
    ("write", "persist"),
    ("Manager", "Service"),
    ("Handler", "Processor"),
    ("helper", "util"),
]

# ---------------------------------------------------------------------------
# Pseudo-selectors and attribute patterns used in sampling
# ---------------------------------------------------------------------------

_PSEUDO_SELECTORS: list[str] = [
    ":exported",
    ":async",
    ":decorated",
    ":first-child",
    ":last-child",
    ":has-docstring",
]

_ATTR_PATTERNS: list[str] = [
    '[name^="test_"]',
    '[name$="_handler"]',
    '[name*="process"]',
    '[name="main"]',
    '[name^="get_"]',
    '[name$="_service"]',
    '[name^="validate_"]',
]

# ---------------------------------------------------------------------------
# Selector sampling functions
# ---------------------------------------------------------------------------

def sample_selector(rng: random.Random) -> str:
    """Sample a single CSS-like selector.

    Distribution:
    - 40%  bare type              e.g. ``.fn``
    - 30%  with name              e.g. ``.fn#validate_token``
    - 15%  with pseudo-class      e.g. ``.fn:exported``
    - 15%  with attribute         e.g. ``.fn[name^="test_"]``
    """
    node = rng.choice(_NODE_TYPES)
    roll = rng.random()
    if roll < 0.40:
        return node
    elif roll < 0.70:
        name = rng.choice(FUNCTION_NAMES)
        return f"{node}#{name}"
    elif roll < 0.85:
        pseudo = rng.choice(_PSEUDO_SELECTORS)
        return f"{node}{pseudo}"
    else:
        attr = rng.choice(_ATTR_PATTERNS)
        return f"{node}{attr}"


def sample_composed_selector(rng: random.Random) -> str:
    """Sample a composed CSS-like selector.

    Distribution:
    - 40%  descendant   ``A B``
    - 20%  child        ``A > B``
    - 20%  :has()       ``A:has(B)``
    - 20%  :not(:has()) ``A:not(:has(B))``
    """
    a = sample_selector(rng)
    b = sample_selector(rng)
    roll = rng.random()
    if roll < 0.40:
        return f"{a} {b}"
    elif roll < 0.60:
        return f"{a} > {b}"
    elif roll < 0.80:
        return f"{a}:has({b})"
    else:
        return f"{a}:not(:has({b}))"


# ---------------------------------------------------------------------------
# LANGUAGES — supported languages with their file extensions and idioms
# ---------------------------------------------------------------------------

LANGUAGES: list[dict[str, str]] = [
    {"name": "python", "ext": "py", "glob": "**/*.py"},
    {"name": "go", "ext": "go", "glob": "**/*.go"},
    {"name": "typescript", "ext": "ts", "glob": "**/*.ts"},
]

# Language-specific function name pools
GO_FUNCTION_NAMES: list[str] = [
    "HandleRequest", "ProcessMessage", "ValidateInput", "SerializeData",
    "ParseConfig", "ConnectDB", "QueryUsers", "UpdateRecord",
    "FetchResource", "WriteResponse", "StartServer", "ShutdownGracefully",
    "RetryWithBackoff", "HashPassword", "VerifyToken", "GenerateID",
    "LogEvent", "EmitMetric", "CompressPayload", "DecryptMessage",
    "MarshalJSON", "UnmarshalJSON", "OpenFile", "ReadAll",
    "WalkDir", "CleanupResources", "InitLogger", "NewClient",
    "Close", "Ping", "HealthCheck", "Middleware",
]

TS_FUNCTION_NAMES: list[str] = [
    "fetchUser", "createOrder", "validateSchema", "parseResponse",
    "handleError", "renderComponent", "updateState", "dispatchAction",
    "subscribeToEvents", "unsubscribe", "formatDate", "debounce",
    "throttle", "memoize", "deepClone", "mergeOptions",
    "connectWebSocket", "sendMessage", "retryRequest", "cacheResult",
    "transformData", "filterRecords", "sortBy", "groupBy",
    "mapToDTO", "serializeForm", "validateEmail", "sanitizeInput",
    "generateToken", "hashString", "encryptPayload", "decryptPayload",
]

GO_CLASS_NAMES: list[str] = [
    "Server", "Client", "Handler", "Middleware",
    "Repository", "Service", "Controller", "Router",
    "Config", "Logger", "Cache", "Pool",
    "Worker", "Scheduler", "Queue", "Pipeline",
]

TS_CLASS_NAMES: list[str] = [
    "UserService", "ApiClient", "EventEmitter", "StateManager",
    "FormValidator", "RouteHandler", "WebSocketManager", "CacheProvider",
    "AuthGuard", "DataTransformer", "ErrorBoundary", "ThemeProvider",
    "QueryBuilder", "SchemaValidator", "TokenManager", "RateLimiter",
]

# Language-specific module paths
GO_MODULE_PATHS: list[str] = [
    "**/*.go", "cmd/**/*.go", "internal/**/*.go",
    "pkg/**/*.go", "api/**/*.go", "handlers/**/*.go",
]

TS_MODULE_PATHS: list[str] = [
    "src/**/*.ts", "src/**/*.tsx", "lib/**/*.ts",
    "components/**/*.tsx", "services/**/*.ts", "utils/**/*.ts",
]

# ---------------------------------------------------------------------------
# DECORATOR_SPECS — decorator strings for addDecorator
# ---------------------------------------------------------------------------

DECORATOR_SPECS: list[str] = [
    "@lru_cache",
    "@lru_cache(maxsize=128)",
    "@retry(max_attempts=3)",
    "@pytest.mark.slow",
    "@pytest.mark.parametrize('input,expected', cases)",
    "@staticmethod",
    "@classmethod",
    "@property",
    "@abstractmethod",
    "@override",
    "@deprecated",
    "@log_calls",
    "@require_auth",
    "@rate_limit(100)",
    "@cache(ttl=300)",
    "@validate_input",
    "@transaction",
    "@timing",
]

# ---------------------------------------------------------------------------
# IMPORT_SPECS — import statements for ensureImport
# ---------------------------------------------------------------------------

IMPORT_SPECS: list[str] = [
    "import logging",
    "import json",
    "import os",
    "import sys",
    "import re",
    "from typing import Optional",
    "from typing import Any",
    "from typing import TYPE_CHECKING",
    "from pathlib import Path",
    "from dataclasses import dataclass",
    "from contextlib import contextmanager",
    "from functools import lru_cache",
    "from collections import defaultdict",
    "from datetime import datetime",
    "import asyncio",
]

# ---------------------------------------------------------------------------
# ARG_SPECS — argument strings for addArg
# ---------------------------------------------------------------------------

ARG_SPECS: list[str] = [
    "timeout=30",
    "timeout=timeout",
    "log_level=log_level",
    "retry=True",
    "encoding='utf-8'",
    "callback=on_complete",
    "session=session",
    "ctx=ctx",
    "dry_run=dry_run",
    "verbose=verbose",
]

# ---------------------------------------------------------------------------
# TYPE_ANNOTATIONS — for annotate/returnType operations
# ---------------------------------------------------------------------------

TYPE_ANNOTATIONS: list[str] = [
    "str", "int", "float", "bool", "bytes",
    "list[str]", "dict[str, Any]", "Optional[str]",
    "None", "bool | None", "str | None",
    "list[dict]", "tuple[int, ...]", "Callable[..., None]",
    "Any",
]

# ---------------------------------------------------------------------------
# ERROR_MESSAGES — realistic error messages for error-driven training pairs
# ---------------------------------------------------------------------------

ERROR_MESSAGES: dict[str, list[dict[str, str]]] = {
    "python": [
        {
            "error": "TypeError: argument 'token' expected str, got None",
            "file": "src/auth.py",
            "function": "validate_token",
            "line": "23",
            "fix_op": "replaceWith",
        },
        {
            "error": "AttributeError: 'NoneType' has no attribute 'decode'",
            "file": "src/auth.py",
            "function": "decode_jwt",
            "line": "47",
            "fix_op": "prepend",
        },
        {
            "error": "KeyError: 'user_id'",
            "file": "src/api/handlers.py",
            "function": "get_user",
            "line": "31",
            "fix_op": "replaceWith",
        },
        {
            "error": "ValueError: invalid literal for int() with base 10: 'abc'",
            "file": "src/utils.py",
            "function": "parse_int",
            "line": "15",
            "fix_op": "wrap",
        },
        {
            "error": "ConnectionError: Failed to connect to database",
            "file": "src/db/client.py",
            "function": "query_database",
            "line": "88",
            "fix_op": "guard",
        },
        {
            "error": "ImportError: cannot import name 'Optional' from 'typing'",
            "file": "src/models.py",
            "function": None,
            "line": "1",
            "fix_op": "replaceWith",
        },
        {
            "error": "RecursionError: maximum recursion depth exceeded",
            "file": "src/tree.py",
            "function": "traverse",
            "line": "42",
            "fix_op": "prepend",
        },
        {
            "error": "FileNotFoundError: [Errno 2] No such file or directory: 'config.yaml'",
            "file": "src/config.py",
            "function": "load_config",
            "line": "12",
            "fix_op": "wrap",
        },
    ],
    "go": [
        {
            "error": "panic: runtime error: invalid memory address or nil pointer dereference",
            "file": "main.go",
            "function": "ProcessUser",
            "line": "23",
            "fix_op": "prepend",
        },
        {
            "error": "cannot use x (variable of type string) as type int in argument",
            "file": "handlers/api.go",
            "function": "HandleRequest",
            "line": "45",
            "fix_op": "replaceWith",
        },
        {
            "error": "undefined: ctx",
            "file": "service/auth.go",
            "function": "ValidateInput",
            "line": "18",
            "fix_op": "addParam",
        },
        {
            "error": "err is shadowed during return",
            "file": "pkg/db/query.go",
            "function": "QueryUsers",
            "line": "33",
            "fix_op": "replaceWith",
        },
    ],
    "typescript": [
        {
            "error": "TypeError: Cannot read properties of undefined (reading 'name')",
            "file": "src/utils.ts",
            "function": "getDisplayName",
            "line": "15",
            "fix_op": "replaceWith",
        },
        {
            "error": "Type 'string | undefined' is not assignable to type 'string'",
            "file": "src/services/user.ts",
            "function": "fetchUser",
            "line": "28",
            "fix_op": "replaceWith",
        },
        {
            "error": "Property 'status' does not exist on type 'Response'",
            "file": "src/api/client.ts",
            "function": "handleError",
            "line": "42",
            "fix_op": "annotate",
        },
        {
            "error": "Argument of type 'null' is not assignable to parameter of type 'User'",
            "file": "src/components/Profile.tsx",
            "function": "renderComponent",
            "line": "55",
            "fix_op": "replaceWith",
        },
    ],
}

# ---------------------------------------------------------------------------
# CODE_CONTEXT_SNIPPETS — code fragments for context-bearing training pairs
# ---------------------------------------------------------------------------

CODE_CONTEXT_SNIPPETS: dict[str, list[dict[str, str]]] = {
    "python": [
        {
            "code": "def validate_token(token):\n    if not token:\n        return None\n    return token.decode()",
            "problem": "returns None silently instead of raising",
            "fix_chain": "select('.fn#validate_token').replaceWith('return None', 'raise ValueError(\"token required\")')",
        },
        {
            "code": "db.execute(f'SELECT * FROM users WHERE id={user_id}')",
            "problem": "SQL injection via string formatting",
            "fix_chain": "select('.call#execute').containing('f\"SELECT').replaceWith(\"f'SELECT * FROM users WHERE id={user_id}'\", \"'SELECT * FROM users WHERE id=?', (user_id,)\")",
        },
        {
            "code": "for item in items:\n    result = process(item)\n    if result:\n        output.append(result)",
            "problem": "could be a list comprehension",
            "fix_chain": "select('.for:has(.call#append)').replaceWith('for item in items:\\n    result = process(item)\\n    if result:\\n        output.append(result)', 'output = [r for r in (process(item) for item in items) if r]')",
        },
        {
            "code": "except Exception:\n    pass",
            "problem": "silently swallowing all exceptions",
            "fix_chain": "select('.except:has(pass)').replaceWith('except Exception:\\n    pass', 'except Exception as e:\\n    logger.exception(e)\\n    raise')",
        },
        {
            "code": "print(f'Debug: {user}')",
            "problem": "debug print statement left in code",
            "fix_chain": "select('.call#print').containing('Debug:').replaceWith('print', 'logger.debug')",
        },
    ],
    "go": [
        {
            "code": "result, _ := doSomething()",
            "problem": "error return value ignored",
            "fix_chain": "select('.assign').containing('_ :=').replaceWith('result, _ :=', 'result, err :=')",
        },
        {
            "code": "func ProcessData(data []byte) {\n    json.Unmarshal(data, &result)\n}",
            "problem": "missing error check on json.Unmarshal",
            "fix_chain": "select('.fn#ProcessData').find('.call#Unmarshal').wrap('if err := ', '; err != nil {\\n    return fmt.Errorf(\"unmarshal: %w\", err)\\n}')",
        },
    ],
    "typescript": [
        {
            "code": "const name = user.profile.name",
            "problem": "unsafe property access chain without null checks",
            "fix_chain": "select('.access-member').containing('user.profile.name').replaceWith('user.profile.name', 'user?.profile?.name ?? \"Unknown\"')",
        },
        {
            "code": "function fetchData(url: string): any {\n    return fetch(url).then(r => r.json())\n}",
            "problem": "return type is 'any', should be typed",
            "fix_chain": "select('.fn#fetchData').returnType('Promise<Data>').replaceWith(': any', ': Promise<Data>')",
        },
    ],
}


def sample_selector_for_language(rng: random.Random, language: str) -> str:
    """Sample a selector using language-appropriate names."""
    if language == "go":
        names = GO_FUNCTION_NAMES
        classes = GO_CLASS_NAMES
    elif language == "typescript":
        names = TS_FUNCTION_NAMES
        classes = TS_CLASS_NAMES
    else:
        names = FUNCTION_NAMES
        classes = CLASS_NAMES

    node = rng.choice(_NODE_TYPES)
    roll = rng.random()
    if roll < 0.40:
        return node
    elif roll < 0.70:
        if node in (".fn", ".call"):
            name = rng.choice(names)
        elif node == ".cls":
            name = rng.choice(classes)
        else:
            name = rng.choice(names)
        return f"{node}#{name}"
    elif roll < 0.85:
        pseudo = rng.choice(_PSEUDO_SELECTORS)
        return f"{node}{pseudo}"
    else:
        attr = rng.choice(_ATTR_PATTERNS)
        return f"{node}{attr}"


def sample_module_path_for_language(rng: random.Random, language: str) -> str:
    """Sample a module path appropriate for the language."""
    if language == "go":
        return rng.choice(GO_MODULE_PATHS)
    elif language == "typescript":
        return rng.choice(TS_MODULE_PATHS)
    return rng.choice(MODULE_PATHS)


def sample_error_context(rng: random.Random, language: str | None = None) -> dict[str, str]:
    """Sample an error message with file/function/line context."""
    if language is None:
        language = rng.choice(["python", "go", "typescript"])
    errors = ERROR_MESSAGES.get(language, ERROR_MESSAGES["python"])
    return {**rng.choice(errors), "language": language}


def sample_code_context(rng: random.Random, language: str | None = None) -> dict[str, str]:
    """Sample a code snippet with problem description and fix chain."""
    if language is None:
        language = rng.choice(["python", "go", "typescript"])
    snippets = CODE_CONTEXT_SNIPPETS.get(language, CODE_CONTEXT_SNIPPETS["python"])
    return {**rng.choice(snippets), "language": language}
