"""Path display helpers.

When pluckit is invoked in a directory that's far from the files it's
querying (e.g., `pluckit view ... /home/x/other-project/**/*.py` from a
deeply nested cwd), a naive ``os.path.relpath`` produces monstrosities
like ``../../../../../../home/x/other-project/src/foo.py``. This module
picks a saner display form.
"""
from __future__ import annotations

import os
from pathlib import Path


def display_path(file_path: str, base: str | None = None) -> str:
    """Return a short, human-readable display path for ``file_path``.

    Rules (applied in order, first match wins):

    1. If ``file_path`` is under ``base`` (or the given base is itself
       inside ``file_path``'s parent), return a plain relative path.
       This is the common case and looks like ``src/pluckit/cli.py``.
    2. If ``file_path`` is under the user's home directory, substitute
       ``~/`` for the home prefix. This is still absolute-ish but much
       shorter than six levels of ``..``.
    3. Otherwise, return the absolute path unchanged.

    The function never raises — any OSError / ValueError produces the
    input path as-is.
    """
    try:
        abs_path = os.path.abspath(file_path)
    except (OSError, ValueError):
        return file_path

    base_abs = os.path.abspath(base) if base else os.getcwd()

    try:
        rel = os.path.relpath(abs_path, base_abs)
    except ValueError:
        # Windows: different drives. Fall through to home substitution.
        rel = abs_path

    # If the relative path doesn't escape upward, it's already good.
    if not rel.startswith(".."):
        return rel

    # File is outside the base. Try ~ substitution.
    try:
        home = str(Path.home())
    except (OSError, RuntimeError):
        home = None

    if home and abs_path.startswith(home + os.sep):
        return "~" + abs_path[len(home):]

    return abs_path
