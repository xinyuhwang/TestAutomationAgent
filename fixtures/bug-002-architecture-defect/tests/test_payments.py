"""Existing test suite. Passes in full.

Note what it does not do: every retry test uses a side-effect-free callable,
and every charge test uses a gateway that never fails. The two are never
composed, which is exactly where the seeded defect lives.
"""

import pytest

from app.payments import PaymentService, charge_with_retry
from app.retry import TransientError, with_retry


class AlwaysOkGateway:
    def confirm(self, order_id, amount_cents):
        return {"order_id": order_id, "status": "confirmed"}


def test_charge_records_one_ledger_entry():
    service = PaymentService(AlwaysOkGateway())
    service.charge("order-1", 500)
    assert service.total_charged("order-1") == 500


def test_charge_returns_gateway_confirmation():
    service = PaymentService(AlwaysOkGateway())
    assert service.charge("order-1", 500)["status"] == "confirmed"


def test_charge_rejects_non_positive_amount():
    service = PaymentService(AlwaysOkGateway())
    with pytest.raises(ValueError):
        service.charge("order-1", 0)


def test_charge_with_retry_succeeds_on_healthy_gateway():
    service = PaymentService(AlwaysOkGateway())
    assert charge_with_retry(service, "order-1", 500)["status"] == "confirmed"
    assert service.total_charged("order-1") == 500


def test_with_retry_recovers_from_transient_failure():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise TransientError("downstream hiccup")
        return "ok"

    assert with_retry(flaky, attempts=3) == "ok"
    assert calls["n"] == 3


def test_with_retry_reraises_after_budget_exhausted():
    def always_fails():
        raise TransientError("still down")

    with pytest.raises(TransientError):
        with_retry(always_fails, attempts=3)


def test_with_retry_rejects_zero_attempts():
    with pytest.raises(ValueError):
        with_retry(lambda: "ok", attempts=0)
