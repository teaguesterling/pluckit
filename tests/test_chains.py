"""End-to-end chain tests exercising multi-step Selection flows.

Unit tests in test_selection.py cover each Selection method in isolation.
These tests exercise full method chains across query → filter → navigate
→ mutate → verify, catching integration bugs that the isolated unit
tests miss. They're also the regression harness for the public fluent
API — if a chain pattern in the docs stops working, it should fail here.
"""
from __future__ import annotations

import textwrap

import pytest

from pluckit import Plucker

# ---------------------------------------------------------------------------
# A larger sample corpus for chain testing: a small "service" module with
# exported and private functions, a class with methods, decorators, and a
# try/except block.
# ---------------------------------------------------------------------------

CHAIN_SAMPLE = textwrap.dedent("""\
    import logging
    from typing import Optional

    log = logging.getLogger(__name__)


    def authenticate(username: str, password: str) -> bool:
        user = _lookup_user(username)
        if user is None:
            return False
        return user.check_password(password)


    def register(username: str, password: str, email: str) -> dict:
        if not _is_valid_email(email):
            raise ValueError("invalid email")
        try:
            user = _create_user(username, password, email)
        except DatabaseError:
            log.error("database write failed")
            raise
        return {"id": user.id, "username": username}


    def logout(session_id: str) -> None:
        _invalidate_session(session_id)


    def _lookup_user(username):
        return None


    def _is_valid_email(email: str) -> bool:
        return "@" in email


    def _create_user(username, password, email):
        return None


    def _invalidate_session(session_id):
        pass


    class UserService:
        def __init__(self, db):
            self.db = db

        def get_user(self, user_id: int) -> Optional[dict]:
            row = self.db.fetch(user_id)
            if row is None:
                return None
            return {"id": row[0], "username": row[1]}

        def delete_user(self, user_id: int) -> bool:
            result = self.db.execute(f"DELETE FROM users WHERE id={user_id}")
            return result > 0

        def _audit(self, event: str) -> None:
            log.info("audit: %s", event)
""")


@pytest.fixture
def chain_repo(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "service.py").write_text(CHAIN_SAMPLE)
    return tmp_path


@pytest.fixture
def pluck(chain_repo):
    return Plucker(code=str(chain_repo / "src/**/*.py"))


# ---------------------------------------------------------------------------
# Pure query chains: no mutations, verifying composition of query methods
# ---------------------------------------------------------------------------

class TestQueryChains:
    def test_find_then_filter_exported(self, pluck):
        """find(.fn) → filter(:exported) should exclude underscore-prefixed."""
        all_fns = pluck.find(".fn")
        exported = all_fns.filter(":exported")
        names = exported.names()
        assert "authenticate" in names
        assert "register" in names
        assert "_lookup_user" not in names
        assert "_is_valid_email" not in names

    def test_class_methods_descend(self, pluck):
        """cls#UserService → find(.fn) should return the class's methods only."""
        svc = pluck.find(".cls#UserService")
        methods = svc.find(".fn")
        names = methods.names()
        assert "get_user" in names
        assert "delete_user" in names
        # Module-level functions are not under the class
        assert "authenticate" not in names

    def test_public_methods_only(self, pluck):
        """cls#UserService → find(.fn) → filter(:exported) strips underscore-prefixed methods."""
        public_methods = (
            pluck.find(".cls#UserService")
            .find(".fn")
            .filter(":exported")
        )
        names = public_methods.names()
        assert "get_user" in names
        assert "delete_user" in names
        assert "_audit" not in names
        # :exported filters out anything starting with _, which includes
        # dunder methods like __init__. If that policy ever changes (dunders
        # become "exported"), this assertion is the tripwire.
        assert "__init__" not in names

    def test_name_prefix_filter_chain(self, pluck):
        """Selector attribute filter composes with find()."""
        lookups = pluck.find(".fn").filter(name__startswith="_")
        names = lookups.names()
        assert "_lookup_user" in names
        assert "_is_valid_email" in names
        assert "authenticate" not in names

    def test_navigation_then_read(self, pluck):
        """fn → parent should walk up to the containing scope."""
        get_user = pluck.find(".fn#get_user")
        parents = get_user.parent()
        # The parent of get_user is the class body / class itself
        assert parents.count() >= 1

    def test_count_unchanged_by_no_op_chain(self, pluck):
        """unique() on an already-deduped selection is a no-op."""
        fns = pluck.find(".fn")
        original = fns.count()
        assert fns.unique().count() == original


# ---------------------------------------------------------------------------
# Query → terminal: verify terminal methods work on chained selections
# ---------------------------------------------------------------------------

class TestChainsToTerminals:
    def test_names_after_multi_chain(self, pluck):
        names = (
            pluck.find(".cls#UserService")
            .find(".fn")
            .filter(":exported")
            .names()
        )
        assert "get_user" in names
        assert "_audit" not in names

    def test_text_after_chain(self, pluck):
        """text() returns source of each matched node after a chain."""
        texts = pluck.find(".fn:exported").filter(name="register").text()
        assert len(texts) == 1
        assert "def register" in texts[0]
        assert "invalid email" in texts[0]

    def test_count_zero_on_missing(self, pluck):
        """A chain that narrows to zero should return 0, not raise."""
        sel = pluck.find(".fn#nonexistent").filter(":exported")
        assert sel.count() == 0
        assert sel.names() == []

    def test_attr_after_chain(self, pluck):
        """attr() works after navigation chains."""
        lines = (
            pluck.find(".cls#UserService")
            .find(".fn#delete_user")
            .attr("start_line")
        )
        assert len(lines) == 1
        assert isinstance(lines[0], int)


# ---------------------------------------------------------------------------
# Query → mutate → verify: full transaction round-trips
# ---------------------------------------------------------------------------

class TestChainsToMutations:
    def test_add_param_to_exported_then_verify(self, pluck, chain_repo):
        """addParam on :exported functions; re-query confirms the change."""
        pluck.find(".fn:exported").filter(name="authenticate").addParam(
            "trace_id: str | None = None"
        )
        content = (chain_repo / "src" / "service.py").read_text()
        assert "def authenticate(username: str, password: str, trace_id: str | None = None)" in content

    def test_rename_then_verify_via_new_selection(self, pluck, chain_repo):
        """After rename, the new name should be findable and the old one shouldn't."""
        pluck.find(".fn#logout").rename("sign_out")
        content = (chain_repo / "src" / "service.py").read_text()
        assert "def sign_out" in content
        assert "def logout" not in content

        # A fresh query (same Plucker, re-reading the file) should find the new name
        fresh_pluck = Plucker(code=str(chain_repo / "src/**/*.py"))
        assert fresh_pluck.find(".fn#sign_out").count() == 1
        assert fresh_pluck.find(".fn#logout").count() == 0

    def test_chain_narrows_before_mutation(self, pluck, chain_repo):
        """Narrowing by class → method → mutation only affects the narrowed set."""
        # Add a param to UserService.get_user ONLY, not to any module-level fn
        pluck.find(".cls#UserService").find(".fn#get_user").addParam(
            "cache: bool = True"
        )
        content = (chain_repo / "src" / "service.py").read_text()
        # get_user got the param
        assert "def get_user(self, user_id: int, cache: bool = True)" in content
        # authenticate did NOT
        assert "def authenticate(username: str, password: str)" in content
        # delete_user did NOT
        assert "def delete_user(self, user_id: int) -> bool:" in content

    def test_empty_chain_mutation_is_noop(self, pluck, chain_repo):
        """A chain that matches nothing should leave the file untouched."""
        original = (chain_repo / "src" / "service.py").read_text()
        pluck.find(".fn#does_not_exist").filter(":exported").rename("whatever")
        content = (chain_repo / "src" / "service.py").read_text()
        assert content == original


# ---------------------------------------------------------------------------
# Cross-file chains
# ---------------------------------------------------------------------------

class TestCrossFileChains:
    def test_chain_aggregates_across_files(self, tmp_path):
        """Selection spans multiple files; terminal methods aggregate."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.py").write_text("def one(): return 1\ndef two(): return 2\n")
        (src / "b.py").write_text("def three(): return 3\n")

        pluck = Plucker(code=str(src / "*.py"))
        all_fns = pluck.find(".fn")
        assert all_fns.count() == 3
        assert set(all_fns.names()) == {"one", "two", "three"}

    def test_narrow_by_name_across_files(self, tmp_path):
        """Filter by name prefix reaches into every file in the glob."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.py").write_text("def _private_a(): pass\ndef public_a(): pass\n")
        (src / "b.py").write_text("def _private_b(): pass\ndef public_b(): pass\n")

        pluck = Plucker(code=str(src / "*.py"))
        private = pluck.find(".fn").filter(name__startswith="_")
        assert set(private.names()) == {"_private_a", "_private_b"}
