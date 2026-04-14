"""History pluckin — git history operations on AST selections.

Exposes five methods on ``Selection`` when this plugin is loaded:

- ``history()`` — commits that touched the matched nodes' files
- ``authors()`` — distinct authors of those commits
- ``at(rev)``  — text of each matched node as it was at a revision
- ``diff(rev)``— unified diff of each matched node between HEAD and ``rev``
- ``blame()``  — NOT YET IMPLEMENTED; upstream-blocked on duck_tails adding
  a line-level blame table function. Raises PluckerError with a pointer.

Architecture: hybrid. `at()` and `diff()` use the duck_tails `git_read` /
`text_diff` table functions since those fit naturally as literal-arg
calls. `history()` and `authors()` shell out to ``git log --follow`` —
duck_tails doesn't support lateral joins over commit hashes, so a pure
SQL implementation would require an O(N commits) Python loop with
per-commit `git_diff_tree` calls, whereas `git log --follow` handles
rename tracking for free and runs in a single subprocess call.

``git`` must be on PATH for ``history()`` and ``authors()`` to work;
``duck_tails`` must be loaded for ``at()`` and ``diff()``.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from pluckit.plugins.base import Pluckin
from pluckit.types import PluckerError

if TYPE_CHECKING:
    from pluckit.selection import Selection


@dataclass(frozen=True)
class Commit:
    """A single commit in a file's history."""
    hash: str
    author_name: str
    author_email: str
    author_date: str     # ISO 8601 string
    message: str         # first line of the commit message

    # -- Serialization (for MCP transport) ----------------------------------

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> Commit:
        return cls(**{k: data[k] for k in ("hash", "author_name", "author_email", "author_date", "message")})

    def to_json(self, **kwargs) -> str:
        import json as _json
        return _json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_json(cls, text: str) -> Commit:
        import json as _json
        return cls.from_dict(_json.loads(text))


class History(Pluckin):
    """git-history pluckin. Load with ``Plucker(..., plugins=[History])``.

    Example::

        from pluckit import Plucker
        from pluckit.plugins import History

        pluck = Plucker(code="src/**/*.py", plugins=[History])
        fn = pluck.find(".fn#validate_token")

        # Every commit that touched validate_token's file, most recent first
        for commit in fn.history():
            print(f"{commit.hash[:8]} {commit.author_name}: {commit.message}")

        # All authors who ever touched that file
        print(fn.authors())

        # The function's body as it existed at v0.1.0
        for text in fn.at("v0.1.0"):
            print(text)

        # Unified diff between HEAD and v0.1.0, restricted to the function's lines
        for diff in fn.diff("v0.1.0"):
            print(diff)
    """

    name = "History"
    methods = {
        "history": "history",
        "authors": "authors",
        "at": "at",
        "diff": "diff",
        "blame": "blame",
    }

    # ------------------------------------------------------------------
    # Public methods (called via plugin dispatch as `plugin.METHOD(selection, ...)`)
    # ------------------------------------------------------------------

    def history(self, selection: Selection) -> list[Commit]:
        """Return commits that touched each matched node's file.

        Deduplicates across multiple matches in the same file. Results are
        sorted most-recent-first. Rename-aware (``git log --follow``).
        """
        self._require_git()
        repo = selection._ctx.repo
        seen: set[str] = set()
        commits: list[Commit] = []
        for file_path in self._distinct_files(selection):
            for commit in self._git_log_file(file_path, repo):
                if commit.hash in seen:
                    continue
                seen.add(commit.hash)
                commits.append(commit)
        commits.sort(key=lambda c: c.author_date, reverse=True)
        return commits

    def authors(self, selection: Selection) -> list[str]:
        """Return distinct author emails for commits touching the matched files."""
        emails: set[str] = set()
        for commit in self.history(selection):
            if commit.author_email:
                emails.add(commit.author_email)
        return sorted(emails)

    def at(self, selection: Selection, rev: str) -> list[str]:
        """Return the source text of each matched node as of revision ``rev``.

        Fetches the file at ``rev`` via ``duck_tails.git_read``, writes it
        to a temp file, re-runs sitting_duck's parser against it, and
        locates a node with the same ``(name, type)`` as the current
        match. Returns that node's text from the old file.

        If the node can't be found at the old revision (added later,
        renamed, or restructured), the corresponding entry is an empty
        string rather than a garbled line-slice.
        """
        self._require_duck_tails(selection)
        repo = selection._ctx.repo
        nodes = selection.materialize()
        return [self._node_text_at_rev(node, rev, repo, selection) for node in nodes]

    def diff(self, selection: Selection, rev: str) -> list[str]:
        """Return unified diff between HEAD and ``rev`` for each matched node.

        For each matched node, resolves the corresponding node at ``rev``
        (by ``(name, type)``) and at HEAD, and diffs the two node texts.
        Returns a list of unified-diff strings, one per match. Empty
        string for any match whose node can't be located at ``rev``.
        """
        import difflib

        self._require_duck_tails(selection)
        repo = selection._ctx.repo
        nodes = selection.materialize()
        diffs: list[str] = []
        for node in nodes:
            rel = self._relative_to_repo(node["file_path"], repo)
            old_text = self._node_text_at_rev(node, rev, repo, selection)
            new_text = self._node_text_at_rev(node, "HEAD", repo, selection)
            diff = "".join(
                difflib.unified_diff(
                    old_text.splitlines(keepends=True),
                    new_text.splitlines(keepends=True),
                    fromfile=f"{rel}@{rev}",
                    tofile=f"{rel}@HEAD",
                )
            )
            diffs.append(diff)
        return diffs

    def blame(self, selection: Selection) -> Any:
        """Line-level git blame is not yet supported.

        duck_tails (as of the version pluckit pins against) does not
        expose a ``git_blame`` table function, and implementing
        line-level blame in Python by iterating the whole commit history
        per matched line range is prohibitively expensive.

        This method is reserved for when duck_tails grows an upstream
        ``git_blame`` function. Track progress at:
        https://github.com/teaguesterling/duck_tails/issues
        """
        raise PluckerError(
            "blame() is not yet implemented. duck_tails does not expose a "
            "line-level blame table function; implementing blame via iterated "
            "git_log + per-commit file reads is prohibitively expensive. "
            "Track upstream support at "
            "https://github.com/teaguesterling/duck_tails/issues."
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _require_git(self) -> None:
        if shutil.which("git") is None:
            raise PluckerError(
                "History plugin: `git` not found on PATH. Install git to use "
                "history() and authors()."
            )

    def _require_duck_tails(self, selection: Selection) -> None:
        """Verify the duck_tails extension is loaded in the Selection's context.

        Raises a helpful PluckerError if not; this plugin is registered
        optionally in _Context._ensure_extensions so a failed community-
        extension install leaves duck_tails unavailable without blocking
        core pluckit operations.
        """
        try:
            selection._ctx.db.sql("SELECT 1 FROM duckdb_functions() WHERE function_name = 'git_read' LIMIT 1").fetchone()
        except Exception as e:
            raise PluckerError(
                f"History plugin: duck_tails extension is not loaded: {e}. "
                f"Run `pluckit init` to install it."
            ) from e
        row = selection._ctx.db.sql(
            "SELECT count(*) FROM duckdb_functions() WHERE function_name = 'git_read'"
        ).fetchone()
        if not row or row[0] == 0:
            raise PluckerError(
                "History plugin: duck_tails `git_read` function not found. "
                "Run `pluckit init` to install the extension."
            )

    def _distinct_files(self, selection: Selection) -> list[str]:
        view = selection._register("hist")
        try:
            rows = selection._ctx.db.sql(
                f"SELECT DISTINCT file_path FROM {view}"
            ).fetchall()
        finally:
            try:
                selection._unregister(view)
            except Exception:
                pass
        return [row[0] for row in rows]

    def _relative_to_repo(self, file_path: str, repo: str) -> str:
        import os
        try:
            rel = os.path.relpath(file_path, repo)
        except ValueError:
            return file_path
        # git URIs use forward slashes; normalize.
        return rel.replace(os.sep, "/")

    def _git_log_file(self, file_path: str, repo: str) -> list[Commit]:
        """Run `git log --follow --format=... -- <file>` and parse the output.

        Uses NUL delimiters between fields and record terminators so commit
        messages can contain arbitrary text including newlines.
        """
        rel = self._relative_to_repo(file_path, repo)
        # Format: hash NUL author_name NUL author_email NUL iso_date NUL subject
        # Records terminated by NUL-newline for easy splitting.
        fmt = "%H%x1f%an%x1f%ae%x1f%aI%x1f%s%x1e"
        try:
            proc = subprocess.run(
                [
                    "git", "log",
                    "--follow",
                    f"--format={fmt}",
                    "--",
                    rel,
                ],
                cwd=repo,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            # File not in git, not a git repo, etc. Return empty history.
            stderr = (e.stderr or "").strip()
            if stderr and "not a git repository" in stderr.lower():
                raise PluckerError(
                    f"History plugin: {repo} is not a git repository"
                ) from e
            return []
        except FileNotFoundError as e:
            raise PluckerError(
                "History plugin: `git` not found on PATH"
            ) from e

        commits: list[Commit] = []
        for record in proc.stdout.split("\x1e"):
            record = record.strip("\n")
            if not record:
                continue
            parts = record.split("\x1f")
            if len(parts) < 5:
                continue
            h, name, email, date, subject = parts[0], parts[1], parts[2], parts[3], parts[4]
            commits.append(Commit(
                hash=h,
                author_name=name,
                author_email=email,
                author_date=date,
                message=subject,
            ))
        return commits

    def _git_read_file(
        self,
        rel_path: str,
        rev: str,
        repo: str,
        selection: Selection,
    ) -> str | None:
        """Fetch the full text of ``rel_path`` at ``rev`` via duck_tails.git_read.

        Returns ``None`` if the file does not exist at that revision.

        Uses an absolute-path ``git://`` URI rather than the ``repo_path``
        named parameter: in the installed duck_tails version, a URI with
        a relative path is resolved against the process cwd regardless of
        ``repo_path``, so we embed the full absolute path in the URI
        itself. This is robust to the caller's cwd.
        """
        import os
        abs_path = os.path.join(repo, rel_path)
        esc_abs = abs_path.replace("'", "''")
        esc_rev = rev.replace("'", "''")
        uri = f"git://{esc_abs}@{esc_rev}"
        try:
            row = selection._ctx.db.sql(
                f"SELECT text FROM git_read('{uri}') LIMIT 1"
            ).fetchone()
        except Exception:
            return None
        if row is None:
            return None
        return row[0]

    def _node_text_at_rev(
        self,
        node: dict,
        rev: str,
        repo: str,
        selection: Selection,
    ) -> str:
        """Find the node corresponding to ``node`` at revision ``rev`` and return its text.

        Matches by ``(name, type)`` using pluckit's own ``read_ast`` query path
        against a tempfile containing the old file's content. This intentionally
        sidesteps sitting_duck's upcoming ``ast_select`` macro (not yet in the
        community-repo version this pluckit pins against) — pluckit's compiler
        handles the ``name = X AND type = Y`` query we need here just as well.

        When sitting_duck ships ``ast_select`` in a community-extension release,
        this method becomes a one-line swap: ``ast_select(tmp_path, '.fn#' + name)``
        instead of the current read_ast path.

        Returns an empty string when:
        - The file does not exist at ``rev``
        - No node matches ``(name, type)`` in the old file (node was added later,
          renamed, or restructured)
        - The node has no name (e.g., an anonymous lambda)
        """
        import os
        import tempfile

        name = node.get("name")
        node_type = node.get("type")
        if not name or not node_type:
            # Without a name we can't re-locate the node at the old revision.
            return ""

        rel = self._relative_to_repo(node["file_path"], repo)
        text = self._git_read_file(rel, rev, repo, selection)
        if text is None:
            return ""

        # Preserve the source extension so sitting_duck picks the right
        # tree-sitter grammar (language detection is extension-based).
        _, ext = os.path.splitext(rel)
        suffix = ext if ext else ".txt"

        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=suffix,
                delete=False,
                encoding="utf-8",
            ) as tmp:
                tmp.write(text)
                tmp_path = tmp.name

            esc_tmp = tmp_path.replace("'", "''")
            esc_name = name.replace("'", "''")
            esc_type = node_type.replace("'", "''")
            try:
                row = selection._ctx.db.sql(
                    f"""
                    SELECT start_line, end_line
                    FROM read_ast('{esc_tmp}')
                    WHERE name = '{esc_name}'
                      AND type = '{esc_type}'
                      AND (flags & 1) = 0
                    ORDER BY node_id
                    LIMIT 1
                    """
                ).fetchone()
            except Exception:
                return ""
            if row is None:
                return ""
            start, end = int(row[0]), int(row[1])
            return _extract_lines(text, start, end)
        finally:
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _extract_lines(text: str, start: int, end: int) -> str:
    """Return lines ``start..end`` (1-indexed, inclusive) from ``text``.

    If either endpoint is out of range, clamps to the available range.
    If the entire range is out of range, returns an empty string.
    """
    if not text:
        return ""
    lines = text.splitlines(keepends=True)
    if not lines:
        return ""
    # Clamp to valid 1-indexed range
    s = max(1, start)
    e = min(len(lines), end)
    if s > len(lines) or e < 1 or s > e:
        return ""
    return "".join(lines[s - 1 : e])
