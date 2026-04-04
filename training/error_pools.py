"""Error message and code context pools for training data generation.

Separated from pools.py for maintainability. Each entry represents a real
bug pattern a developer would encounter, with a plausible fix chain.

Each error entry has:
    error: str       — the error message
    file: str        — file path where it occurs
    function: str    — function name (or None for module-level)
    line: str        — line number
    fix_op: str      — the primary pluckit operation to fix it

Each code context entry has:
    code: str        — the buggy code snippet
    problem: str     — natural language problem description
    fix_chain: str   — the pluckit chain that fixes it
"""
from __future__ import annotations

# =============================================================================
# ERROR MESSAGES — realistic error messages with fix metadata
# =============================================================================

ERROR_MESSAGES: dict[str, list[dict[str, str]]] = {
    "python": [
        # --- TypeError ---
        {"error": "TypeError: argument 'token' expected str, got None", "file": "src/auth.py", "function": "validate_token", "line": "23", "fix_op": "prepend"},
        {"error": "TypeError: unsupported operand type(s) for +: 'int' and 'str'", "file": "src/utils.py", "function": "format_output", "line": "45", "fix_op": "replaceWith"},
        {"error": "TypeError: 'NoneType' object is not iterable", "file": "src/data.py", "function": "process_data", "line": "31", "fix_op": "prepend"},
        {"error": "TypeError: expected str, bytes or os.PathLike object, not NoneType", "file": "src/io.py", "function": "read_file", "line": "12", "fix_op": "prepend"},
        {"error": "TypeError: __init__() missing 1 required positional argument: 'db'", "file": "src/services.py", "function": "AuthService", "line": "8", "fix_op": "replaceWith"},
        {"error": "TypeError: object of type 'int' has no len()", "file": "src/validate.py", "function": "validate_input", "line": "19", "fix_op": "replaceWith"},
        {"error": "TypeError: can't multiply sequence by non-int of type 'float'", "file": "src/math_utils.py", "function": "scale_values", "line": "7", "fix_op": "replaceWith"},
        {"error": "TypeError: unhashable type: 'list'", "file": "src/cache.py", "function": "cache_result", "line": "34", "fix_op": "replaceWith"},

        # --- AttributeError ---
        {"error": "AttributeError: 'NoneType' has no attribute 'decode'", "file": "src/auth.py", "function": "decode_jwt", "line": "47", "fix_op": "prepend"},
        {"error": "AttributeError: 'NoneType' has no attribute 'strip'", "file": "src/parser.py", "function": "parse_header", "line": "22", "fix_op": "prepend"},
        {"error": "AttributeError: 'dict' object has no attribute 'name'", "file": "src/models.py", "function": "get_user", "line": "55", "fix_op": "replaceWith"},
        {"error": "AttributeError: 'NoneType' has no attribute 'id'", "file": "src/api/handlers.py", "function": "get_profile", "line": "28", "fix_op": "prepend"},
        {"error": "AttributeError: 'list' object has no attribute 'items'", "file": "src/serialize.py", "function": "to_dict", "line": "14", "fix_op": "replaceWith"},
        {"error": "AttributeError: module 'json' has no attribute 'loads_safe'", "file": "src/config.py", "function": "load_config", "line": "3", "fix_op": "replaceWith"},

        # --- KeyError ---
        {"error": "KeyError: 'user_id'", "file": "src/api/handlers.py", "function": "get_user", "line": "31", "fix_op": "replaceWith"},
        {"error": "KeyError: 'email'", "file": "src/auth.py", "function": "authenticate_user", "line": "42", "fix_op": "replaceWith"},
        {"error": "KeyError: 'status'", "file": "src/api/client.py", "function": "fetch_resource", "line": "67", "fix_op": "wrap"},
        {"error": "KeyError: 'Authorization'", "file": "src/middleware.py", "function": "auth_middleware", "line": "15", "fix_op": "replaceWith"},

        # --- ValueError ---
        {"error": "ValueError: invalid literal for int() with base 10: 'abc'", "file": "src/utils.py", "function": "parse_int", "line": "15", "fix_op": "wrap"},
        {"error": "ValueError: not enough values to unpack (expected 3, got 2)", "file": "src/parser.py", "function": "parse_csv_row", "line": "44", "fix_op": "prepend"},
        {"error": "ValueError: math domain error", "file": "src/math_utils.py", "function": "compute_log", "line": "8", "fix_op": "prepend"},
        {"error": "ValueError: could not convert string to float: 'N/A'", "file": "src/data.py", "function": "normalize_payload", "line": "29", "fix_op": "wrap"},

        # --- ConnectionError / IOError ---
        {"error": "ConnectionError: Failed to connect to database", "file": "src/db/client.py", "function": "query_database", "line": "88", "fix_op": "guard"},
        {"error": "ConnectionRefusedError: [Errno 111] Connection refused", "file": "src/api/client.py", "function": "fetch_resource", "line": "23", "fix_op": "guard"},
        {"error": "TimeoutError: Request timed out after 30s", "file": "src/api/client.py", "function": "send_request", "line": "56", "fix_op": "guard"},
        {"error": "ConnectionResetError: [Errno 104] Connection reset by peer", "file": "src/net/socket.py", "function": "read_response", "line": "78", "fix_op": "guard"},

        # --- ImportError ---
        {"error": "ImportError: cannot import name 'Optional' from 'typing'", "file": "src/models.py", "function": None, "line": "1", "fix_op": "replaceWith"},
        {"error": "ModuleNotFoundError: No module named 'yaml'", "file": "src/config.py", "function": None, "line": "2", "fix_op": "replaceWith"},

        # --- FileNotFoundError ---
        {"error": "FileNotFoundError: [Errno 2] No such file or directory: 'config.yaml'", "file": "src/config.py", "function": "load_config", "line": "12", "fix_op": "wrap"},
        {"error": "FileNotFoundError: [Errno 2] No such file or directory: '/tmp/data.csv'", "file": "src/data.py", "function": "read_file", "line": "5", "fix_op": "wrap"},
        {"error": "PermissionError: [Errno 13] Permission denied: '/var/log/app.log'", "file": "src/logging.py", "function": "setup_logging", "line": "20", "fix_op": "wrap"},

        # --- RecursionError ---
        {"error": "RecursionError: maximum recursion depth exceeded", "file": "src/tree.py", "function": "traverse", "line": "42", "fix_op": "prepend"},

        # --- IndexError ---
        {"error": "IndexError: list index out of range", "file": "src/data.py", "function": "get_first_item", "line": "11", "fix_op": "prepend"},
        {"error": "IndexError: string index out of range", "file": "src/parser.py", "function": "parse_header", "line": "35", "fix_op": "prepend"},

        # --- RuntimeError ---
        {"error": "RuntimeError: dictionary changed size during iteration", "file": "src/cache.py", "function": "evict_expired", "line": "28", "fix_op": "replaceWith"},
        {"error": "RuntimeError: Event loop is closed", "file": "src/async_utils.py", "function": "run_async", "line": "15", "fix_op": "wrap"},

        # --- ZeroDivisionError ---
        {"error": "ZeroDivisionError: division by zero", "file": "src/math_utils.py", "function": "compute_average", "line": "9", "fix_op": "prepend"},

        # --- StopIteration ---
        {"error": "StopIteration", "file": "src/iter.py", "function": "get_next", "line": "22", "fix_op": "wrap"},

        # --- AssertionError ---
        {"error": "AssertionError: expected status 200, got 404", "file": "tests/test_api.py", "function": "test_get_user", "line": "45", "fix_op": "replaceWith"},

        # --- UnicodeDecodeError ---
        {"error": "UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff in position 0", "file": "src/io.py", "function": "read_file", "line": "18", "fix_op": "replaceWith"},
    ],

    "go": [
        # --- Nil pointer ---
        {"error": "panic: runtime error: invalid memory address or nil pointer dereference", "file": "main.go", "function": "ProcessUser", "line": "23", "fix_op": "prepend"},
        {"error": "panic: runtime error: invalid memory address or nil pointer dereference", "file": "handlers/api.go", "function": "HandleRequest", "line": "67", "fix_op": "prepend"},
        {"error": "panic: runtime error: invalid memory address or nil pointer dereference", "file": "internal/db/query.go", "function": "QueryUsers", "line": "42", "fix_op": "prepend"},
        {"error": "panic: runtime error: invalid memory address or nil pointer dereference", "file": "pkg/auth/token.go", "function": "ValidateToken", "line": "31", "fix_op": "prepend"},

        # --- Type errors ---
        {"error": "cannot use x (variable of type string) as type int in argument", "file": "handlers/api.go", "function": "HandleRequest", "line": "45", "fix_op": "replaceWith"},
        {"error": "cannot use result (variable of type *User) as type User in return statement", "file": "internal/user.go", "function": "GetUser", "line": "38", "fix_op": "replaceWith"},
        {"error": "cannot convert data (variable of type []byte) to type string", "file": "pkg/parser.go", "function": "ParseConfig", "line": "22", "fix_op": "replaceWith"},

        # --- Undefined ---
        {"error": "undefined: ctx", "file": "service/auth.go", "function": "ValidateInput", "line": "18", "fix_op": "addParam"},
        {"error": "undefined: err", "file": "handlers/webhook.go", "function": "HandleWebhook", "line": "33", "fix_op": "replaceWith"},

        # --- Error handling ---
        {"error": "err is shadowed during return", "file": "pkg/db/query.go", "function": "QueryUsers", "line": "33", "fix_op": "replaceWith"},
        {"error": "error return value is not checked", "file": "cmd/server.go", "function": "StartServer", "line": "15", "fix_op": "wrap"},
        {"error": "error return value of 'json.Unmarshal' is not checked", "file": "internal/config.go", "function": "ParseConfig", "line": "27", "fix_op": "wrap"},
        {"error": "error return value of 'rows.Close' is not checked", "file": "internal/db/query.go", "function": "FetchAll", "line": "55", "fix_op": "replaceWith"},

        # --- Interface errors ---
        {"error": "cannot use s (*Server) as type http.Handler: missing method ServeHTTP", "file": "cmd/server.go", "function": "NewServer", "line": "12", "fix_op": "addMethod"},
        {"error": "cannot use c (*Client) as type io.Closer: missing method Close", "file": "pkg/client.go", "function": "NewClient", "line": "20", "fix_op": "addMethod"},

        # --- Import errors ---
        {"error": "imported and not used: \"fmt\"", "file": "internal/utils.go", "function": None, "line": "4", "fix_op": "removeImport"},
        {"error": "imported and not used: \"os\"", "file": "cmd/main.go", "function": None, "line": "5", "fix_op": "removeImport"},

        # --- Race conditions ---
        {"error": "WARNING: DATA RACE: Write at 0x00c000012345 by goroutine 7", "file": "internal/cache.go", "function": "SetCache", "line": "44", "fix_op": "wrap"},

        # --- Bounds checking ---
        {"error": "panic: runtime error: index out of range [5] with length 3", "file": "internal/data.go", "function": "ProcessBatch", "line": "28", "fix_op": "prepend"},

        # --- Goroutine leaks ---
        {"error": "goroutine leak detected: 15 goroutines still running after test", "file": "internal/worker.go", "function": "StartWorker", "line": "50", "fix_op": "wrap"},
    ],

    "typescript": [
        # --- Property access ---
        {"error": "TypeError: Cannot read properties of undefined (reading 'name')", "file": "src/utils.ts", "function": "getDisplayName", "line": "15", "fix_op": "replaceWith"},
        {"error": "TypeError: Cannot read properties of null (reading 'id')", "file": "src/services/user.ts", "function": "fetchUser", "line": "28", "fix_op": "prepend"},
        {"error": "TypeError: Cannot read properties of undefined (reading 'length')", "file": "src/utils.ts", "function": "filterRecords", "line": "42", "fix_op": "prepend"},
        {"error": "TypeError: Cannot read properties of undefined (reading 'map')", "file": "src/components/List.tsx", "function": "renderComponent", "line": "33", "fix_op": "prepend"},

        # --- Type assignment ---
        {"error": "Type 'string | undefined' is not assignable to type 'string'", "file": "src/services/user.ts", "function": "fetchUser", "line": "28", "fix_op": "replaceWith"},
        {"error": "Type 'null' is not assignable to type 'User'", "file": "src/components/Profile.tsx", "function": "renderComponent", "line": "55", "fix_op": "replaceWith"},
        {"error": "Type 'number' is not assignable to type 'string'", "file": "src/api/client.ts", "function": "formatDate", "line": "12", "fix_op": "replaceWith"},
        {"error": "Type 'any' is not assignable to type 'never'", "file": "src/state/reducer.ts", "function": "dispatchAction", "line": "48", "fix_op": "annotate"},

        # --- Property existence ---
        {"error": "Property 'status' does not exist on type 'Response'", "file": "src/api/client.ts", "function": "handleError", "line": "42", "fix_op": "annotate"},
        {"error": "Property 'email' does not exist on type '{}'", "file": "src/services/auth.ts", "function": "validateSchema", "line": "18", "fix_op": "annotate"},
        {"error": "Property 'data' does not exist on type 'AxiosResponse'", "file": "src/api/client.ts", "function": "fetchUser", "line": "23", "fix_op": "replaceWith"},

        # --- Argument errors ---
        {"error": "Argument of type 'null' is not assignable to parameter of type 'User'", "file": "src/components/Profile.tsx", "function": "renderComponent", "line": "55", "fix_op": "replaceWith"},
        {"error": "Expected 2 arguments, but got 1", "file": "src/services/api.ts", "function": "sendMessage", "line": "30", "fix_op": "replaceWith"},
        {"error": "Expected 0 arguments, but got 1", "file": "src/utils.ts", "function": "generateToken", "line": "8", "fix_op": "replaceWith"},

        # --- Promise errors ---
        {"error": "TypeError: response.json is not a function", "file": "src/api/client.ts", "function": "fetchUser", "line": "19", "fix_op": "replaceWith"},
        {"error": "Unhandled promise rejection: Error: Network request failed", "file": "src/api/client.ts", "function": "retryRequest", "line": "45", "fix_op": "wrap"},
        {"error": "TypeError: Cannot read properties of undefined (reading 'then')", "file": "src/services/data.ts", "function": "transformData", "line": "22", "fix_op": "prepend"},

        # --- Import errors ---
        {"error": "Module '\"./types\"' has no exported member 'UserResponse'", "file": "src/services/user.ts", "function": None, "line": "1", "fix_op": "replaceWith"},
        {"error": "Cannot find module './config' or its corresponding type declarations", "file": "src/app.ts", "function": None, "line": "3", "fix_op": "replaceWith"},

        # --- Runtime errors ---
        {"error": "RangeError: Maximum call stack size exceeded", "file": "src/utils.ts", "function": "deepClone", "line": "5", "fix_op": "prepend"},
        {"error": "TypeError: Assignment to constant variable", "file": "src/state/store.ts", "function": "updateState", "line": "38", "fix_op": "replaceWith"},
    ],
}


# =============================================================================
# CODE CONTEXT SNIPPETS — buggy code with problem descriptions and fix chains
# =============================================================================

CODE_CONTEXT_SNIPPETS: dict[str, list[dict[str, str]]] = {
    "python": [
        # --- None returns ---
        {
            "code": "def validate_token(token):\n    if not token:\n        return None\n    return token.decode()",
            "problem": "returns None silently instead of raising",
            "fix_chain": "select('.fn#validate_token').replaceWith('return None', 'raise ValueError(\"token required\")')",
        },
        {
            "code": "def get_user(user_id):\n    user = db.find(user_id)\n    return user",
            "problem": "returns None when user not found, should raise NotFoundError",
            "fix_chain": "select('.fn#get_user').prepend('if user is None:\\n    raise NotFoundError(f\"user {user_id} not found\")')",
        },
        {
            "code": "def parse_config(path):\n    if not os.path.exists(path):\n        return {}\n    return yaml.safe_load(open(path))",
            "problem": "silently returns empty dict on missing config instead of raising",
            "fix_chain": "select('.fn#parse_config').replaceWith('return {}', 'raise FileNotFoundError(f\"config not found: {path}\")')",
        },

        # --- SQL injection ---
        {
            "code": "db.execute(f'SELECT * FROM users WHERE id={user_id}')",
            "problem": "SQL injection via string formatting",
            "fix_chain": "select('.call#execute').containing(\"f'SELECT\").replaceWith(\"f'SELECT * FROM users WHERE id={user_id}'\", \"'SELECT * FROM users WHERE id=?', (user_id,)\")",
        },
        {
            "code": "cursor.execute(\"DELETE FROM orders WHERE status='\" + status + \"'\")",
            "problem": "SQL injection via string concatenation",
            "fix_chain": "select('.call#execute').containing('+ status +').replaceWith(\"\\\"DELETE FROM orders WHERE status='\\\" + status + \\\"'\\\"\", \"'DELETE FROM orders WHERE status=?', (status,)\")",
        },

        # --- Exception swallowing ---
        {
            "code": "except Exception:\n    pass",
            "problem": "silently swallowing all exceptions",
            "fix_chain": "select('.except:has(pass)').replaceWith('except Exception:\\n    pass', 'except Exception as e:\\n    logger.exception(e)\\n    raise')",
        },
        {
            "code": "try:\n    result = api.fetch(url)\nexcept:\n    result = None",
            "problem": "bare except catches everything including KeyboardInterrupt",
            "fix_chain": "select('.try').containing('except:').replaceWith('except:', 'except Exception as e:\\n    logger.warning(f\"fetch failed: {e}\")')",
        },
        {
            "code": "try:\n    data = json.loads(raw)\nexcept Exception:\n    return default",
            "problem": "catching too broadly — should only catch JSONDecodeError",
            "fix_chain": "select('.except').containing('Exception').replaceWith('except Exception:', 'except json.JSONDecodeError:')",
        },

        # --- Debug leftovers ---
        {
            "code": "print(f'Debug: {user}')",
            "problem": "debug print statement left in production code",
            "fix_chain": "select('.call#print').containing('Debug:').replaceWith('print', 'logger.debug')",
        },
        {
            "code": "import pdb; pdb.set_trace()",
            "problem": "debugger breakpoint left in code",
            "fix_chain": "select('.call#set_trace').parent().remove()",
        },
        {
            "code": "# TODO: remove this before release\ntime.sleep(5)",
            "problem": "intentional delay left in code",
            "fix_chain": "select('.call#sleep').parent().remove()",
        },

        # --- Resource leaks ---
        {
            "code": "f = open('data.txt')\ndata = f.read()\nreturn data",
            "problem": "file handle never closed",
            "fix_chain": "select('.call#open').ancestor('.fn').replaceWith('f = open', 'with open').wrap('with open(\\'data.txt\\') as f:', '')",
        },
        {
            "code": "conn = db.connect()\nresult = conn.execute(query)\nreturn result",
            "problem": "database connection never closed",
            "fix_chain": "select('.call#connect').ancestor('.fn').wrap('with db.connect() as conn:', '')",
        },

        # --- Mutable default arguments ---
        {
            "code": "def process(items=[]):\n    items.append('done')\n    return items",
            "problem": "mutable default argument — shared between calls",
            "fix_chain": "select('.fn#process').replaceWith('items=[]', 'items=None').prepend('if items is None:\\n    items = []')",
        },

        # --- String formatting ---
        {
            "code": "msg = 'Hello ' + name + ', you have ' + str(count) + ' items'",
            "problem": "string concatenation instead of f-string",
            "fix_chain": "select('.assign#msg').replaceWith(\"'Hello ' + name + ', you have ' + str(count) + ' items'\", \"f'Hello {name}, you have {count} items'\")",
        },

        # --- Equality vs identity ---
        {
            "code": "if result == None:\n    return False",
            "problem": "using == instead of 'is' for None comparison",
            "fix_chain": "select('.if').containing('== None').replaceWith('== None', 'is None')",
        },

        # --- Missing return type ---
        {
            "code": "def validate_email(email):\n    return '@' in email and '.' in email",
            "problem": "missing return type annotation",
            "fix_chain": "select('.fn#validate_email').returnType('bool')",
        },

        # --- Hardcoded values ---
        {
            "code": "if retry_count > 3:\n    raise MaxRetriesError()",
            "problem": "hardcoded retry limit should be configurable",
            "fix_chain": "select('.fn').ancestor('.fn').addParam('max_retries: int = 3').find('.if').containing('> 3').replaceWith('> 3', '> max_retries')",
        },

        # --- Missing async/await ---
        {
            "code": "async def fetch_data(url):\n    response = requests.get(url)\n    return response.json()",
            "problem": "async function using synchronous requests",
            "fix_chain": "select('.fn#fetch_data').replaceWith('requests.get(url)', 'await httpx.get(url)').ensureImport('import httpx')",
        },

        # --- Dangerous defaults ---
        {
            "code": "def delete_user(user_id, force=True):\n    db.delete(user_id)",
            "problem": "destructive operation defaults to force=True",
            "fix_chain": "select('.fn#delete_user').replaceWith('force=True', 'force=False')",
        },

        # --- Missing validation ---
        {
            "code": "def transfer(amount, from_acct, to_acct):\n    from_acct.balance -= amount\n    to_acct.balance += amount",
            "problem": "no validation that amount is positive or that from_acct has sufficient balance",
            "fix_chain": "select('.fn#transfer').prepend('if amount <= 0:\\n    raise ValueError(\"amount must be positive\")\\nif from_acct.balance < amount:\\n    raise ValueError(\"insufficient balance\")')",
        },

        # --- Race condition ---
        {
            "code": "if key not in cache:\n    cache[key] = compute_expensive(key)\nreturn cache[key]",
            "problem": "race condition in cache check-then-set",
            "fix_chain": "select('.if').containing('not in cache').ancestor('.fn').wrap('with cache_lock:', '')",
        },
    ],

    "go": [
        # --- Error ignored ---
        {
            "code": "result, _ := doSomething()",
            "problem": "error return value ignored",
            "fix_chain": "select('.assign').containing('_ :=').replaceWith('result, _ :=', 'result, err :=')",
        },
        {
            "code": "json.Unmarshal(data, &result)",
            "problem": "error return value of json.Unmarshal not checked",
            "fix_chain": "select('.call#Unmarshal').ancestor('.fn').find('.call#Unmarshal').wrap('if err := ', '; err != nil {\\n    return fmt.Errorf(\"unmarshal: %w\", err)\\n}')",
        },
        {
            "code": "resp, _ := http.Get(url)",
            "problem": "HTTP error ignored",
            "fix_chain": "select('.call#Get').ancestor('.fn').replaceWith('resp, _ := http.Get(url)', 'resp, err := http.Get(url)\\nif err != nil {\\n    return nil, fmt.Errorf(\"GET %s: %w\", url, err)\\n}')",
        },
        {
            "code": "defer rows.Close()",
            "problem": "error from rows.Close not checked",
            "fix_chain": "select('.call#Close').containing('rows.Close').replaceWith('defer rows.Close()', 'defer func() {\\n    if err := rows.Close(); err != nil {\\n        log.Printf(\"close rows: %v\", err)\\n    }\\n}()')",
        },
        {
            "code": "file, _ := os.Open(path)\ndefer file.Close()",
            "problem": "os.Open error ignored, will panic on nil file",
            "fix_chain": "select('.call#Open').ancestor('.fn').replaceWith('file, _ := os.Open(path)', 'file, err := os.Open(path)\\nif err != nil {\\n    return fmt.Errorf(\"open %s: %w\", path, err)\\n}')",
        },

        # --- Nil pointer ---
        {
            "code": "func ProcessUser(u *User) {\n    fmt.Println(u.Name)\n}",
            "problem": "no nil check on pointer parameter",
            "fix_chain": "select('.fn#ProcessUser').prepend('if u == nil {\\n    return\\n}')",
        },
        {
            "code": "func GetConfig() *Config {\n    return configs[env]\n}",
            "problem": "returns nil if env not in map, caller will dereference nil",
            "fix_chain": "select('.fn#GetConfig').replaceWith('return configs[env]', 'cfg, ok := configs[env]\\nif !ok {\\n    return nil, fmt.Errorf(\"unknown env: %s\", env)\\n}\\nreturn cfg, nil')",
        },

        # --- Missing context ---
        {
            "code": "func ValidateInput(data []byte) error {\n    // ...\n}",
            "problem": "missing context.Context parameter — can't cancel or set deadline",
            "fix_chain": "select('.fn#ValidateInput').addParam('ctx context.Context', before='*')",
        },
        {
            "code": "func QueryDB(query string) (*sql.Rows, error) {\n    return db.Query(query)\n}",
            "problem": "missing context.Context — can't cancel long-running queries",
            "fix_chain": "select('.fn#QueryDB').addParam('ctx context.Context', before='*').replaceWith('db.Query(query)', 'db.QueryContext(ctx, query)')",
        },

        # --- Goroutine problems ---
        {
            "code": "for _, item := range items {\n    go process(item)\n}",
            "problem": "loop variable captured by goroutine — all goroutines see last item",
            "fix_chain": "select('.for:has(.call#go)').replaceWith('go process(item)', 'item := item\\n    go process(item)')",
        },
        {
            "code": "go func() {\n    result <- compute()\n}()",
            "problem": "goroutine has no error recovery — panic will crash the process",
            "fix_chain": "select('.call').containing('go func').prepend('defer func() {\\n    if r := recover(); r != nil {\\n        log.Printf(\"goroutine panic: %v\", r)\\n    }\\n}()')",
        },

        # --- Resource leaks ---
        {
            "code": "resp, err := http.Get(url)\nif err != nil {\n    return err\n}\nbody, err := io.ReadAll(resp.Body)",
            "problem": "resp.Body never closed",
            "fix_chain": "select('.call#Get').ancestor('.fn').find('.call#ReadAll').prepend('defer resp.Body.Close()')",
        },

        # --- Mutex issues ---
        {
            "code": "func (c *Cache) Get(key string) interface{} {\n    return c.data[key]\n}",
            "problem": "concurrent map read without mutex",
            "fix_chain": "select('.fn#Get').prepend('c.mu.RLock()\\ndefer c.mu.RUnlock()')",
        },

        # --- String formatting ---
        {
            "code": "log.Printf(\"user: \" + user.Name)",
            "problem": "string concatenation in Printf instead of format directive",
            "fix_chain": "select('.call#Printf').containing('\" +').replaceWith('\"user: \" + user.Name', '\"user: %s\", user.Name')",
        },
    ],

    "typescript": [
        # --- Unsafe property access ---
        {
            "code": "const name = user.profile.name",
            "problem": "unsafe property access chain without null checks",
            "fix_chain": "select('.access-member').containing('user.profile.name').replaceWith('user.profile.name', 'user?.profile?.name ?? \"Unknown\"')",
        },
        {
            "code": "const email = data.user.email.toLowerCase()",
            "problem": "chained property access without null checks",
            "fix_chain": "select('.access-member').containing('data.user.email').replaceWith('data.user.email.toLowerCase()', 'data?.user?.email?.toLowerCase() ?? \"\"')",
        },
        {
            "code": "const items = response.data.items.map(transform)",
            "problem": "assumes response.data.items is always an array",
            "fix_chain": "select('.call#map').ancestor('.assign').replaceWith('response.data.items.map(transform)', '(response?.data?.items ?? []).map(transform)')",
        },

        # --- Any types ---
        {
            "code": "function fetchData(url: string): any {\n    return fetch(url).then(r => r.json())\n}",
            "problem": "return type is 'any', should be typed",
            "fix_chain": "select('.fn#fetchData').returnType('Promise<Data>').replaceWith(': any', ': Promise<Data>')",
        },
        {
            "code": "function parseResponse(data: any): any {\n    return JSON.parse(data)\n}",
            "problem": "both parameter and return type are 'any'",
            "fix_chain": "select('.fn#parseResponse').replaceWith('data: any): any', 'data: string): Record<string, unknown>')",
        },
        {
            "code": "const result: any = await api.get('/users')",
            "problem": "result typed as 'any' loses type safety",
            "fix_chain": "select('.assign#result').replaceWith(': any', ': User[]')",
        },

        # --- Missing null checks ---
        {
            "code": "function getUser(id: string): User {\n    return users.find(u => u.id === id)!\n}",
            "problem": "non-null assertion (!) hides potential undefined",
            "fix_chain": "select('.fn#getUser').replaceWith('users.find(u => u.id === id)!', 'users.find(u => u.id === id) ?? throwNotFound(`user ${id}`)')",
        },
        {
            "code": "const value = localStorage.getItem('token')\nfetch(url, { headers: { Authorization: value } })",
            "problem": "localStorage.getItem can return null",
            "fix_chain": "select('.call#getItem').ancestor('.fn').prepend('if (value === null) throw new Error(\"no token\")')",
        },

        # --- Promise errors ---
        {
            "code": "async function loadData() {\n    const data = await fetch(url)\n    return data.json()\n}",
            "problem": "no error handling on fetch — network errors will propagate",
            "fix_chain": "select('.fn#loadData').wrap('try {', '} catch (e) {\\n    console.error(\"load failed:\", e)\\n    return null\\n}')",
        },
        {
            "code": "promise.then(handle).catch(console.log)",
            "problem": "error handler just logs to console — should handle properly",
            "fix_chain": "select('.call#catch').replaceWith('console.log', '(err) => { reportError(err); throw err; }')",
        },

        # --- State mutation ---
        {
            "code": "function addItem(state: State, item: Item) {\n    state.items.push(item)\n    return state\n}",
            "problem": "mutates state directly instead of creating a new copy",
            "fix_chain": "select('.fn#addItem').replaceWith('state.items.push(item)\\n    return state', 'return { ...state, items: [...state.items, item] }')",
        },
        {
            "code": "const sorted = items.sort((a, b) => a.date - b.date)",
            "problem": "sort() mutates the original array",
            "fix_chain": "select('.call#sort').replaceWith('items.sort(', '[...items].sort(')",
        },

        # --- Event listener leaks ---
        {
            "code": "useEffect(() => {\n    window.addEventListener('resize', handleResize)\n})",
            "problem": "event listener never cleaned up — memory leak",
            "fix_chain": "select('.call#addEventListener').ancestor('.call#useEffect').replaceWith('})', 'return () => window.removeEventListener(\"resize\", handleResize)\\n})')",
        },

        # --- Type assertions ---
        {
            "code": "const user = data as User",
            "problem": "unsafe type assertion without validation",
            "fix_chain": "select('.assign#user').replaceWith('data as User', 'isUser(data) ? data : throwTypeError(\"expected User\")')",
        },

        # --- Import issues ---
        {
            "code": "import { UserService } from '../services'\nimport { UserService } from '../services/user'",
            "problem": "duplicate import of UserService from different paths",
            "fix_chain": "select('.import#UserService').at_line(1).remove()",
        },

        # --- Callback hell ---
        {
            "code": "getData(id, (data) => {\n    process(data, (result) => {\n        save(result, (status) => {\n            callback(status)\n        })\n    })\n})",
            "problem": "deeply nested callbacks — should use async/await",
            "fix_chain": "select('.fn:has(.fn:has(.fn))').replaceWith('getData(id, (data) => {', 'const data = await getData(id)\\nconst result = await process(data)\\nconst status = await save(result)\\ncallback(status)')",
        },
    ],
}
