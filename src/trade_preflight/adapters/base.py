"""Abstract broker adapter and shared translation mechanics.

An adapter's only job is to turn a broker-shaped argument mapping into a
``NormalizedOrder``. It must not evaluate policy, write to the database, or call
the network.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any, ClassVar

from ..domain.order import NormalizedOrder, OrderValidationError

__all__ = ["AdapterError", "BrokerAdapter"]


class AdapterError(ValueError):
    """Raised when broker arguments cannot be translated safely."""


class BrokerAdapter(ABC):
    """Contract every broker adapter must satisfy."""

    #: Exact Hermes tool name this adapter handles.
    tool_name: ClassVar[str]

    #: canonical field -> broker-specific field
    field_map: ClassVar[Mapping[str, str]]

    @abstractmethod
    def normalize(self, args: Mapping[str, Any]) -> NormalizedOrder:
        """Translate raw tool arguments into the canonical order."""

    def _normalize(self, args: Mapping[str, Any]) -> NormalizedOrder:
        """Shared translation used by concrete adapters."""
        if not isinstance(args, Mapping):
            raise AdapterError(f"{self.tool_name}: arguments must be an object")

        try:
            return NormalizedOrder.create(
                symbol=self._require(args, "symbol"),
                side=self._require(args, "side"),
                quantity=self._require(args, "quantity"),
                order_type=self._require(args, "order_type"),
                limit_price=self._require(args, "limit_price"),
            )
        except OrderValidationError as exc:
            raise AdapterError(f"{self.tool_name}: {exc}") from exc

    def _require(self, args: Mapping[str, Any], canonical_field: str) -> Any:
        broker_field = self.field_map[canonical_field]
        if broker_field not in args:
            raise AdapterError(
                f"{self.tool_name}: missing required field {broker_field!r}"
            )
        value = args[broker_field]
        if value is None:
            raise AdapterError(
                f"{self.tool_name}: field {broker_field!r} must not be null"
            )
        return value
