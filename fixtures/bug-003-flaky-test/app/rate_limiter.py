"""A capacity-based admission limiter.

Contract: at most `capacity` requests are ever admitted, and the counter is
safe to call from multiple threads. The limiter deliberately makes *no*
promise about *which* requests win under contention — admission order is
whatever order callers reach the lock in.
"""

import threading


class RateLimiter:
    def __init__(self, capacity: int):
        if capacity < 0:
            raise ValueError("capacity must not be negative")
        self.capacity = capacity
        self._lock = threading.Lock()
        self._admitted: list[int] = []

    def try_acquire(self, request_id: int) -> bool:
        """Admit `request_id` if there is room. Returns whether it was admitted."""
        with self._lock:
            if len(self._admitted) >= self.capacity:
                return False
            self._admitted.append(request_id)
            return True

    @property
    def admitted(self) -> list[int]:
        """Request ids that were admitted, in the order they reached the lock."""
        with self._lock:
            return list(self._admitted)

    @property
    def remaining(self) -> int:
        with self._lock:
            return self.capacity - len(self._admitted)
