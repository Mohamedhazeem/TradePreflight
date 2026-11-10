"""Unit tests for ``NormalizedOrder`` and decimal parsing."""

from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation

import pytest

from trade_preflight.domain.order import (
    NormalizedOrder,
    OrderValidationError,
    calculate_notional,
    parse_decimal,
)


def test_parse_decimal_accepts_string_int_and_decimal():
    assert parse_decimal("42", "q") == Decimal("42")
    assert parse_decimal(7, "q") == Decimal("7")
    assert parse_decimal(Decimal("3.5"), "q") == Decimal("3.5")


def test_parse_decimal_rejects_bool_float_nan_and_invalid():
    for bad in (True, False, 1.0, float("nan"), float("inf"), "NaN", "Infinity", "", "fifty"):
        with pytest.raises(OrderValidationError):
            parse_decimal(bad, "q")


def test_calculate_notional_rounds_half_up_to_cents():
    assert calculate_notional(Decimal("3"), Decimal("0.005")) == Decimal("0.02")
    assert calculate_notional(Decimal("10"), Decimal("150.00")) == Decimal("1500.00")


def test_calculate_notional_rejects_non_positive_or_non_decimal():
    with pytest.raises(OrderValidationError):
        calculate_notional(Decimal("0"), Decimal("1"))
    with pytest.raises(OrderValidationError):
        calculate_notional(Decimal("1"), Decimal("-2"))
    with pytest.raises(OrderValidationError):
        calculate_notional(1, Decimal("1"))  # type: ignore[arg-type]


def test_normalized_order_create_canonicalizes_and_derives_notional():
    order = NormalizedOrder.create(
        symbol="aapl", side="BUY", quantity="10", order_type="LIMIT", limit_price="150.00"
    )
    assert order.symbol == "AAPL"
    assert order.side == "buy"
    assert order.order_type == "limit"
    assert order.quantity == Decimal("10")
    assert order.limit_price == Decimal("150.00")
    assert order.notional == Decimal("1500.00")
    assert order.to_dict()["quantity"] == "10"


def test_normalized_order_rejects_fractional_zero_negative_and_bad_fields():
    cases = [
        dict(quantity="1.5"),
        dict(quantity="0"),
        dict(quantity="-1"),
        dict(symbol=""),
        dict(side="hold"),
        dict(order_type="market"),
        dict(limit_price="0"),
        dict(quantity=True),
        dict(quantity=1.0),
    ]
    for override in cases:
        kwargs = dict(symbol="AAPL", side="buy", quantity="10", order_type="limit", limit_price="100.00")
        kwargs.update(override)
        with pytest.raises(OrderValidationError):
            NormalizedOrder.create(**kwargs)


def test_normalized_order_rejects_non_finite_limit_price():
    with pytest.raises(OrderValidationError):
        NormalizedOrder.create(
            symbol="AAPL", side="buy", quantity="1", order_type="limit", limit_price="NaN"
        )