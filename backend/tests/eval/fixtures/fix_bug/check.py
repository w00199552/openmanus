"""Completion check for the fix_bug task.

Verifies:
  1. search.py still exists and imports cleanly.
  2. binary_search returns correct results on the cases the bug broke.
  3. The test file runs green (Coder was asked to run it, so it must pass).

Note: we don't separately assert test_search.py is unmodified — running it
green is the real signal. If Coder gutted the tests, the check would either
fail to import or fail to catch the bug (covered by the direct assertions
in step 2, which don't depend on the test file).
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


def _load_module(workdir: Path):
    search = workdir / "search.py"
    if not search.exists():
        raise AssertionError("search.py is missing — was it deleted?")
    sys.path.insert(0, str(workdir))
    try:
        spec = importlib.util.spec_from_file_location("search_under_test", search)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path.pop(0)


def check(workdir: Path) -> dict:
    mod = _load_module(workdir)

    # 1. The cases the original bug broke now pass
    assert mod.binary_search([42], 42) == 0, "single-element found still broken"
    assert mod.binary_search([1, 2], 2) == 1, "two-element last still broken"
    # 2. Sanity on a normal case
    assert mod.binary_search([1, 3, 5, 7, 9], 5) == 2, "regression on normal case"
    assert mod.binary_search([1, 3, 5, 7, 9], 4) == -1, "not-found broken"

    # 3. Run the test file end-to-end (Coder was asked to run it)
    test_file = workdir / "test_search.py"
    if not test_file.exists():
        raise AssertionError("test_search.py was deleted — task says don't change it")
    result = subprocess.run(
        [sys.executable, str(test_file)],
        capture_output=True, text=True, cwd=str(workdir), timeout=10,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"test_search.py does not pass:\n{result.stdout}\n{result.stderr}"
        )

    return {
        "score": 1.0,
        "reason": "binary_search fixed, test_search.py runs green",
    }
