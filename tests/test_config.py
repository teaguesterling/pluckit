"""Tests for pluckit.config — project config reader from pyproject.toml."""

from __future__ import annotations

from pathlib import Path

from pluckit.config import PluckitConfig


def _write_pyproject(tmp_path: Path, content: str) -> None:
    (tmp_path / "pyproject.toml").write_text(content)


class TestPluckitConfig:
    def test_reads_pyproject_toml(self, tmp_path: Path) -> None:
        _write_pyproject(
            tmp_path,
            """\
[tool.pluckit]
plugins = ["JsonViewer", "CsvViewer"]

[tool.pluckit.sources]
mydb = "sqlite:///my.db"
logs = "/var/log/**/*.log"
""",
        )
        cfg = PluckitConfig.load(tmp_path)
        assert cfg.plugins == ["JsonViewer", "CsvViewer"]
        assert cfg.sources == {"mydb": "sqlite:///my.db", "logs": "/var/log/**/*.log"}

    def test_defaults_when_no_config(self, tmp_path: Path) -> None:
        cfg = PluckitConfig.load(tmp_path)
        assert cfg.plugins == ["AstViewer"]
        assert cfg.sources == {}

    def test_defaults_when_no_pluckit_section(self, tmp_path: Path) -> None:
        _write_pyproject(
            tmp_path,
            """\
[project]
name = "something"
""",
        )
        cfg = PluckitConfig.load(tmp_path)
        assert cfg.plugins == ["AstViewer"]
        assert cfg.sources == {}

    def test_resolve_source_shortcut(self, tmp_path: Path) -> None:
        _write_pyproject(
            tmp_path,
            """\
[tool.pluckit.sources]
mydb = "sqlite:///my.db"
""",
        )
        cfg = PluckitConfig.load(tmp_path)
        # Known shortcut resolves to its value
        assert cfg.resolve_source("mydb") == ["sqlite:///my.db"]
        # Unknown name passes through as-is
        assert cfg.resolve_source("unknown.py") == ["unknown.py"]

    def test_default_sources_always_present(self) -> None:
        """'code' without any config returns ["code"] as a literal."""
        cfg = PluckitConfig()
        assert cfg.resolve_source("code") == ["code"]


class TestCacheConfig:
    def test_cache_defaults_to_false(self, tmp_path):
        cfg = PluckitConfig.load(tmp_path)
        assert cfg.cache is False
        assert cfg.cache_path == ".pluckit.duckdb"

    def test_cache_from_config(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[tool.pluckit]\n'
            'cache = true\n'
            'cache_path = "custom.duckdb"\n'
        )
        cfg = PluckitConfig.load(tmp_path)
        assert cfg.cache is True
        assert cfg.cache_path == "custom.duckdb"

    def test_cache_false_explicit(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[tool.pluckit]\n'
            'cache = false\n'
        )
        cfg = PluckitConfig.load(tmp_path)
        assert cfg.cache is False
