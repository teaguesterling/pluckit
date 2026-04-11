"""Tests for the History pluckin (git-history operations on AST selections).

These tests stand up a real git repo in ``tmp_path`` with a known commit
graph, run pluckit queries against it, and verify the plugin's public
methods return the right shape. They hit both the subprocess path
(``git log --follow`` for ``history()``/``authors()``) and the duck_tails
+ re-parse path (``at(rev)``/``diff(rev)``).
"""
from __future__ import annotations

import shutil
import subprocess
import textwrap

import pytest

from pluckit import Plucker
from pluckit.plugins import History
from pluckit.types import PluckerError

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="git not available; History plugin requires git for history()/authors()",
)


# ---------------------------------------------------------------------------
# Fixture: a tiny git repo with a 3-commit history on a single Python file
# ---------------------------------------------------------------------------

V1 = textwrap.dedent("""\
    def authenticate(username, password):
        return True

    def logout():
        pass
""")

V2 = textwrap.dedent("""\
    def authenticate(username, password, timeout=30):
        if not username:
            return False
        return True

    def logout():
        pass
""")

V3 = textwrap.dedent("""\
    def authenticate(username, password, timeout=30, trace_id=None):
        if not username:
            return False
        if trace_id:
            log(trace_id)
        return True

    def logout():
        pass

    def register(username, password):
        return {"id": 1}
""")


def _run_git(cwd, *args, env_extra=None):
    env = {
        "GIT_AUTHOR_NAME": "Test Author",
        "GIT_AUTHOR_EMAIL": "author@example.com",
        "GIT_COMMITTER_NAME": "Test Author",
        "GIT_COMMITTER_EMAIL": "author@example.com",
        # Force a stable, reproducible date for the first commit; later commits
        # will bump the clock inside this test.
        "GIT_AUTHOR_DATE": "2026-01-01T00:00:00",
        "GIT_COMMITTER_DATE": "2026-01-01T00:00:00",
        "PATH": "/usr/bin:/bin:/usr/local/bin",
    }
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )


@pytest.fixture
def git_repo(tmp_path):
    """Stand up a 3-commit git repo with `src/auth.py` evolving across revisions."""
    repo = tmp_path
    src = repo / "src"
    src.mkdir()
    f = src / "auth.py"

    _run_git(repo, "init", "-q", "-b", "main")
    # Local config so commits work without relying on global config
    _run_git(repo, "config", "user.name", "Test Author")
    _run_git(repo, "config", "user.email", "author@example.com")
    _run_git(repo, "config", "commit.gpgsign", "false")

    f.write_text(V1)
    _run_git(repo, "add", "src/auth.py")
    _run_git(repo, "commit", "-q", "-m", "initial: add authenticate + logout")

    f.write_text(V2)
    _run_git(
        repo, "commit", "-q", "-am", "feat: add timeout param and validation",
        env_extra={
            "GIT_AUTHOR_DATE": "2026-01-02T00:00:00",
            "GIT_COMMITTER_DATE": "2026-01-02T00:00:00",
        },
    )

    f.write_text(V3)
    _run_git(
        repo, "commit", "-q", "-am", "feat: add trace_id and register",
        env_extra={
            "GIT_AUTHOR_DATE": "2026-01-03T00:00:00",
            "GIT_COMMITTER_DATE": "2026-01-03T00:00:00",
            "GIT_AUTHOR_EMAIL": "other@example.com",
            "GIT_COMMITTER_EMAIL": "other@example.com",
        },
    )
    return repo


@pytest.fixture
def pluck(git_repo):
    return Plucker(
        code=str(git_repo / "src/auth.py"),
        plugins=[History],
        repo=str(git_repo),
    )


# ---------------------------------------------------------------------------
# history() and authors() — subprocess-backed
# ---------------------------------------------------------------------------

class TestHistory:
    def test_history_returns_commits_for_touching_file(self, pluck):
        hist = pluck.find(".fn#authenticate").history()
        assert len(hist) == 3
        # Most recent first
        messages = [c.message for c in hist]
        assert "trace_id" in messages[0]
        assert "timeout" in messages[1]
        assert "initial" in messages[2]

    def test_history_commit_fields_populated(self, pluck):
        hist = pluck.find(".fn#authenticate").history()
        c = hist[0]
        assert len(c.hash) == 40  # full SHA
        assert c.author_name == "Test Author"
        assert c.author_email == "other@example.com"  # last commit was 'other'
        assert c.author_date.startswith("2026-01-03")
        assert c.message

    def test_history_deduplicates_across_matches_in_one_file(self, pluck):
        """If a query matches two fns in the same file, the file's commit
        history should still be deduplicated in the result."""
        both = pluck.find(".fn")  # all three functions in src/auth.py
        assert both.count() == 3
        hist = both.history()
        # Still only 3 unique commits (they all touched the same file)
        assert len(hist) == 3


class TestAuthors:
    def test_authors_returns_unique_emails(self, pluck):
        authors = pluck.find(".fn#authenticate").authors()
        assert set(authors) == {"author@example.com", "other@example.com"}

    def test_authors_sorted(self, pluck):
        authors = pluck.find(".fn#authenticate").authors()
        assert authors == sorted(authors)


# ---------------------------------------------------------------------------
# at(rev) — duck_tails + re-parse
# ---------------------------------------------------------------------------

class TestAt:
    def test_at_head_returns_current_function_body(self, pluck):
        texts = pluck.find(".fn#authenticate").at("HEAD")
        assert len(texts) == 1
        body = texts[0]
        assert "trace_id" in body
        assert "def authenticate(username, password, timeout=30, trace_id=None):" in body

    def test_at_initial_commit_returns_original_body(self, pluck, git_repo):
        # Ask for HEAD~2 (the initial commit)
        texts = pluck.find(".fn#authenticate").at("HEAD~2")
        assert len(texts) == 1
        body = texts[0]
        # Original form had no timeout, no validation, no trace_id
        assert "def authenticate(username, password):" in body
        assert "timeout" not in body
        assert "trace_id" not in body

    def test_at_returns_empty_string_when_node_missing_at_rev(self, pluck):
        # `register` didn't exist at HEAD~2
        texts = pluck.find(".fn#register").at("HEAD~2")
        assert texts == [""]

    def test_at_is_ast_aware_not_line_sliced(self, pluck):
        """The node's current line range might not correspond to the same
        semantic node in an old revision. at() must re-parse and look up
        by (name, type), not naively slice by current line numbers."""
        # `logout` at HEAD is at a different line number than at HEAD~2
        # (V3 adds content above it). Verify we get `logout`, not some
        # random slice of the old file.
        texts = pluck.find(".fn#logout").at("HEAD~2")
        assert "def logout" in texts[0]
        assert "def authenticate" not in texts[0]


# ---------------------------------------------------------------------------
# diff(rev) — per-node unified diff
# ---------------------------------------------------------------------------

class TestDiff:
    def test_diff_shows_meaningful_changes(self, pluck):
        diffs = pluck.find(".fn#authenticate").diff("HEAD~2")
        assert len(diffs) == 1
        d = diffs[0]
        # Should show the addition of timeout and trace_id
        assert "+" in d and "-" in d
        assert "trace_id" in d
        # fromfile / tofile markers
        assert "@HEAD~2" in d
        assert "@HEAD" in d

    def test_diff_of_unchanged_function_is_empty(self, pluck):
        # `logout` has been unchanged across all revisions
        diffs = pluck.find(".fn#logout").diff("HEAD~2")
        # Empty diff (no +/- lines, just possibly a header or empty string)
        d = diffs[0]
        # Unified diff of identical content is empty
        assert not any(line.startswith("+") and not line.startswith("+++") for line in d.splitlines())
        assert not any(line.startswith("-") and not line.startswith("---") for line in d.splitlines())


# ---------------------------------------------------------------------------
# blame() — explicit NotImplemented with upstream pointer
# ---------------------------------------------------------------------------

class TestBlame:
    def test_blame_raises_with_upstream_pointer(self, pluck):
        with pytest.raises(PluckerError, match="duck_tails"):
            pluck.find(".fn#authenticate").blame()


# ---------------------------------------------------------------------------
# Plugin registration / attribute delivery
# ---------------------------------------------------------------------------

class TestHistoryPluginRegistration:
    def test_methods_surface_when_plugin_loaded(self, pluck):
        sel = pluck.find(".fn#authenticate")
        # These are accessible as methods on the Selection via the plugin
        # dispatch shim, not as concrete methods on core Selection.
        assert callable(sel.history)
        assert callable(sel.at)
        assert callable(sel.diff)
        assert callable(sel.authors)
        assert callable(sel.blame)

    def test_methods_missing_without_plugin(self, git_repo):
        """Without the History plugin, these methods should raise a helpful
        PluckerError (via Selection.__getattr__ + _KNOWN_PROVIDERS)."""
        pluck = Plucker(
            code=str(git_repo / "src/auth.py"),
            repo=str(git_repo),
            # No plugins=[History]
        )
        sel = pluck.find(".fn#authenticate")
        with pytest.raises(PluckerError, match="History"):
            _ = getattr(sel, "history")  # noqa: B009 — the getattr IS the side effect
