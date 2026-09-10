# Payment capture

Captures a payment by recording it in a ledger and confirming it with a
downstream payment gateway. The gateway is unreliable and can fail transiently,
so callers are expected to go through the retry wrapper.

## Intended behaviour

- `PaymentService.charge(order_id, amount_cents)` — record the charge and
  confirm it downstream. `amount_cents` must be positive.
- `PaymentService.total_charged(order_id)` — sum of ledger entries for an
  order. **A customer must never be charged more than they authorised.**
- `charge_with_retry(service, order_id, amount_cents, attempts=3)` — the
  supported entry point; survives transient gateway failures.
- `with_retry(fn, attempts)` — retries `fn` on `TransientError`, re-raising the
  last error once the attempt budget is spent.

## Running the tests

```bash
python -m pytest
```
