"""Policy schema, validation, and canonical hashing.

A policy is operator-owned configuration. It is never accepted from the model
and there is no tool that can mutate it.

Validation is intentionally strict: unknown keys, empty allowlists, wrong types,
and non-finite or over-precise amounts are configuration errors. The hook treats
a configuration error as a block.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Final, Mapping

from .order import OrderValidationError, parse_decimal

__all__ = ["Policy", "PolicyError", "REQUIRED_KEYS"]

REQUIRED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "max_gross_buy_notional_usd",
        "max_quantity",
        "symbol_allowlist",
        "order_type_allowlist",
        "side_allowlist",
    }
)
_OPTIONAL_KEYS: Final[frozenset[str]] = frozenset({"version"})
_CENT: Final[Decimal] = Decimal("0.01")


class PolicyError(ValueError):
    """Raised when a policy document is missing, malformed, or unsafe."""


def _require_mapping(raw: Any) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise PolicyError("policy must be a JSON object")
    return raw


def _parse_max_notional(raw: Any) -> Decimal:
    try:
        value = parse_decimal(raw, "max_gross_buy_notional_usd")
    except OrderValidationError as exc:
        raise PolicyError(str(exc)) from exc
    if value <= 0:
        raise PolicyError("max_gross_buy_notional_usd must be positive")
    try:
        quantized = value.quantize(_CENT)
    except InvalidOperation as exc:  # extremely large exponents
        raise PolicyError("max_gross_buy_notional_usd is out of range") from exc
    if quantized != value:
        raise PolicyError(
            "max_gross_buy_notional_usd must have at most two decimal places"
        )
    return quantized


def _parse_positive_int(raw: Any, field_name: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise PolicyError(f"{field_name} must be an integer")
    if raw <= 0:
        raise PolicyError(f"{field_name} must be positive")
    return raw


def _parse_allowlist(
    raw: Any,
    field_name: str,
    *,
    uppercase: bool,
) -> frozenset[str]:
    if isinstance(raw, (str, bytes)) or not isinstance(raw, (list, tuple, set, frozenset)):
        raise PolicyError(f"{field_name} must be a non-empty array of strings")
    if not raw:
        raise PolicyError(f"{field_name} must not be empty")

    normalized: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            raise PolicyError(f"{field_name} entries must be strings")
        value = item.strip()
        if not value:
            raise PolicyError(f"{field_name} must not contain empty values")
        normalized.add(value.upper() if uppercase else value.lower())

    return frozenset(normalized)


@dataclass(frozen=True, slots=True)
class Policy:
    """Validated, immutable policy document."""

    max_gross_buy_notional_usd: Decimal
    max_quantity: int
    symbol_allowlist: frozenset[str]
    order_type_allowlist: frozenset[str]
    side_allowlist: frozenset[str]
    version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.max_gross_buy_notional_usd, Decimal):
            raise PolicyError("max_gross_buy_notional_usd must be a Decimal")
        if not self.max_gross_buy_notional_usd.is_finite():
            raise PolicyError("max_gross_buy_notional_usd must be finite")
        if self.max_gross_buy_notional_usd <= 0:
            raise PolicyError("max_gross_buy_notional_usd must be positive")
        if self.max_gross_buy_notional_usd != self.max_gross_buy_notional_usd.quantize(_CENT):
            raise PolicyError(
                "max_gross_buy_notional_usd must have at most two decimal places"
            )
        object.__setattr__(
            self,
            "max_gross_buy_notional_usd",
            self.max_gross_buy_notional_usd.quantize(_CENT),
        )

        if isinstance(self.max_quantity, bool) or not isinstance(self.max_quantity, int):
            raise PolicyError("max_quantity must be an integer")
        if self.max_quantity <= 0:
            raise PolicyError("max_quantity must be positive")

        for name, value in (
            ("symbol_allowlist", self.symbol_allowlist),
            ("order_type_allowlist", self.order_type_allowlist),
            ("side_allowlist", self.side_allowlist),
        ):
            if not isinstance(value, frozenset) or not value:
                raise PolicyError(f"{name} must be a non-empty frozenset")
            if any(not isinstance(item, str) or not item for item in value):
                raise PolicyError(f"{name} entries must be non-empty strings")

        if any(symbol != symbol.upper() for symbol in self.symbol_allowlist):
            raise PolicyError("symbol_allowlist entries must be uppercase")
        if any(side != side.lower() for side in self.side_allowlist):
            raise PolicyError("side_allowlist entries must be lowercase")
        if any(kind != kind.lower() for kind in self.order_type_allowlist):
            raise PolicyError("order_type_allowlist entries must be lowercase")

        if isinstance(self.version, bool) or not isinstance(self.version, int):
            raise PolicyError("version must be an integer")
        if self.version < 1:
            raise PolicyError("version must be >= 1")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "Policy":
        """Validate a decoded JSON policy document."""
        data = _require_mapping(raw)

        missing = REQUIRED_KEYS - set(data)
        unknown = set(data) - REQUIRED_KEYS - _OPTIONAL_KEYS
        if missing:
            raise PolicyError(
                "policy is missing required keys: " + ", ".join(sorted(missing))
            )
        if unknown:
            raise PolicyError(
                "policy contains unknown keys: " + ", ".join(sorted(unknown))
            )

        return cls(
            max_gross_buy_notional_usd=_parse_max_notional(
                data["max_gross_buy_notional_usd"]
            ),
            max_quantity=_parse_positive_int(data["max_quantity"], "max_quantity"),
            symbol_allowlist=_parse_allowlist(
                data["symbol_allowlist"], "symbol_allowlist", uppercase=True
            ),
            order_type_allowlist=_parse_allowlist(
                data["order_type_allowlist"], "order_type_allowlist", uppercase=False
            ),
            side_allowlist=_parse_allowlist(
                data["side_allowlist"], "side_allowlist", uppercase=False
            ),
            version=_parse_positive_int(data.get("version", 1), "version"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Canonical, JSON-safe representation. Lists are sorted."""
        return {
            "max_gross_buy_notional_usd": format(
                self.max_gross_buy_notional_usd, "f"
            ),
            "max_quantity": self.max_quantity,
            "symbol_allowlist": sorted(self.symbol_allowlist),
            "order_type_allowlist": sorted(self.order_type_allowlist),
            "side_allowlist": sorted(self.side_allowlist),
            "version": self.version,
        }

    def canonical_json(self) -> str:
        """Deterministic JSON used for hashing and audit correlation."""
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )

    def sha256(self) -> str:
        """SHA-256 of the canonical policy document."""
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()
