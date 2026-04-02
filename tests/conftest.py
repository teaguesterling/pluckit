# tests/conftest.py
"""Shared fixtures for pluckit tests."""
import textwrap
from pathlib import Path

import pytest


SAMPLE_AUTH = textwrap.dedent("""\
    import json
    import os

    def validate_token(token: str, timeout: int = 30) -> bool:
        if token is None:
            return None
        if len(token) < 10:
            raise ValueError("token too short")
        return True

    def process_data(items: list, threshold: float = 0.5) -> list:
        filtered = []
        for item in items:
            if item.score > threshold:
                filtered.append(item)
        return filtered

    class AuthService:
        def __init__(self, db):
            self.db = db

        def authenticate(self, username: str, password: str) -> bool:
            user = self.db.get_user(username)
            if user is None:
                return False
            return user.check_password(password)

        def _internal_helper(self):
            pass
""")

SAMPLE_EMAIL = textwrap.dedent("""\
    from typing import Optional

    def send_email(to: str, subject: str, body: str, cc: Optional[str] = None) -> bool:
        if not to:
            raise ValueError("recipient required")
        return True

    def parse_header(raw: bytes) -> dict:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
""")


@pytest.fixture
def sample_dir(tmp_path):
    """Create a temp directory with sample Python files."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "auth.py").write_text(SAMPLE_AUTH)
    (src / "email.py").write_text(SAMPLE_EMAIL)
    return tmp_path


@pytest.fixture
def ctx(sample_dir):
    """Create a pluckit Context rooted at the sample directory."""
    from pluckit.context import Context
    return Context(repo=str(sample_dir))
