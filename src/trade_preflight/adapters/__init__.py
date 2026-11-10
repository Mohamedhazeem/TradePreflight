"""Broker adapters: the only place broker-specific schemas are understood."""

from __future__ import annotations

from .base import AdapterError, BrokerAdapter
from .broker_a import BrokerAAdapter
from .broker_b import BrokerBAdapter

_ADAPTERS: dict[str, BrokerAdapter] = {
    adapter.tool_name: adapter for adapter in (BrokerAAdapter(), BrokerBAdapter())
}

#: Tool names the execution gate is responsible for. Exact-match only.
GUARDED_TOOLS: frozenset[str] = frozenset(_ADAPTERS)


def get_adapter(tool_name: str) -> BrokerAdapter | None:
    """Return the adapter for a guarded tool, or ``None`` for any other tool."""
    return _ADAPTERS.get(tool_name)


__all__ = [
    "AdapterError",
    "BrokerAdapter",
    "BrokerAAdapter",
    "BrokerBAdapter",
    "GUARDED_TOOLS",
    "get_adapter",
]
