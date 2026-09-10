# Admission rate limiter

A capacity-based admission limiter used to shed load: it admits a fixed number
of concurrent requests and rejects the rest.

## Intended behaviour

- `RateLimiter(capacity)` — `capacity` must not be negative.
- `try_acquire(request_id)` — admit the request if there is room; returns
  whether it was admitted. Safe to call from multiple threads.
- `admitted` — request ids that were admitted, in the order they reached the
  lock.
- `remaining` — unused capacity.

**Guaranteed:** at most `capacity` requests are ever admitted, no matter how
many threads call `try_acquire` concurrently.

**Not guaranteed:** *which* requests win under contention. Admission order is
whatever order callers reach the lock in, and the limiter makes no promise
about it.

## Running the tests

```bash
python -m pytest
```

One test in this suite fails intermittently.
