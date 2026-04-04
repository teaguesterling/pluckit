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
    ":named",
    ":void",
    ":typed",
    ":variadic",
    ":static",
    ":const",
    ":public",
    ":private",
    ":is-called",
    ":is-referenced",
    ":unreferenced",
    ":definition",
    ":reference",
    ":scope",
]

# Pseudo-classes that take arguments
_PSEUDO_WITH_ARGS: list[tuple[str, list[str]]] = [
    (":calls", [
        "execute", "query", "fetch", "print", "validate", "process",
        "connect", "send", "read", "write", "parse", "serialize",
        "authenticate", "authorize", "log", "emit", "dispatch",
    ]),
    (":called-by", [
        "main", "handle_request", "process_data", "run", "setup",
        "test_validate", "init", "start", "execute",
    ]),
    (":scope", [
        "function", "class", "module", "loop", "if", "try",
    ]),
    (":matches", [
        '"return None"',
        '"self.___ = ___"',
        '"db.execute()"',
        '"raise ValueError"',
        '"logger.debug()"',
        '"await ___"',
        '"for ___ in ___"',
        '"if ___ is None"',
        '"except Exception"',
        '"print()"',
        '"os.path.join()"',
        '"json.loads()"',
    ]),
    (":nth-child", ["1", "2", "3"]),
    (":precedes", ["function_definition", "class_definition", "import"]),
    (":follows", ["import", "class", "function"]),
]

# Pseudo-elements for navigation
_PSEUDO_ELEMENTS: list[str] = [
    "::callers",
    "::callees",
    "::parent",
    "::scope",
    "::parent-definition",
    "::next-sibling",
    "::prev-sibling",
]

_ATTR_PATTERNS: list[str] = [
    '[name^="test_"]',
    '[name$="_handler"]',
    '[name*="process"]',
    '[name="main"]',
    '[name^="get_"]',
    '[name$="_service"]',
    '[name^="validate_"]',
    '[annotation*="pytest"]',
    '[annotation*="route"]',
    '[modifier=async]',
    '[modifier=static]',
    '[signature=int]',
    '[signature=bool]',
    '[params=0]',
    '[params=2]',
    '[peek*="SELECT"]',
    '[peek*="TODO"]',
    '[qualified*="auth."]',
]

# ---------------------------------------------------------------------------
# Selector sampling functions
# ---------------------------------------------------------------------------

def sample_selector(rng: random.Random) -> str:
    """Sample a single CSS-like selector.

    Distribution:
    - 25%  bare type              e.g. ``.fn``
    - 20%  with name              e.g. ``.fn#validate_token``
    - 15%  with pseudo-class      e.g. ``.fn:exported``
    - 10%  with pseudo-class+arg  e.g. ``.func:calls(execute)``
    - 10%  with attribute         e.g. ``.fn[name^="test_"]``
    - 10%  with pseudo-element    e.g. ``.fn#main::callees``
    - 10%  compound               e.g. ``.func:named:unreferenced``
    """
    node = rng.choice(_NODE_TYPES)
    roll = rng.random()
    if roll < 0.25:
        return node
    elif roll < 0.45:
        name = rng.choice(FUNCTION_NAMES)
        return f"{node}#{name}"
    elif roll < 0.60:
        pseudo = rng.choice(_PSEUDO_SELECTORS)
        return f"{node}{pseudo}"
    elif roll < 0.70:
        # Pseudo-class with argument
        pseudo_name, arg_pool = rng.choice(_PSEUDO_WITH_ARGS)
        arg = rng.choice(arg_pool)
        return f"{node}{pseudo_name}({arg})"
    elif roll < 0.80:
        attr = rng.choice(_ATTR_PATTERNS)
        return f"{node}{attr}"
    elif roll < 0.90:
        # Pseudo-element (navigation)
        name = rng.choice(FUNCTION_NAMES)
        pe = rng.choice(_PSEUDO_ELEMENTS)
        return f"{node}#{name}{pe}"
    else:
        # Compound: two pseudo-classes
        p1 = rng.choice(_PSEUDO_SELECTORS)
        p2 = rng.choice([p for p in _PSEUDO_SELECTORS if p != p1])
        return f"{node}{p1}{p2}"


def sample_composed_selector(rng: random.Random) -> str:
    """Sample a composed CSS-like selector.

    Distribution:
    - 30%  descendant   ``A B``
    - 15%  child        ``A > B``
    - 15%  :has()       ``A:has(B)``
    - 15%  :not(:has()) ``A:not(:has(B))``
    - 15%  :calls + :not(:has()) ``A:calls(X):not(:has(.try))``
    - 10%  :matches + modifier ``A:matches("code"):named``
    """
    a = sample_selector(rng)
    b = sample_selector(rng)
    roll = rng.random()
    if roll < 0.30:
        return f"{a} {b}"
    elif roll < 0.45:
        return f"{a} > {b}"
    elif roll < 0.60:
        return f"{a}:has({b})"
    elif roll < 0.75:
        return f"{a}:not(:has({b}))"
    elif roll < 0.90:
        # :calls + :not(:has()) pattern (common: "calls X without error handling")
        call_name = rng.choice(FUNCTION_NAMES[:20])
        guard = rng.choice([".try", ".catch", ".except", "try_statement"])
        return f".func:calls({call_name}):not(:has({guard}))"
    else:
        # :matches with modifier
        _, args = rng.choice(_PSEUDO_WITH_ARGS[:1])  # :matches args
        if _PSEUDO_WITH_ARGS[3][0] == ":matches":
            _, args = _PSEUDO_WITH_ARGS[3]
        pattern = rng.choice(args)
        modifier = rng.choice([":named", ":exported", ":async", ":void"])
        return f".func:matches({pattern}){modifier}"


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
# TYPE_ANNOTATIONS — for annotate operations
# ---------------------------------------------------------------------------

TYPE_ANNOTATIONS: list[str] = [
    "str", "int", "float", "bool", "bytes",
    "list[str]", "dict[str, Any]", "Optional[str]",
    "None", "bool | None", "str | None",
    "list[dict]", "tuple[int, ...]", "Callable[..., None]",
    "Any",
]

# ---------------------------------------------------------------------------
# ERROR_MESSAGES and CODE_CONTEXT_SNIPPETS — imported from error_pools.py
# (separated for maintainability — 200+ templates across 3 languages)
# ---------------------------------------------------------------------------

from training.error_pools import ERROR_MESSAGES, CODE_CONTEXT_SNIPPETS  # noqa: E402


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
