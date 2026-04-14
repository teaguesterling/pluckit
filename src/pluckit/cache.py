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

    def __init__(self, db) -> None:
        self._db = db
        self._ensure_index()

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
                SELECT * FROM read_ast('{escaped_pattern}') WHERE 1=0
            """)
            total = 0
        else:
            self._db.sql(f"""
                CREATE OR REPLACE TABLE {table_name} AS
                SELECT * FROM read_ast('{escaped_pattern}')
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
                    self._db.sql(
                        f"INSERT INTO {table_name} SELECT * FROM read_ast('{esc}')"
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
        return hashlib.sha256(pattern.encode()).hexdigest()[:16]

    def _sql_list(self, items: list[str]) -> str:
        if not items:
            return "CAST([] AS VARCHAR[])"
        escaped = ", ".join("'" + s.replace("'", "''") + "'" for s in items)
        return f"[{escaped}]"
