"""Integration tests for parallel paper orders."""

from __future__ import annotations

import json
import sqlite3

import pytest

from trade_preflight.domain.policy import Policy
from trade_preflight.hooks import execution_gate as gate
from trade_preflight.services.audit import AuditStore
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


def test_parallel_allowed_orders_write_one_row_each(monkeypatch, policy, tmp_path):
    paper_trades.reset_handler_invocation_count()
    store = AuditStore(connection_factory=lambda: sqlite3.connect(str(tmp_path / "audit.db")))
    ledger_db = tmp_path / "ledger.db"
    monkeypatch.setattr(gate, "load_policy", lambda: policy)
    monkeypatch.setattr(gate, "default_audit_store", lambda: store)
    monkeypatch.setattr(paper_trades, "_ledger_connection_factory", lambda: sqlite3.connect(str(ledger_db)))

    orders = [
        ("p1", {"symbol": "AAPL", "side": "buy", "quantity": "10", "order_type": "limit", "limit_price": "100.00"}),
        ("p2", {"symbol": "MSFT", "side": "buy", "quantity": "5", "order_type": "limit", "limit_price": "200.00"}),
    ]

    for tool_call_id, args in orders:
        assert gate.pre_tool_call(tool_name="paper_place_order_a", args=args, tool_call_id=tool_call_id) is None

    for tool_call_id, args in orders:
        result = paper_trades.place_order_a(args)
        parsed = json.loads(result)
        assert parsed["status"] == "SUCCESS"
        gate.post_tool_call(
            tool_name="paper_place_order_a",
            result=result,
            status="success",
            tool_call_id=tool_call_id,
        )

    conn = sqlite3.connect(str(ledger_db))
    assert conn.execute("SELECT COUNT(*) FROM paper_ledger").fetchone()[0] == 2
    conn.close()

    rows = store.recent(10)
    assert sum(r["decision"] == "EXECUTION_SUCCEEDED" for r in rows) == 2


def test_blocked_order_leaves_ledger_empty(monkeypatch, policy, tmp_path):
    store = AuditStore(connection_factory=lambda: sqlite3.connect(str(tmp_path / "audit.db")))
    ledger_db = tmp_path / "ledger.db"
    monkeypatch.setattr(gate, "load_policy", lambda: policy)
    monkeypatch.setattr(gate, "default_audit_store", lambda: store)
    monkeypatch.setattr(paper_trades, "_ledger_connection_factory", lambda: sqlite3.connect(str(ledger_db)))

    result = gate.pre_tool_call(
        tool_name="paper_place_order_a",
        args={"symbol": "AAPL", "side": "buy", "quantity": "100", "order_type": "limit", "limit_price": "150.00"},
        tool_call_id="blocked-1",
    )
    assert result is not None and result["action"] == "block"

    conn = sqlite3.connect(str(ledger_db))
    # Schema may not exist yet because the handler never ran; ensure table exists.
    conn.executescript(__import__("pathlib").Path("src/trade_preflight/services/schema.sql").read_text())
    assert conn.execute("SELECT COUNT(*) FROM paper_ledger").fetchone()[0] == 0
    conn.close()

    rows = store.recent(10)
    assert any(r["tool_call_id"] == "blocked-1" and r["decision"] == "EXECUTION_BLOCKED" for r in rows)


def test_duplicate_tool_call_id_is_idempotent(monkeypatch, tmp_path):
    store = AuditStore(connection_factory=lambda: sqlite3.connect(str(tmp_path / "audit.db")))
    store.record_decision(
        tool_call_id="dup-1",
        tool_name="paper_place_order_a",
        order_json="{}",
        decision="EXECUTION_BLOCKED",
        reason="first",
        policy_hash="abc",
    )
    store.record_decision(
        tool_call_id="dup-1",
        tool_name="paper_place_order_a",
        order_json="{}",
        decision="EXECUTION_ALLOWED",
        reason="second",
        policy_hash="abc",
    )
    rows = store.recent(10)
    assert sum(r["tool_call_id"] == "dup-1" for r in rows) == 1