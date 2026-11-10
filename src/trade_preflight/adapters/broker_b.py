"""Simulated Broker B adapter.

Broker B schema::

    paper_place_order_b(ticker, direction, qty, order_type, price)

This schema is deliberately different from Broker A's. It proves that the policy
engine receives a canonical order rather than a broker payload.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from ..domain.order import NormalizedOrder
from .base import BrokerAdapter

__all__ = ["BrokerBAdapter"]


class BrokerBAdapter(BrokerAdapter):
    tool_name: ClassVar[str] = "paper_place_order_b"
    field_map: ClassVar[Mapping[str, str]] = {
        "symbol": "ticker",
        "side": "direction",
        "quantity": "qty",
        "order_type": "order_type",
        "limit_price": "price",
    }

    def normalize(self, args: Mapping[str, object]) -> NormalizedOrder:
        return self._normalize(args)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "BrokerBAdapter()"
