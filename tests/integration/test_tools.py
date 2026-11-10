"""Integration tests for the read-only admin tools."""

from __future__ import annotations

import json

import pytest

from trade_preflight.domain.policy import Policy
from trade_preflight.services.audit import AuditStore
from trade_preflight.tools import admin


@pytest.fixture
def policy():
    return Policy.from_mapping(
        {
            "max_gross_buy_notional_usd": "10000.00",
            "max_quantity": 200,
            "symbol_allowlist": ["AAPL", "MSFT"],
            "order_type_allowlist": ["limit"],
            "side_allowlist": ["buy"],
        }
    )


def test_trade_policy_get_returns_policy_and_hash(monkeypatch, policy):
    monkeypatch.setattr(admin, "load_policy", lambda: policy)
    payload = json.loads(admin.trade_policy_get({}))
    assert payload["status"] == "OK"
    assert payload["policy"]["max_quantity"] == 200
    assert payload["sha256"] == policy.sha256()


def test_trade_check_allows_compliant_order(monkeypatch, policy):
    monkeypatch.setattr(admin, "load_policy", lambda: policy)
    payload = json.loads(
        admin.trade_check(
            {
                "symbol": "AAPL",
                "side": "buy",
                "quantity": "10",
                "order_type": "limit",
                "limit_price": "100.00",
            }
        )
    )
    assert payload["allowed"] is True
    assert payload["rule"] == "policy"


def test_trade_check_blocks_notional_violation(monkeypatch, policy):
    monkeypatch.setattr(admin, "load_policy", lambda: policy)
    payload = json.loads(
        admin.trade_check(
            {
                "symbol": "AAPL",
                "side": "buy",
                "quantity": "100",
                "order_type": "limit",
                "limit_price": "150.00",
            }
        )
    )
    assert payload["allowed"] is False
    assert payload["rule"] == "max_gross_buy_notional_usd"


def test_trade_audit_returns_rows(monkeypatch, tmp_path):
    store = AuditStore(connection_factory=lambda: __import__("sqlite3").connect(str(tmp_path / "audit.db")))
    monkeypatch.setattr(admin, "default_audit_store", lambda: store)
    store.record_decision(
        tool_call_id="t1",
        tool_name="paper_place_order_a",
        order_json="{}",
        decision="EXECUTION_BLOCKED",
        reason="test",
        policy_hash="abc",
    )
    payload = json.loads(admin.trade_audit({"limit": 10}))
    assert payload["status"] == "OK"
    assert payload["count"] == 1
    assert payload["entries"][0]["tool_call_id"] == "t1"