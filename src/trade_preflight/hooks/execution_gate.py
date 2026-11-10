"""Fail-closed Hermes lifecycle hooks.

Slice 0 implementation: a hardcoded 100-share quantity gate proves that
``pre_tool_call`` fires before the handler and can block it. The full policy
engine replaces this gate in Slice 2.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from ..adapters import GUARDED_TOOLS, get_adapter
from ..domain.order import NormalizedOrder
from ..services.audit import (
    EXECUTION_ALLOWED,
    EXECUTION_BLOCKED,
    EXECUTION_FAILED,
    EXECUTION_OUTCOME_UNKNOWN,
    EXECUTION_SUCCEEDED,
    default_audit_store,
)
from ..services.engine import Decision

__all__ = ["SLICE_0_QUANTITY_LIMIT", "post_tool_call", "pre_tool_call"]

logger = logging.getLogger(__name__)

#: Slice 0 policy: no single order may exceed 100 shares. Replaced by
#: ``max_quantity`` from the operator policy in Slice 2.
SLICE_0_QUANTITY_LIMIT: Decimal = Decimal("100")

_FAIL_CLOSED_MESSAGE = (
    "TradePreflight blocked this order because policy evaluation failed. "
    "No order was executed."
)


def _audit_id(tool_call_id: str) -> str:
    return tool_call_id or f"uncorrelated-{uuid.uuid4().hex}"


def _json_value(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    except Exception:  # pragma: no cover - defensive
        return "{}"


def _block_directive(tool_name: str, reason: str) -> dict[str, str]:
    return {"action": "block", "message": f"TradePreflight blocked {tool_name}: {reason}"}


def _record_decision(
    *,
    tool_call_id: str,
    tool_name: str,
    order: NormalizedOrder,
    decision: Decision,
) -> None:
    default_audit_store().record_decision(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        order_json=_json_value(order.to_dict()),
        decision=decision.allowed and "EXECUTION_ALLOWED" or "EXECUTION_BLOCKED",
        reason=decision.reason,
        policy_hash=decision.policy_hash,
    )


def _record_failure(
    *,
    tool_call_id: str,
    tool_name: str,
    args: Any,
    policy_hash: str,
    exc: BaseException,
) -> None:
    reason = f"FAIL_CLOSED: {type(exc).__name__}: {str(exc)[:500]}"
    default_audit_store().record_decision(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        order_json=_json_value(args),
        decision=EXECUTION_BLOCKED,
        reason=reason,
        policy_hash=policy_hash,
    )


def pre_tool_call(
    tool_name: str = "",
    args: Any = None,
    task_id: str = "",
    session_id: str = "",
    tool_call_id: str = "",
    **kwargs: Any,
) -> dict[str, str] | None:
    """Intercept a guarded trade call before its handler runs."""
    adapter = get_adapter(tool_name)
    if adapter is None:
        # Not a TradePreflight execution tool. This plugin does not police it.
        return None

    audit_id = _audit_id(tool_call_id)

    try:
        raw_args = args if isinstance(args, Mapping) else {}
        order = adapter.normalize(raw_args)

        # --- Slice 0 hardcoded gate (replaced by the policy engine in Slice 2) ---
        if order.quantity > SLICE_0_QUANTITY_LIMIT:
            reason = (
                f"quantity {order.quantity} exceeds the "
                f"{SLICE_0_QUANTITY_LIMIT}-share limit"
            )
            _record_decision(
                tool_call_id=audit_id,
                tool_name=tool_name,
                order=order,
                decision=Decision(
                    allowed=False,
                    rule="max_quantity",
                    reason=reason,
                    policy_hash="",
                ),
            )
            return _block_directive(tool_name, reason)

        _record_decision(
            tool_call_id=audit_id,
            tool_name=tool_name,
            order=order,
            decision=Decision(
                allowed=True,
                rule="max_quantity",
                reason="Slice 0 quantity check passed",
                policy_hash="",
            ),
        )
        return None
    except Exception as exc:
        logger.exception("TradePreflight failed closed for tool %s", tool_name)
        try:
            _record_failure(
                tool_call_id=audit_id,
                tool_name=tool_name,
                args=args,
                policy_hash="",
                exc=exc,
            )
        except Exception:
            logger.exception("TradePreflight could not write the failure audit row")
        return {"action": "block", "message": _FAIL_CLOSED_MESSAGE}


def _classify_result(result: Any, status: str) -> tuple[str, str]:
    """Map a handler result to an audit outcome without trusting it blindly."""
    parsed: Any = result
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return EXECUTION_OUTCOME_UNKNOWN, "Unrecognized tool result"

    if isinstance(parsed, dict):
        payload_status = str(parsed.get("status", "")).upper()
        if payload_status == "SUCCESS" or parsed.get("ok") is True:
            return EXECUTION_SUCCEEDED, "Handler returned a success payload"
        if payload_status in {"ERROR", "FAILED", "BLOCKED"} or "error" in parsed:
            return EXECUTION_FAILED, f"Handler returned {payload_status or 'ERROR'}"

    if str(status).lower() in {"error", "failed"}:
        return EXECUTION_FAILED, "Hermes reported a handler error"

    return EXECUTION_OUTCOME_UNKNOWN, "Unrecognized tool result"


def post_tool_call(
    tool_name: str = "",
    args: Any = None,
    result: Any = None,
    task_id: str = "",
    session_id: str = "",
    tool_call_id: str = "",
    duration_ms: int = 0,
    status: str = "",
    error_type: str | None = None,
    error_message: str | None = None,
    **kwargs: Any,
) -> None:
    """Correlate a guarded handler's outcome with its pre-execution decision."""
    if tool_name not in GUARDED_TOOLS or not tool_call_id:
        return None

    if str(status).lower() in {"blocked", "denied"}:
        # pre_tool_call already recorded EXECUTION_BLOCKED.
        return None

    try:
        decision, reason = _classify_result(result, status)
        default_audit_store().record_outcome(
            tool_call_id=tool_call_id,
            decision=decision,
            reason=reason,
        )
    except Exception:
        # This is an observer; never break the agent loop. The pre-execution
        # row remains EXECUTION_ALLOWED, which is itself a visible anomaly.
        logger.exception("TradePreflight could not record the tool outcome")

    return None