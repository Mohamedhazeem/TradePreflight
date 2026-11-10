"""Paper-trading tool schemas and handlers (Broker A and Broker B).

Slice 0 implementation: each handler validates its arguments through the adapter,
increments ``handler_invocation_count``, and returns a simulated success payload.
No database write happens yet; that is Slice 3.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
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

PAPER_PLACE_ORDER_A: dict[str, Any] = {
    "name": "paper_place_order_a",
    "description": (
        "Simulated Broker A equity order. This is a paper trade: no real broker "
        "or network call is made. Before execution, TradePreflight normalizes "
        "the order and blocks it unless it satisfies the Slice 0 quantity gate. "
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
        "same gate applies. Limit orders only; whole shares only."
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

    _order_counter += 1
    return json.dumps(
        {
            "status": "SUCCESS",
            "order_id": f"mock-{_order_counter:04d}",
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