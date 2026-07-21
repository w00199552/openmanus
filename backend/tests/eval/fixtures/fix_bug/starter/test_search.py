"""Test for binary_search. Coder should run this to verify the fix."""
import sys
from pathlib import Path

# Make the workdir importable when running `python test_search.py`
sys.path.insert(0, str(Path(__file__).parent))
from search import binary_search


def test_found():
    assert binary_search([1, 3, 5, 7, 9], 5) == 2


def test_first_element():
    assert binary_search([1, 3, 5, 7, 9], 1) == 0


def test_last_element():
    assert binary_search([1, 3, 5, 7, 9], 9) == 4


def test_not_found():
    assert binary_search([1, 3, 5, 7, 9], 4) == -1


def test_single_element_found():
    assert binary_search([42], 42) == 0     # this fails with the bug


def test_single_element_not_found():
    assert binary_search([42], 7) == -1


def test_two_elements():
    assert binary_search([1, 2], 1) == 0
    assert binary_search([1, 2], 2) == 1    # this fails with the bug


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL {name}: {e}")
    if failures:
        print(f"\n{failures} test(s) failed")
        sys.exit(1)
    print(f"\nAll tests passed")
