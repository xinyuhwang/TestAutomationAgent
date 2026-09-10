"""Generic retry helper.

Correct in isolation: it retries only transient failures, respects the attempt
budget, and re-raises the last error when the budget is exhausted.
"""

from typing import Callable, TypeVar

T = TypeVar("T")


class TransientError(Exception):
    """A failure the caller is expected to retry."""


def with_retry(fn: Callable[[], T], attempts: int = 3) -> T:
    """Call `fn`, retrying up to `attempts` times on TransientError."""
    if attempts < 1:
        raise ValueError("attempts must be at least 1")

    last_error: TransientError | None = None
    for _ in range(attempts):
        try:
            return fn()
        except TransientError as exc:
            last_error = exc
    raise last_error
