# tests/test_source.py
"""Tests for Source type."""
import pytest

from pluckit.source import Source


def test_source_stores_glob(ctx):
    s = ctx.source("src/**/*.py")
    assert s.glob == "src/**/*.py"


def test_source_find_returns_selection(ctx):
    s = ctx.source("src/**/*.py")
    sel = s.find(".function")
    from pluckit.selection import Selection
    assert isinstance(sel, Selection)


def test_source_find_functions(ctx):
    s = ctx.source("src/**/*.py")
    sel = s.find(".function")
    # Sample files have: validate_token, process_data, __init__,
    # authenticate, _internal_helper, send_email, parse_header
    assert sel.count() >= 6


def test_source_resolves_glob_relative_to_repo(ctx, sample_dir):
    s = ctx.source("src/auth.py")
    sel = s.find(".function")
    names = sel.names()
    assert "validate_token" in names
