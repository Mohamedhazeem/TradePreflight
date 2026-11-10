"""Hermes entry point for the TradePreflight plugin.

Hermes loads a native directory plugin by importing this module and calling
``register(ctx)``. The implementation lives in ``src/trade_preflight``; this
shim puts the bundled ``src`` directory on ``sys.path`` so the package resolves
for both directory installs and editable installs.

Registration failures are intentionally *not* swallowed: a security plugin that
cannot register must fail loudly rather than load in a half-wired state.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_PLUGIN_ROOT = Path(__file__).resolve().parent
_SRC = _PLUGIN_ROOT / "src"

if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def register(ctx: Any) -> None:
    """Register TradePreflight tools and hooks with Hermes."""
    from trade_preflight.hooks import execution_gate
    from trade_preflight.tools import admin, paper_trades

    ctx.register_tool(
        name="paper_place_order_a",
        toolset="trade-preflight",
        schema=paper_trades.PAPER_PLACE_ORDER_A,
        handler=paper_trades.place_order_a,
    )
    ctx.register_tool(
        name="paper_place_order_b",
        toolset="trade-preflight",
        schema=paper_trades.PAPER_PLACE_ORDER_B,
        handler=paper_trades.place_order_b,
    )
    ctx.register_tool(
        name="trade_check",
        toolset="trade-preflight",
        schema=admin.TRADE_CHECK,
        handler=admin.trade_check,
    )
    ctx.register_tool(
        name="trade_policy_get",
        toolset="trade-preflight",
        schema=admin.TRADE_POLICY_GET,
        handler=admin.trade_policy_get,
    )
    ctx.register_tool(
        name="trade_audit",
        toolset="trade-preflight",
        schema=admin.TRADE_AUDIT,
        handler=admin.trade_audit,
    )

    ctx.register_hook("pre_tool_call", execution_gate.pre_tool_call)
    ctx.register_hook("post_tool_call", execution_gate.post_tool_call)


__all__ = ["register"]
