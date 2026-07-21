"""A binary search module with a bug for the fix_bug task.

There is a bug in `binary_search`: it returns the wrong index in some cases.
Coder must find it, fix it, and verify with the existing test.

This tests the Doing-tasks workflow from the prompt:
  1. search/read to understand the code
  2. locate the bug
  3. fix it
  4. run the test to verify
"""


def binary_search(arr: list[int], target: int) -> int:
    """Return the index of `target` in sorted `arr`, or -1 if not found."""
    lo = 0
    hi = len(arr) - 1
    while lo < hi:                      # BUG: should be <=
        mid = (lo + hi) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            lo = mid + 1
        else:
            hi = mid                    # BUG: should be mid - 1
    return -1
