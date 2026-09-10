"""Payment capture.

`charge` writes to the ledger and then confirms with the downstream gateway.
`charge_with_retry` is how callers are expected to invoke it.
"""

from app.retry import with_retry


class PaymentService:
    def __init__(self, gateway):
        self.gateway = gateway
        self.ledger: list[dict] = []

    def charge(self, order_id: str, amount_cents: int) -> dict:
        """Record the charge, then confirm it downstream."""
        if amount_cents <= 0:
            raise ValueError("amount_cents must be positive")

        self.ledger.append({"order_id": order_id, "amount_cents": amount_cents})
        return self.gateway.confirm(order_id, amount_cents)

    def total_charged(self, order_id: str) -> int:
        """Sum of all ledger entries for an order."""
        return sum(e["amount_cents"] for e in self.ledger if e["order_id"] == order_id)


def charge_with_retry(
    service: PaymentService, order_id: str, amount_cents: int, attempts: int = 3
) -> dict:
    """Charge an order, retrying transient gateway failures."""
    return with_retry(
        lambda: service.charge(order_id, amount_cents), attempts=attempts
    )
