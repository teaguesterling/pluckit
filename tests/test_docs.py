"""Tests for DocSelection and the docs= parameter."""
from __future__ import annotations

import textwrap

import pytest

from pluckit import DocSelection, Plucker
from pluckit.pluckins.search import Search
from pluckit.types import PluckerError


def _fledgling_available():
    try:
        import fledgling
        return True
    except ImportError:
        return False


requires_fledgling = pytest.mark.skipif(
    not _fledgling_available(),
    reason="fledgling not installed",
)


SAMPLE_DOCS = textwrap.dedent("""\
    # Project Guide

    Welcome to the project.

    ## Installation

    Run `pip install myproject` to get started.

    ## Authentication

    This section covers auth flows.

    ### Token Validation

    Tokens are validated using JWT verification.

    ### Password Hashing

    Passwords are hashed with bcrypt.

    ## Database

    Configure the database connection.
""")

SAMPLE_CHANGELOG = textwrap.dedent("""\
    # Changelog

    ## v1.0

    Initial release.

    ## v0.9

    Beta release with auth support.
""")


@pytest.fixture
def docs_dir(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text(SAMPLE_DOCS)
    (docs / "changelog.md").write_text(SAMPLE_CHANGELOG)
    return tmp_path


@pytest.fixture
def pluck_with_docs(docs_dir):
    return Plucker(
        docs=str(docs_dir / "docs/**/*.md"),
        repo=str(docs_dir),
    )


class TestDocsParameter:
    def test_docs_creates_plucker(self, docs_dir):
        p = Plucker(docs=str(docs_dir / "docs/**/*.md"))
        assert p._docs_source is not None

    def test_docs_without_param_raises(self):
        p = Plucker()
        with pytest.raises(PluckerError, match="No docs source"):
            p.docs()

    def test_docs_returns_doc_selection(self, pluck_with_docs):
        result = pluck_with_docs.docs()
        assert isinstance(result, DocSelection)

    def test_docs_has_sections(self, pluck_with_docs):
        result = pluck_with_docs.docs()
        assert result.count() > 0

    def test_both_code_and_docs(self, docs_dir):
        src = docs_dir / "src"
        src.mkdir()
        (src / "main.py").write_text("def hello(): pass\n")
        p = Plucker(
            code=str(docs_dir / "src/**/*.py"),
            docs=str(docs_dir / "docs/**/*.md"),
        )
        assert p.find(".fn").count() > 0
        assert p.docs().count() > 0


class TestDocSelectionTerminals:
    def test_titles(self, pluck_with_docs):
        titles = pluck_with_docs.docs().titles()
        assert "Installation" in titles
        assert "Authentication" in titles

    def test_count(self, pluck_with_docs):
        n = pluck_with_docs.docs().count()
        assert n >= 5

    def test_files(self, pluck_with_docs):
        files = pluck_with_docs.docs().files()
        assert len(files) == 2
        assert any("guide.md" in f for f in files)
        assert any("changelog.md" in f for f in files)

    def test_content(self, pluck_with_docs):
        contents = pluck_with_docs.docs().content()
        assert len(contents) > 0
        assert any("pip install" in c for c in contents)

    def test_sections(self, pluck_with_docs):
        sections = pluck_with_docs.docs().sections()
        assert len(sections) > 0
        assert "title" in sections[0]
        assert "level" in sections[0]

    def test_len(self, pluck_with_docs):
        ds = pluck_with_docs.docs()
        assert len(ds) == ds.count()

    def test_repr(self, pluck_with_docs):
        ds = pluck_with_docs.docs()
        r = repr(ds)
        assert "DocSelection" in r
        assert "sections" in r


class TestDocSelectionFilter:
    def test_filter_by_level(self, pluck_with_docs):
        h2_only = pluck_with_docs.docs().filter(level=2)
        titles = h2_only.titles()
        assert "Installation" in titles
        assert "Token Validation" not in titles

    def test_filter_by_max_level(self, pluck_with_docs):
        top = pluck_with_docs.docs().filter(max_level=1)
        titles = top.titles()
        assert "Project Guide" in titles or "Changelog" in titles
        assert "Installation" not in titles

    def test_filter_by_search(self, pluck_with_docs):
        auth = pluck_with_docs.docs().filter(search="auth")
        titles = auth.titles()
        assert len(titles) > 0

    def test_outline(self, pluck_with_docs):
        outline = pluck_with_docs.docs().outline(max_level=2)
        titles = outline.titles()
        assert "Installation" in titles
        assert "Token Validation" not in titles

    def test_filter_chaining(self, pluck_with_docs):
        result = pluck_with_docs.docs().filter(max_level=2).filter(search="auth")
        assert result.count() > 0

    def test_filter_by_file_path(self, pluck_with_docs):
        guide_only = pluck_with_docs.docs().filter(file_path="guide")
        files = guide_only.files()
        assert len(files) == 1
        assert "guide.md" in files[0]


@requires_fledgling
class TestDocSelectionSearch:
    @pytest.fixture
    def pluck_fts_docs(self, docs_dir):
        src = docs_dir / "src"
        src.mkdir(exist_ok=True)
        (src / "stub.py").write_text("def stub(): pass\n")
        p = Plucker(
            code=str(docs_dir / "src/**/*.py"),
            docs=str(docs_dir / "docs/**/*.md"),
            plugins=[Search],
            repo=str(docs_dir),
        )
        if not p._ctx._fledgling_loaded:
            pytest.skip("fledgling not loaded")
        p.rebuild_fts(
            docs_glob=str(docs_dir / "docs/**/*.md"),
            code_glob=str(docs_dir / "src/**/*.py"),
        )
        return p

    def test_search_returns_doc_selection(self, pluck_fts_docs):
        result = pluck_fts_docs.docs().search("authentication")
        assert isinstance(result, DocSelection)
        assert result.count() > 0

    def test_search_respects_filter_chain(self, pluck_fts_docs):
        all_results = pluck_fts_docs.docs().search("database")
        filtered = pluck_fts_docs.docs().filter(file_path="guide").search("database")
        guide_files = filtered.files()
        assert all("guide" in f for f in guide_files)

    def test_search_no_match(self, pluck_fts_docs):
        result = pluck_fts_docs.docs().search("zzzznonexistentzzzz")
        assert result.count() == 0


class TestDocsSerialization:
    def test_to_dict_includes_docs(self, docs_dir):
        p = Plucker(
            code="**/*.py",
            docs=str(docs_dir / "docs/**/*.md"),
        )
        d = p.to_dict()
        assert "docs" in d

    def test_from_dict_restores_docs(self, docs_dir):
        original = Plucker(
            code="**/*.py",
            docs=str(docs_dir / "docs/**/*.md"),
        )
        restored = Plucker.from_dict(original.to_dict())
        assert restored._docs_source == original._docs_source
