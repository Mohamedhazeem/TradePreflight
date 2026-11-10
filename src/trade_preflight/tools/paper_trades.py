"""Paper-trading tool schemas and handlers (Broker A and Broker B).

Slice 3 implementation: each handler validates its arguments through the adapter,
inserts one row into ``paper_ledger``, and returns a simulated success payload.
No real broker or network call is made.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..adapters import get_adapter

__all__ = [
    "PAPER_PLACE_ORDER_A",
    "PAPER_PLACE_ORDER_B",
    "handler_invocation_count",
    "place_order_a",
    "place_order_b",
    "reset_handler_invocation_count",
]

_DECIMAL_STRING = (
    "Decimal value encoded as a string. Floats are rejected by the domain layer; "
    "send strings such as \"10\" or \"150.00\"."
)

_PLUGIN_NAME = "trade-preflight"
_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "services" / "schema.sql"


def _default_ledger_connection_factory():
    from plugins.plugin_storage import plugin_db

    return plugin_db(_PLUGIN_NAME)


PAPER_PLACE_ORDER_A: dict[str, Any] = {
    "name": "paper_place_order_a",
    "description": (
        "Simulated Broker A equity order. This is a paper trade: no real broker "
        "or network call is made. Before execution, TradePreflight normalizes "
        "the order and blocks it unless it satisfies the operator policy. "
        "Limit orders only; whole shares only."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "Equity ticker, e.g. \"AAPL\".",
            },
            "side": {
                "type": "string",
                "enum": ["buy", "sell"],
                "description": "Order side. The default policy permits buys only.",
            },
            "quantity": {
                "type": "string",
                "description": "Whole-share quantity. " + _DECIMAL_STRING,
            },
            "order_type": {
                "type": "string",
                "enum": ["limit"],
                "description": "Order type. The MVP supports limit orders only.",
            },
            "limit_price": {
                "type": "string",
                "description": "Limit price per share. " + _DECIMAL_STRING,
            },
        },
        "required": ["symbol", "side", "quantity", "order_type", "limit_price"],
        "additionalProperties": False,
    },
}

PAPER_PLACE_ORDER_B: dict[str, Any] = {
    "name": "paper_place_order_b",
    "description": (
        "Simulated Broker B equity order. This is a paper trade: no real broker "
        "or network call is made. Broker B uses ticker/direction/qty/price; the "
        "adapter normalizes it to the same canonical order as Broker A, so the "
        "same policy applies. Limit orders only; whole shares only."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "ticker": {
                "type": "string",
                "description": "Equity ticker, e.g. \"MSFT\".",
            },
            "direction": {
                "type": "string",
                "enum": ["buy", "sell"],
                "description": "Order direction. The default policy permits buys only.",
            },
            "qty": {
                "type": "string",
                "description": "Whole-share quantity. " + _DECIMAL_STRING,
            },
            "order_type": {
                "type": "string",
                "enum": ["limit"],
                "description": "Order type. The MVP supports limit orders only.",
            },
            "price": {
                "type": "string",
                "description": "Limit price per share. " + _DECIMAL_STRING,
            },
        },
        "required": ["ticker", "direction", "qty", "order_type", "price"],
        "additionalProperties": False,
    },
}

handler_invocation_count: int = 0
_order_counter: int = 0


def reset_handler_invocation_count() -> None:
    """Reset the invocation counter. Intended for tests and fresh sessions."""
    global handler_invocation_count, _order_counter
    handler_invocation_count = 0
    _order_counter = 0


def _error(tool_name: str, message: str) -> str:
    return json.dumps(
        {"status": "ERROR", "tool": tool_name, "error": message},
        sort_keys=True,
    )


_ledger_connection_factory = _default_ledger_connection_factory


def _insert_ledger(order) -> int:
    """Insert one row into ``paper_ledger`` and return its row id."""
    connection = _ledger_connection_factory()
    try:
        connection.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
        cursor = connection.execute(
            """
            INSERT INTO paper_ledger (symbol, side, quantity, price, notional, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                order.symbol,
                order.side,
                str(order.quantity),
                str(order.limit_price),
                str(order.notional),
                datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)
    finally:
        connection.close()


def _handle(tool_name: str, args: Any) -> str:
    global handler_invocation_count, _order_counter

    handler_invocation_count += 1

    adapter = get_adapter(tool_name)
    if adapter is None:  # pragma: no cover - registry invariant
        return _error(tool_name, "No adapter is registered for this tool")

    try:
        if not isinstance(args, Mapping):
            return _error(tool_name, "Arguments must be an object")
        order = adapter.normalize(args)
    except Exception as exc:
        # Handler boundary: never raise, never leak a traceback to the model.
        return _error(tool_name, f"{type(exc).__name__}: {exc}")

    try:
        ledger_row_id = _insert_ledger(order)
    except Exception as exc:
        return _error(tool_name, f"Ledger write failed: {type(exc).__name__}: {exc}")

    _order_counter += 1
    return json.dumps(
        {
            "status": "SUCCESS",
            "order_id": f"mock-{_order_counter:04d}",
            "ledger_row_id": ledger_row_id,
            "message": (
                f"Simulated {order.side} of {order.quantity} "
                f"{order.symbol} shares executed."
            ),
            "order": order.to_dict(),
        },
        sort_keys=True,
    )


def place_order_a(args: Mapping[str, Any], **kwargs: Any) -> str:
    """Handle ``paper_place_order_a``. Always returns a JSON string."""
    return _handle("paper_place_order_a", args)


def place_order_b(args: Mapping[str, Any], **kwargs: Any) -> str:
    """Handle ``paper_place_order_b``. Always returns a JSON string."""
    return _handle("paper_place_order_b", args)