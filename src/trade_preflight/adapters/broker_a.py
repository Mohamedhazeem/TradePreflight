"""Simulated Broker A adapter.

Broker A schema::

    paper_place_order_a(symbol, side, quantity, order_type, limit_price)
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from ..domain.order import NormalizedOrder
from .base import BrokerAdapter

__all__ = ["BrokerAAdapter"]


class BrokerAAdapter(BrokerAdapter):
    tool_name: ClassVar[str] = "paper_place_order_a"
    field_map: ClassVar[Mapping[str, str]] = {
        "symbol": "symbol",
        "side": "side",
        "quantity": "quantity",
        "order_type": "order_type",
        "limit_price": "limit_price",
    }

    def normalize(self, args: Mapping[str, object]) -> NormalizedOrder:
        return self._normalize(args)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "BrokerAAdapter()"
