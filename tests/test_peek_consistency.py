"""peek must be populated regardless of which selector form was used.

``ast_select`` parses with ``peek := 'none'``, so its peek column is always
NULL. :func:`ast_select_sql` recovers the real ``read_ast`` row by joining on
node identity — but historically only when the selector carried a pluckit
post-filter (``:contains``, ``:async``, …). A plain structural selector took the
no-join branch and silently returned NULL peek, so whether a caller got source
text depended on which pseudo-classes they happened to use.
"""
import pytest

from pluckit import Plucker
from pluckit.pluckins.viewer import AstViewer


SRC = "function foo(x) {\n    return x + 1;\n}\n"


@pytest.fixture
def js(tmp_path):
    p = tmp_path / "sample.js"
    p.write_text(SRC)
    return str(p)


def _peek(plucker, selector):
    rel = plucker.find(selector).relation
    cols = list(rel.columns)
    assert "peek" in cols, f"peek column missing for {selector!r}"
    rows = rel.fetchall()
    assert rows, f"no rows for {selector!r}"
    return rows[0][cols.index("peek")]


def test_peek_populated_without_post_filter(js):
    """Plain structural selector — the branch that used to skip the join."""
    p = Plucker(plugins=[AstViewer])
    p._code_source = js
    assert _peek(p, ".fn"), "peek is NULL for a plain structural selector"


def test_peek_consistent_across_selector_forms(js):
    """Same node reached two ways must carry the same peek."""
    p = Plucker(plugins=[AstViewer])
    p._code_source = js
    plain = _peek(p, ".fn")
    filtered = _peek(p, ".fn:contains(return)")
    assert plain == filtered


def test_schema_matches_read_ast(js):
    """The no-filter branch must not leak ast_select's extra columns."""
    p = Plucker(plugins=[AstViewer])
    p._code_source = js
    cols = set(p.find(".fn").relation.columns)
    assert "start_column" not in cols
    assert "end_column" not in cols
