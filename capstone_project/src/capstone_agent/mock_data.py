"""Synthetic, non-PII order data used for demos/tests only (no real customers)."""
from datetime import datetime, timedelta, timezone


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).date().isoformat()


ORDERS = {
    # Control case: outside the 30-day window under either date field.
    "ORD-1001": {
        "order_id": "ORD-1001",
        "product": "Wireless Mouse",
        "order_date": _days_ago(50),
        "delivered_date": _days_ago(45),
        "status": "delivered",
    },
    # Bug-revealing case: order_date is >30 days ago but delivered_date is <30 days
    # ago (slow shipping). A version measuring from order_date wrongly says
    # ineligible; measuring from delivered_date (correct) says eligible.
    "ORD-1002": {
        "order_id": "ORD-1002",
        "product": "Bluetooth Headphones",
        "order_date": _days_ago(40),
        "delivered_date": _days_ago(15),
        "status": "delivered",
    },
    # Not yet delivered.
    "ORD-1003": {
        "order_id": "ORD-1003",
        "product": "Mechanical Keyboard",
        "order_date": _days_ago(5),
        "delivered_date": None,
        "status": "in_transit",
    },
}
