"""Unit tests for the broker adapters."""

from __future__ import annotations

import pytest

from trade_preflight.adapters import AdapterError, get_adapter


def test_broker_a_and_b_produce_identical_normalized_orders():
    a = get_adapter("paper_place_order_a").normalize(
        {
            "symbol": "aapl",
            "side": "BUY",
            "quantity": "10",
            "order_type": "LIMIT",
            "limit_price": "150.00",
        }
    )
    b = get_adapter("paper_place_order_b").normalize(
        {
            "ticker": "AAPL",
            "direction": "buy",
            "qty": 10,
            "order_type": "limit",
            "price": "150.00",
        }
    )
    assert a.to_dict() == b.to_dict()


def test_adapters_reject_missing_and_invalid_fields():
    adapter = get_adapter("paper_place_order_a")
    with pytest.raises(AdapterError):
        adapter.normalize({"symbol": "AAPL"})
    with pytest.raises(AdapterError):
        adapter.normalize(
            {
                "symbol": "AAPL",
                "side": "buy",
                "quantity": "fifty",
                "order_type": "limit",
                "limit_price": "100",
            }
        )

    b = get_adapter("paper_place_order_b")
    with pytest.raises(AdapterError):
        b.normalize({"ticker": "AAPL"})


def test_unknown_tool_has_no_adapter():
    assert get_adapter("terminal") is None