"""Completion check for the add_param task.

Verifies:
  1. format_price now accepts a tax_rate parameter.
  2. tax_rate defaults to 0 (backwards compatible).
  3. tax_rate > 0 applies the tax correctly.
  4. All call sites were updated to pass tax_rate explicitly.
  5. Unrelated code (the demo block, other functions) was not broken.
"""
from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path


def _load_module(workdir: Path):
    calc = workdir / "calc.py"
    if not calc.exists():
        raise AssertionError("calc.py is missing — was it deleted?")
    sys.path.insert(0, str(workdir))
    try:
        spec = importlib.util.spec_from_file_location("calc_under_test", calc)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod, calc.read_text(encoding="utf-8")
    finally:
        sys.path.pop(0)


def check(workdir: Path) -> dict:
    mod, source = _load_module(workdir)

    # 1. format_price signature has tax_rate
    sig = inspect.signature(mod.format_price)
    if "tax_rate" not in sig.parameters:
        raise AssertionError(f"format_price has no tax_rate param: {sig}")
    param = sig.parameters["tax_rate"]
    if param.default != 0 and param.default != 0.0:
        raise AssertionError(f"tax_rate should default to 0, got default={param.default!r}")

    # 2. backwards compatible: tax_rate=0 → same as before
    assert mod.format_price(3.5) == "$3.50", "default tax_rate broke the no-tax case"

    # 3. tax_rate applies correctly
    assert mod.format_price(3.5, tax_rate=0.0) == "$3.50", "tax_rate=0.0 wrong"
    # 3.5 * 1.08 = 3.78
    assert mod.format_price(3.5, tax_rate=0.08) == "$3.78", "tax_rate=0.08 wrong"
    # 100 * 1.20 = 120.00
    assert mod.format_price(100, "USD", tax_rate=0.20) == "$120.00", "tax with currency wrong"

    # 4. callers updated to pass tax_rate explicitly.
    # Count explicit `tax_rate=` mentions in the source (outside the def line).
    lines_with_tax = [
        ln for ln in source.splitlines()
        if "tax_rate=" in ln and "def format_price" not in ln
    ]
    # There are 2 call sites: receipt_line and grand_total.
    if len(lines_with_tax) < 2:
        raise AssertionError(
            f"only {len(lines_with_tax)} call site(s) updated to pass tax_rate= explicitly, "
            f"expected ≥2 (receipt_line + grand_total)"
        )

    return {
        "score": 1.0,
        "reason": (
            "tax_rate param added with correct default, tax math correct, "
            f"{len(lines_with_tax)} call sites updated"
        ),
    }
