"""Canonical, broker-agnostic order value objects.

This module is pure domain code. It performs no I/O, imports no Hermes modules,
and never touches a float. Every monetary or quantity value is a
``decimal.Decimal`` parsed from a string.

Design rules
------------
- Reject ``bool`` before any numeric handling (``True == 1`` in Python).
- Reject ``float`` outright; JSON decimal values must arrive as strings.
- Reject ``NaN`` / ``Infinity`` / ``-Infinity``.
- Reject zero, negative, and (for the MVP) fractional quantities.
- Derive notional; never accept it from a model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Final

__all__ = [
    "NormalizedOrder",
    "OrderValidationError",
    "calculate_notional",
    "parse_decimal",
]

ASSET_CLASS: Final[str] = "equity"
SIDES: Final[frozenset[str]] = frozenset({"buy", "sell"})
ORDER_TYPES: Final[frozenset[str]] = frozenset({"limit"})
_CENT: Final[Decimal] = Decimal("0.01")
_SYMBOL_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


class OrderValidationError(ValueError):
    """Raised when raw order input cannot be normalized without ambiguity."""


def parse_decimal(value: Any, field_name: str) -> Decimal:
    """Parse a decimal from a string, integer, or ``Decimal``.

    Floats are rejected rather than stringified: accepting binary floats at the
    boundary makes the exact value dependent on the JSON encoder/parser and
    defeats the purpose of the Decimal gate.
    """
    if isinstance(value, bool):
        raise OrderValidationError(
            f"{field_name}: booleans are not valid numeric values"
        )

    if isinstance(value, float):
        raise OrderValidationError(
            f"{field_name}: floats are not permitted; send a decimal string"
        )

    if isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, int):
        parsed = Decimal(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise OrderValidationError(f"{field_name}: value is empty")
        try:
            parsed = Decimal(text)
        except (InvalidOperation, ValueError) as exc:
            raise OrderValidationError(
                f"{field_name}: {text!r} is not a valid decimal"
            ) from exc
    else:
        raise OrderValidationError(
            f"{field_name}: expected a decimal string or integer, "
            f"got {type(value).__name__}"
        )

    if not parsed.is_finite():
        raise OrderValidationError(
            f"{field_name}: NaN and Infinity are not permitted"
        )

    return parsed


def calculate_notional(quantity: Decimal, limit_price: Decimal) -> Decimal:
    """Return ``quantity * limit_price`` rounded half-up to cents.

    The inputs must already be validated ``Decimal`` values. The result is
    quantized so audit rows and policy comparisons use one canonical scale.
    """
    if not isinstance(quantity, Decimal) or not isinstance(limit_price, Decimal):
        raise OrderValidationError("quantity and limit_price must be Decimal")
    if not quantity.is_finite() or not limit_price.is_finite():
        raise OrderValidationError("quantity and limit_price must be finite")
    if quantity <= 0 or limit_price <= 0:
        raise OrderValidationError("quantity and limit_price must be positive")

    return (quantity * limit_price).quantize(_CENT, rounding=ROUND_HALF_UP)


def _label(value: Any, field_name: str, *, uppercase: bool) -> str:
    if not isinstance(value, str):
        raise OrderValidationError(f"{field_name}: expected a string")
    text = value.strip()
    if not text:
        raise OrderValidationError(f"{field_name}: value is empty")
    return text.upper() if uppercase else text.lower()


@dataclass(frozen=True, slots=True)
class NormalizedOrder:
    """The only order shape the policy engine is allowed to see."""

    asset_class: str
    symbol: str
    side: str
    quantity: Decimal
    order_type: str
    limit_price: Decimal
    notional: Decimal = field(init=False)

    def __post_init__(self) -> None:
        asset_class = _label(self.asset_class, "asset_class", uppercase=False)
        symbol = _label(self.symbol, "symbol", uppercase=True)
        side = _label(self.side, "side", uppercase=False)
        order_type = _label(self.order_type, "order_type", uppercase=False)

        if asset_class != ASSET_CLASS:
            raise OrderValidationError(
                f"asset_class: only {ASSET_CLASS!r} is supported"
            )
        if not _SYMBOL_RE.fullmatch(symbol):
            raise OrderValidationError(f"symbol: {symbol!r} is not a valid ticker")
        if side not in SIDES:
            raise OrderValidationError(f"side: {side!r} is not supported")
        if order_type not in ORDER_TYPES:
            raise OrderValidationError(
                f"order_type: {order_type!r} is not supported in the MVP"
            )

        if not isinstance(self.quantity, Decimal):
            raise OrderValidationError("quantity must be a Decimal")
        if not isinstance(self.limit_price, Decimal):
            raise OrderValidationError("limit_price must be a Decimal")
        if not self.quantity.is_finite() or not self.limit_price.is_finite():
            raise OrderValidationError("quantity and limit_price must be finite")
        if self.quantity <= 0 or self.limit_price <= 0:
            raise OrderValidationError("quantity and limit_price must be positive")
        if self.quantity != self.quantity.to_integral_value():
            raise OrderValidationError("fractional shares are not supported")

        object.__setattr__(self, "asset_class", asset_class)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "side", side)
        object.__setattr__(self, "order_type", order_type)
        object.__setattr__(
            self,
            "notional",
            calculate_notional(self.quantity, self.limit_price),
        )

    @classmethod
    def create(
        cls,
        *,
        symbol: Any,
        side: Any,
        quantity: Any,
        order_type: Any,
        limit_price: Any,
    ) -> "NormalizedOrder":
        """Build an order from untrusted, broker-shaped raw values."""
        return cls(
            asset_class=ASSET_CLASS,
            symbol=_label(symbol, "symbol", uppercase=True),
            side=_label(side, "side", uppercase=False),
            quantity=parse_decimal(quantity, "quantity"),
            order_type=_label(order_type, "order_type", uppercase=False),
            limit_price=parse_decimal(limit_price, "limit_price"),
        )

    def to_dict(self) -> dict[str, str]:
        """Canonical JSON-safe representation (all numbers are strings)."""
        return {
            "asset_class": self.asset_class,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": format(self.quantity.to_integral_value(), "f"),
            "order_type": self.order_type,
            "limit_price": format(self.limit_price, "f"),
            "notional": format(self.notional, "f"),
        }

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"{self.side} {self.quantity} {self.symbol} "
            f"@ {self.limit_price} ({self.order_type})"
        )
