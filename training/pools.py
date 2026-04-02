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
