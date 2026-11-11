"""Hermes entry point for the TradePreflight plugin.

Hermes loads a native directory plugin by importing this module and calling
``register(ctx)``. The implementation lives in ``src/trade_preflight`` and is
imported with *relative* imports so every module is loaded underneath the
``hermes_plugins.<slug>`` namespace that Hermes owns.

Why relative imports matter: Hermes evicts plugin modules from ``sys.modules``
by that namespace prefix before (re)loading a plugin. A top-level
``trade_preflight`` package would survive the eviction, so an updated plugin
would keep running the previous version's code, and a second Hermes profile
would silently reuse the first profile's modules. Relative imports keep the
whole implementation inside ``hermes_plugins.trade_preflight.*`` where the
eviction applies.

Registration failures are intentionally *not* swallowed: a security plugin that
cannot register must fail loudly rather than load in a half-wired state.
"""

from __future__ import annotations

from typing import Any


def register(ctx: Any) -> None:
    """Register TradePreflight tools and hooks with Hermes."""
    from .src.trade_preflight.hooks import execution_gate
    from .src.trade_preflight.tools import admin, paper_trades

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
