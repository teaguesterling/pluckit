"""Tests for the display_path helper."""
from __future__ import annotations

import os

from pluckit._paths import display_path


class TestDisplayPath:
    def test_file_inside_base(self, tmp_path):
        base = tmp_path
        f = base / "src" / "foo.py"
        f.parent.mkdir()
        f.write_text("")
        assert display_path(str(f), str(base)) == os.path.join("src", "foo.py")

    def test_file_equals_base(self, tmp_path):
        f = tmp_path / "foo.py"
        f.write_text("")
        assert display_path(str(f), str(tmp_path)) == "foo.py"

    def test_file_outside_base_uses_home_substitution(self, tmp_path, monkeypatch):
        # Point HOME at the temp tree so we exercise the ~ substitution
        # branch deterministically regardless of the real home.
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))

        target = fake_home / "projects" / "other" / "foo.py"
        target.parent.mkdir(parents=True)
        target.write_text("")

        # Base is deep inside a sibling tree — relpath would go up many levels
        deep_base = tmp_path / "deeply" / "nested" / "cwd"
        deep_base.mkdir(parents=True)

        out = display_path(str(target), str(deep_base))
        assert out.startswith("~")
        assert "projects/other/foo.py" in out
        # Should NOT start with ../
        assert ".." not in out

    def test_file_outside_base_and_outside_home_returns_absolute(
        self, tmp_path, monkeypatch
    ):
        # HOME is somewhere completely unrelated
        fake_home = tmp_path / "some_other_home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))

        target = tmp_path / "completely" / "elsewhere" / "file.py"
        target.parent.mkdir(parents=True)
        target.write_text("")

        deep_base = tmp_path / "deeply" / "nested" / "cwd"
        deep_base.mkdir(parents=True)

        out = display_path(str(target), str(deep_base))
        # Should be an absolute path, not ../../../...
        assert out == str(target)
        assert not out.startswith("..")

    def test_base_defaults_to_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        f = tmp_path / "foo.py"
        f.write_text("")
        assert display_path(str(f)) == "foo.py"

    def test_never_raises_on_weird_input(self):
        # Should not raise even on bizarre input
        assert display_path("") != None  # noqa: E711  — just making sure it returns

    def test_long_relpath_replaced_by_home_substitution(self, tmp_path, monkeypatch):
        """The original bug: `../../../../../../home/x/...` should become `~/x/...`."""
        fake_home = tmp_path / "home_user"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))

        target = fake_home / "Projects" / "lackpy" / "src" / "cli.py"
        target.parent.mkdir(parents=True)
        target.write_text("")

        # A cwd that's 6 levels deep and NOT under home
        deep_base = tmp_path / "a" / "b" / "c" / "d" / "e" / "f"
        deep_base.mkdir(parents=True)

        out = display_path(str(target), str(deep_base))
        # Compact home path, not a long ../
        assert out.startswith("~/")
        assert out.count("..") == 0
        assert "Projects/lackpy/src/cli.py" in out
