"""Test suite for RateLimiter.

One of these tests fails intermittently. The application code is correct; the
failure is a property of the test, not of the limiter.
"""

import threading
import time

from app.rate_limiter import RateLimiter

CAPACITY = 15


def _submit_concurrently(limiter: RateLimiter, n: int) -> dict[int, bool]:
    """Fire `n` acquire attempts, staggered slightly, and collect outcomes."""
    results: dict[int, bool] = {}

    def worker(i: int) -> None:
        time.sleep(i * 0.004)  # submit roughly in id order
        results[i] = limiter.try_acquire(i)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def test_admits_everything_below_capacity():
    limiter = RateLimiter(CAPACITY)
    results = _submit_concurrently(limiter, 10)
    assert all(results.values())
    assert limiter.remaining == 5


def test_admits_exactly_capacity_under_high_concurrency():
    limiter = RateLimiter(CAPACITY)
    results = _submit_concurrently(limiter, 20)
    assert sum(results.values()) == CAPACITY
    assert limiter.remaining == 0


def test_rejects_when_full():
    limiter = RateLimiter(1)
    assert limiter.try_acquire(1) is True
    assert limiter.try_acquire(2) is False


def test_admits_first_arrivals_under_high_concurrency():
    limiter = RateLimiter(CAPACITY)
    _submit_concurrently(limiter, 20)
    assert limiter.admitted == list(range(CAPACITY))
