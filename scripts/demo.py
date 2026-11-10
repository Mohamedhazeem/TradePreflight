#!/usr/bin/env python3
"""Reproducible TradePreflight demo.

Runs the three orders from the 90-second storyboard against the live plugin code
without Hermes, a broker account, or network access. Prints the audit trail and
the handler/ledger counters a judge would inspect.

Usage:
    python scripts/demo.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from trade_preflight.domain.policy import Policy
from trade_preflight.hooks import execution_gate as gate
from trade_preflight.services.audit import AuditStore
from trade_preflight.tools import paper_trades


def section(title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def main() -> int:
    policy = Policy.from_mapping(
        {
            "max_gross_buy_notional_usd": "10000.00",
            "max_quantity": 200,
            "symbol_allowlist": ["AAPL", "MSFT"],
            "order_type_allowlist": ["limit"],
            "side_allowlist": ["buy"],
        }
    )

    tmp = tempfile.mkdtemp(prefix="tradepreflight-demo-")
    audit_db = Path(tmp) / "audit.db"
    ledger_db = Path(tmp) / "ledger.db"

    store = AuditStore(connection_factory=lambda: sqlite3.connect(str(audit_db)))
    gate.default_audit_store = lambda: store
    gate.load_policy = lambda: policy
    paper_trades.reset_handler_invocation_count()
    paper_trades._ledger_connection_factory = lambda: sqlite3.connect(str(ledger_db))

    scenarios = [
        (
            "Scenario 1 - 100 shares AAPL @ $150 (Broker A)",
            "paper_place_order_a",
            {"symbol": "AAPL", "side": "buy", "quantity": "100", "order_type": "limit", "limit_price": "150.00"},
            "c1",
        ),
        (
            "Scenario 2 - 10 shares TSLA @ $200 (Broker B)",
            "paper_place_order_b",
            {"ticker": "TSLA", "direction": "buy", "qty": "10", "order_type": "limit", "price": "200.00"},
            "c2",
        ),
        (
            "Scenario 3 - 20 shares AAPL @ $150 (Broker A)",
            "paper_place_order_a",
            {"symbol": "AAPL", "side": "buy", "quantity": "20", "order_type": "limit", "limit_price": "150.00"},
            "c3",
        ),
    ]

    for title, tool, args, call_id in scenarios:
        section(title)
        decision = gate.pre_tool_call(tool_name=tool, args=args, tool_call_id=call_id)
        if decision is not None:
            print(f"RESULT: BLOCKED - {decision['message']}")
            continue

        handler = (
            paper_trades.place_order_a if tool == "paper_place_order_a" else paper_trades.place_order_b
        )
        result = handler(args)
        parsed = json.loads(result)
        print(f"RESULT: ALLOWED - {parsed['message']} (order_id={parsed['order_id']})")
        gate.post_tool_call(
            tool_name=tool, result=result, status="success", tool_call_id=call_id
        )

    section("Audit trail (newest first)")
    for row in store.recent(10):
        print(f"{row['tool_call_id']:<6} {row['decision']:<24} {row['reason']}")

    section("Counters")
    conn = sqlite3.connect(str(ledger_db))
    ledger_rows = conn.execute("SELECT COUNT(*) FROM paper_ledger").fetchone()[0]
    conn.close()
    print(f"Handler invocation count : {paper_trades.handler_invocation_count}")
    print(f"Paper ledger rows        : {ledger_rows}")

    section("Validation")
    print("Run: hermes plugins doctor . --ci")
    print("Run: hermes plugins validate .")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())