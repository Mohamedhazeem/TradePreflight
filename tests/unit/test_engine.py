"""Unit tests for the policy engine rules."""

from __future__ import annotations

from decimal import Decimal

import pytest

from trade_preflight.domain.order import NormalizedOrder
from trade_preflight.domain.policy import Policy
from trade_preflight.services.engine import PolicyEngine


def _policy(**overrides):
    data = {
        "max_gross_buy_notional_usd": "10000.00",
        "max_quantity": 200,
        "symbol_allowlist": ["AAPL", "MSFT"],
        "order_type_allowlist": ["limit"],
        "side_allowlist": ["buy"],
    }
    data.update(overrides)
    return Policy.from_mapping(data)


def _order(**overrides):
    kwargs = dict(symbol="AAPL", side="buy", quantity="10", order_type="limit", limit_price="100.00")
    kwargs.update(overrides)
    return NormalizedOrder.create(**kwargs)


def test_allowed_order_passes_all_rules():
    decision = PolicyEngine(_policy()).evaluate(_order())
    assert decision.allowed is True
    assert decision.rule == "policy"


def test_side_allowlist_blocks_disallowed_side():
    decision = PolicyEngine(_policy()).evaluate(_order(side="sell"))
    assert decision.allowed is False
    assert decision.rule == "side_allowlist"


def test_symbol_allowlist_blocks_unknown_symbol():
    decision = PolicyEngine(_policy()).evaluate(_order(symbol="TSLA"))
    assert decision.allowed is False
    assert decision.rule == "symbol_allowlist"


def test_order_type_allowlist_blocks_disallowed_type():
    decision = PolicyEngine(_policy(order_type_allowlist=["market"])).evaluate(_order())
    assert decision.allowed is False
    assert decision.rule == "order_type_allowlist"


def test_max_quantity_blocks_oversized_order():
    decision = PolicyEngine(_policy()).evaluate(_order(quantity="201"))
    assert decision.allowed is False
    assert decision.rule == "max_quantity"
    assert "201" in decision.reason


def test_max_gross_buy_notional_blocks_large_order():
    # 100 shares @ $150 = $15,000 > $10,000
    decision = PolicyEngine(_policy()).evaluate(_order(quantity="100", limit_price="150.00"))
    assert decision.allowed is False
    assert decision.rule == "max_gross_buy_notional_usd"
    assert "15000.00" in decision.reason


def test_boundary_values_are_allowed():
    decision = PolicyEngine(_policy()).evaluate(_order(quantity="200", limit_price="50.00"))
    assert decision.allowed is True  # 200 shares, $10,000 notional


def test_engine_rejects_wrong_input_types():
    with pytest.raises(TypeError):
        PolicyEngine("not a policy")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        PolicyEngine(_policy()).evaluate("not an order")  # type: ignore[arg-type]