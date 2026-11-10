"""Integration tests for the fail-closed execution gate."""

from __future__ import annotations

import json
import sqlite3
import tempfile

import pytest

from trade_preflight.domain.policy import Policy
from trade_preflight.services.audit import AuditStore
from trade_preflight.hooks import execution_gate as gate
from trade_preflight.tools import paper_trades


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


@pytest.fixture
def store(tmp_path):
    return AuditStore(connection_factory=lambda: sqlite3.connect(str(tmp_path / "audit.db")))


def test_allowed_order_is_audited_and_handler_runs(monkeypatch, policy, store):
    paper_trades.reset_handler_invocation_count()
    monkeypatch.setattr(gate, "load_policy", lambda: policy)
    monkeypatch.setattr(gate, "default_audit_store", lambda: store)

    result = gate.pre_tool_call(
        tool_name="paper_place_order_a",
        args={"symbol": "AAPL", "side": "buy", "quantity": "10", "order_type": "limit", "limit_price": "100.00"},
        tool_call_id="allow-1",
    )
    assert result is None

    handler_result = paper_trades.place_order_a(
        {"symbol": "AAPL", "side": "buy", "quantity": "10", "order_type": "limit", "limit_price": "100.00"}
    )
    assert json.loads(handler_result)["status"] == "SUCCESS"

    gate.post_tool_call(
        tool_name="paper_place_order_a",
        result=handler_result,
        status="success",
        tool_call_id="allow-1",
    )

    rows = store.recent(10)
    assert any(r["tool_call_id"] == "allow-1" and r["decision"] == "EXECUTION_SUCCEEDED" for r in rows)


def test_notional_violation_is_blocked_and_audited(monkeypatch, policy, store):
    monkeypatch.setattr(gate, "load_policy", lambda: policy)
    monkeypatch.setattr(gate, "default_audit_store", lambda: store)

    result = gate.pre_tool_call(
        tool_name="paper_place_order_a",
        args={"symbol": "AAPL", "side": "buy", "quantity": "100", "order_type": "limit", "limit_price": "150.00"},
        tool_call_id="block-1",
    )
    assert result is not None and result["action"] == "block"
    assert "max_gross_buy_notional_usd" in result["message"]

    rows = store.recent(10)
    assert any(r["tool_call_id"] == "block-1" and r["decision"] == "EXECUTION_BLOCKED" for r in rows)


def test_fail_closed_on_corrupt_policy(monkeypatch, store):
    def boom():
        raise ValueError("corrupt policy")

    monkeypatch.setattr(gate, "load_policy", boom)
    monkeypatch.setattr(gate, "default_audit_store", lambda: store)

    result = gate.pre_tool_call(
        tool_name="paper_place_order_b",
        args={"ticker": "AAPL", "direction": "buy", "qty": "10", "order_type": "limit", "price": "100.00"},
        tool_call_id="fail-1",
    )
    assert result is not None and result["action"] == "block"
    assert "policy evaluation failed" in result["message"].lower()

    rows = store.recent(10)
    assert any(r["tool_call_id"] == "fail-1" and r["decision"] == "EXECUTION_BLOCKED" for r in rows)