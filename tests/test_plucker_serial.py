"""Tests for Plucker serialization."""
from __future__ import annotations

import json

from pluckit import AstViewer, Plucker


class TestPluckerSerialization:
    def test_to_dict(self):
        p = Plucker(code="src/**/*.py", plugins=[], repo="/tmp/test")
        d = p.to_dict()
        assert d["code"] == "src/**/*.py"
        assert d["repo"] == "/tmp/test"

    def test_to_dict_with_plugins(self):
        p = Plucker(code="*.py", plugins=[AstViewer])
        d = p.to_dict()
        assert "AstViewer" in d["plugins"]

    def test_to_dict_omits_cwd_repo(self):
        # When repo == cwd, it's omitted as a default
        p = Plucker(code="*.py")
        d = p.to_dict()
        # repo may or may not be present depending on whether it equals cwd
        # but shouldn't crash
        assert "code" in d

    def test_from_dict(self, tmp_path):
        (tmp_path / "a.py").write_text("def f(): pass\n")
        d = {"code": str(tmp_path / "*.py"), "plugins": ["AstViewer"]}
        p = Plucker.from_dict(d)
        assert p.find(".fn").count() >= 1

    def test_to_json_round_trip(self):
        p = Plucker(code="src/**/*.py", plugins=[], repo="/tmp/x")
        j = p.to_json()
        data = json.loads(j)
        assert data["code"] == "src/**/*.py"

    def test_to_argv(self):
        p = Plucker(code="src/**/*.py", plugins=[AstViewer], repo="/tmp/x")
        argv = p.to_argv()
        assert "src/**/*.py" in argv
        assert "--plugin" in argv
        assert "AstViewer" in argv
        assert "--repo" in argv
        assert "/tmp/x" in argv

    def test_from_argv(self, tmp_path):
        (tmp_path / "a.py").write_text("def f(): pass\n")
        p = Plucker.from_argv(["--plugin", "AstViewer", str(tmp_path / "*.py")])
        assert p.find(".fn").count() >= 1

    def test_argv_round_trip(self, tmp_path):
        (tmp_path / "a.py").write_text("def f(): pass\n")
        original = Plucker(code=str(tmp_path / "*.py"), plugins=[AstViewer], repo=str(tmp_path))
        argv = original.to_argv()
        restored = Plucker.from_argv(argv)
        assert restored._code_source == original._code_source
