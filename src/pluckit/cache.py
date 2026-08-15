"""AST parse-tree cache backed by persistent DuckDB tables.

When enabled, ``read_ast`` results are cached in named tables inside
the DuckDB connection. Subsequent queries against the same source
pattern skip re-parsing and query the cached table directly.
Freshness is maintained via file-stat mtime checks with incremental
invalidation (delete stale rows, re-parse only changed files).
"""
from __future__ import annotations

import glob as _glob
import hashlib
import os
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb  # noqa: F401


class ASTCache:
    """Manages cached AST tables on a DuckDB connection."""

    _INDEX_TABLE = "_pluckit_cache_index"

    # Bump when the materialized schema changes, so tables built by an older
    # pluckit are not served to a newer one. Cached tables are keyed by content,
    # not by code version, so without this a cache built before columns were
    # materialized keeps being reused and the new capability silently does
    # nothing — the failure mode is a missing column, not a stale value.
    _SCHEMA_VERSION = 2

    def __init__(self, db, peek: str | None = None) -> None:
        """*peek* is the ``read_ast`` peek extent used when materializing.

        This is the only place the extent can be chosen: ``ast_select`` always
        parses with ``peek := 'none'``, so the cached table — queried later via
        ``ast_select_from`` — is what decides how much source callers can ever
        see. ``None`` keeps sitting_duck's default (``'smart'``, a bounded
        preview). Pass ``'full'`` for minified sources, where a node can be
        thousands of characters on a single line and the preview truncates it.
        """
        self._db = db
        self._peek = peek
        self._ensure_index()

    def _read_ast_call(self, pattern_literal: str) -> str:
        """Render the ``read_ast`` call used to materialize a cache table.

        ``peek := 'none'`` drops the column outright rather than emptying it,
        which would leave a cached table whose schema differs from every other
        one — and ``ast_select_from`` over it fails with "does not have a
        column named peek" rather than simply returning no source text. The
        ``+schema`` suffix keeps the column present and NULL, so a cache table
        has the same shape whatever extent it was built with.

        ``source := 'full'`` is always passed. It is the only way to get
        ``start_column`` / ``end_column`` into the table at all — at any other
        extent they are absent from the schema, not merely zero. On minified
        input those columns are the *only* positional signal that survives:
        every node reports ``start_line = 1``, so line-addressed extraction
        returns the whole file, and character offsets are what isolate a node.
        Two extra integers per row is a cheap price for making the cached table
        usable on the case it exists to serve.
        """
        args = ["source := 'full'"]
        if self._peek:
            peek = self._peek
            if peek.split("+")[0] == "none" and "+schema" not in peek:
                peek = "none+schema"
            args.append(f"peek := '{peek}'")
        return f"read_ast('{pattern_literal}', {', '.join(args)})"

    def _ensure_index(self) -> None:
        self._db.sql(f"""
            CREATE TABLE IF NOT EXISTS {self._INDEX_TABLE} (
                cache_id    VARCHAR PRIMARY KEY,
                pattern     VARCHAR,
                created     DOUBLE,
                files       VARCHAR[],
                total_nodes INTEGER
            )
        """)

    def get_or_create(self, pattern: str) -> str:
        """Return the cache table name for *pattern*, creating or refreshing."""
        cache_id = self._hash_pattern(pattern)
        table_name = f"_pluckit_cache_{cache_id}"

        # Escape for SQL literal
        esc_cache_id = cache_id.replace("'", "''")
        row = self._db.sql(
            f"SELECT files, created FROM {self._INDEX_TABLE} "
            f"WHERE cache_id = '{esc_cache_id}'"
        ).fetchone()

        if row is not None:
            cached_files = row[0] or []
            cached_time = row[1] or 0.0
            stale = self._find_stale_files(cached_files, cached_time)
            if stale:
                self._refresh(table_name, stale, cache_id)
            return table_name

        # Cache miss — create
        resolved_files = self._resolve_pattern(pattern)
        escaped_pattern = pattern.replace("'", "''")

        if not resolved_files:
            # Empty pattern → create empty table with read_ast schema.
            # Use DESCRIBE to get the schema by selecting from a known file.
            self._db.sql(f"""
                CREATE OR REPLACE TABLE {table_name} AS
                SELECT * FROM {self._read_ast_call(escaped_pattern)} WHERE 1=0
            """)
            total = 0
        else:
            self._db.sql(f"""
                CREATE OR REPLACE TABLE {table_name} AS
                SELECT * FROM {self._read_ast_call(escaped_pattern)}
            """)
            total = self._db.sql(f"SELECT count(*) FROM {table_name}").fetchone()[0]

        now = time.time()
        files_literal = self._sql_list(resolved_files)
        self._db.sql(
            f"INSERT INTO {self._INDEX_TABLE} VALUES "
            f"('{esc_cache_id}', '{escaped_pattern}', {now}, "
            f"{files_literal}, {total})"
        )
        return table_name

    def _refresh(self, table_name: str, stale_files: list[str], cache_id: str) -> None:
        """Incrementally update a cached table by re-parsing only stale files."""
        files_in = ", ".join(
            "'" + f.replace("'", "''") + "'" for f in stale_files
        )
        self._db.sql(f"DELETE FROM {table_name} WHERE file_path IN ({files_in})")
        for f in stale_files:
            if os.path.isfile(f):
                esc = f.replace("'", "''")
                try:
                    # Must use the same peek extent the table was built with,
                    # or a refreshed file's rows carry a different amount of
                    # source text than the rest of the table.
                    self._db.sql(
                        f"INSERT INTO {table_name} "
                        f"SELECT * FROM {self._read_ast_call(esc)}"
                    )
                except Exception:
                    pass
        now = time.time()
        esc_cache_id = cache_id.replace("'", "''")
        self._db.sql(
            f"UPDATE {self._INDEX_TABLE} SET created = {now} "
            f"WHERE cache_id = '{esc_cache_id}'"
        )

    def _find_stale_files(self, cached_files: list[str], cached_time: float) -> list[str]:
        """Return files whose mtime is newer than cached_time or that have been deleted."""
        stale = []
        for f in cached_files:
            try:
                if os.path.getmtime(f) > cached_time:
                    stale.append(f)
            except OSError:
                stale.append(f)  # deleted
        return stale

    def _resolve_pattern(self, pattern: str) -> list[str]:
        """Resolve a glob pattern to a sorted list of absolute file paths."""
        files = sorted(_glob.glob(pattern, recursive=True))
        return [os.path.abspath(f) for f in files if os.path.isfile(f)]

    def _hash_pattern(self, pattern: str) -> str:
        """Key the cache on the pattern *and* the peek extent.

        The peek extent is baked into the materialized rows, so two callers
        asking for different extents need different tables. Keying on the
        pattern alone would serve a table built with a bounded preview to a
        caller that asked for full source — a silent wrong answer rather than
        a miss.
        """
        key = f"{pattern}\x00peek={self._peek or ''}\x00v={self._SCHEMA_VERSION}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    def _sql_list(self, items: list[str]) -> str:
        if not items:
            return "CAST([] AS VARCHAR[])"
        escaped = ", ".join("'" + s.replace("'", "''") + "'" for s in items)
        return f"[{escaped}]"
