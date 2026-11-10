"""Read-only administrative tools: ``trade_check``, ``trade_policy_get``,
``trade_audit``.

None of these tools can mutate policy or execute an order. ``trade_check`` is a
dry run and deliberately does not write an audit row.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ..domain.order import NormalizedOrder
from ..services.audit import default_audit_store
from ..services.engine import PolicyEngine, load_policy

__all__ = [
    "TRADE_AUDIT",
    "TRADE_CHECK",
    "TRADE_POLICY_GET",
    "trade_audit",
    "trade_check",
    "trade_policy_get",
]

TRADE_CHECK: dict[str, Any] = {
    "name": "trade_check",
    "description": (
        "Dry-run an equity order against the operator policy without executing "
        "it. Returns the canonical normalized order, the allow/block decision, "
        "the violated rule, and the policy hash. Use this to preview an order. "
        "A preview never authorizes execution: the pre_tool_call gate evaluates "
        "the real call independently."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "Equity ticker, e.g. \"AAPL\"."},
            "side": {
                "type": "string",
                "enum": ["buy", "sell"],
                "description": "Order side.",
            },
            "quantity": {
                "type": "string",
                "description": "Whole-share quantity as a decimal string, e.g. \"20\".",
            },
            "order_type": {
                "type": "string",
                "enum": ["limit"],
                "description": "Order type. The MVP supports limit orders only.",
            },
            "limit_price": {
                "type": "string",
                "description": "Limit price as a decimal string, e.g. \"150.00\".",
            },
        },
        "required": ["symbol", "side", "quantity", "order_type", "limit_price"],
        "additionalProperties": False,
    },
}

TRADE_POLICY_GET: dict[str, Any] = {
    "name": "trade_policy_get",
    "description": (
        "Return the active operator policy and its SHA-256. Read-only. The "
        "policy is owned by the operator; this tool cannot change it."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}

TRADE_AUDIT: dict[str, Any] = {
    "name": "trade_audit",
    "description": (
        "Return recent TradePreflight audit entries, newest first, including "
        "blocked, allowed, succeeded, failed, and outcome-unknown decisions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 500,
                "default": 50,
                "description": "Maximum number of entries to return.",
            }
        },
        "additionalProperties": False,
    },
}


def _error(message: str) -> str:
    return json.dumps({"status": "ERROR", "error": message}, sort_keys=True)


def trade_check(args: Mapping[str, Any], **kwargs: Any) -> str:
    """Normalize and evaluate an order without executing or auditing it."""
    if not isinstance(args, Mapping):
        return _error("Arguments must be an object")

    try:
        order = NormalizedOrder.create(
            symbol=args.get("symbol"),
            side=args.get("side"),
            quantity=args.get("quantity"),
            order_type=args.get("order_type"),
            limit_price=args.get("limit_price"),
        )
        policy = load_policy()
        decision = PolicyEngine(policy).evaluate(order)
        return json.dumps(
            {
                "status": "OK",
                "mode": "dry_run",
                **decision.to_dict(),
                "order": order.to_dict(),
            },
            sort_keys=True,
        )
    except Exception as exc:
        # Invalid input is a block for dry-run purposes.
        return json.dumps(
            {
                "status": "ERROR",
                "mode": "dry_run",
                "allowed": False,
                "decision": "BLOCK",
                "error": f"{type(exc).__name__}: {exc}",
            },
            sort_keys=True,
        )


def trade_policy_get(args: Any = None, **kwargs: Any) -> str:
    """Return the validated policy and its canonical hash."""
    try:
        policy = load_policy()
        return json.dumps(
            {
                "status": "OK",
                "policy": policy.to_dict(),
                "sha256": policy.sha256(),
            },
            sort_keys=True,
        )
    except Exception as exc:
        return _error(f"{type(exc).__name__}: {exc}")


def trade_audit(args: Any = None, **kwargs: Any) -> str:
    """Return recent audit rows."""
    if args is None:
        args = {}
    if not isinstance(args, Mapping):
        return _error("Arguments must be an object")

    limit = args.get("limit", 50)
    if isinstance(limit, bool) or not isinstance(limit, int):
        return _error("limit must be an integer between 1 and 500")
    if not 1 <= limit <= 500:
        return _error("limit must be between 1 and 500")

    try:
        rows = default_audit_store().recent(limit)
        return json.dumps(
            {"status": "OK", "count": len(rows), "entries": rows},
            sort_keys=True,
        )
    except Exception as exc:
        return _error(f"{type(exc).__name__}: {exc}")
