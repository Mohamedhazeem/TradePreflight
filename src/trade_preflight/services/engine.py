"""Policy loading and deterministic order evaluation.

The engine is a pure decision function: it receives a ``NormalizedOrder`` and a
validated ``Policy`` and returns a ``Decision``. It performs no I/O.

Policy loading is separated from evaluation so the operator file can be re-read
on every guarded call without giving the engine a filesystem dependency.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from ..domain.order import NormalizedOrder
from ..domain.policy import Policy, PolicyError

__all__ = [
    "Decision",
    "PolicyEngine",
    "default_policy_path",
    "load_policy",
    "policy_path",
]

PLUGIN_NAME: Final[str] = "trade-preflight"
POLICY_FILENAME: Final[str] = "policy.json"
_MAX_POLICY_BYTES: Final[int] = 1_000_000


@dataclass(frozen=True, slots=True)
class Decision:
    """The result of evaluating one order against one policy."""

    allowed: bool
    rule: str
    reason: str
    policy_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "decision": "ALLOW" if self.allowed else "BLOCK",
            "rule": self.rule,
            "reason": self.reason,
            "policy_hash": self.policy_hash,
        }


def policy_path() -> Path:
    """Return the operator-owned policy path under the plugin data directory."""
    try:
        from plugins.plugin_storage import plugin_data_dir
    except ImportError as exc:  # outside a Hermes runtime
        raise PolicyError("Hermes plugin storage is unavailable") from exc

    return plugin_data_dir(PLUGIN_NAME) / POLICY_FILENAME


def default_policy_path() -> Path:
    """Path to the policy shipped with this plugin (used only to seed)."""
    return Path(__file__).resolve().parents[3] / "policies" / "default.json"


def _seed_default_policy(target: Path) -> None:
    source = default_policy_path()
    if not source.is_file():
        raise PolicyError(
            f"no policy at {target} and no shipped default at {source}"
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    try:
        target.chmod(0o600)
    except OSError:  # best effort on platforms without POSIX modes
        pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PolicyError(f"policy contains duplicate key {key!r}")
        result[key] = value
    return result


def load_policy(path: Path | None = None) -> Policy:
    """Load and validate the operator policy.

    The policy is re-read on every call so operator edits take effect without a
    restart. Any error is a configuration error and therefore fails closed at the
    hook boundary.
    """
    target = Path(path) if path is not None else policy_path()

    if not target.exists():
        _seed_default_policy(target)

    try:
        size = target.stat().st_size
        if size > _MAX_POLICY_BYTES:
            raise PolicyError("policy file is too large")
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise PolicyError(f"unable to read policy file: {exc}") from exc

    try:
        raw = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise PolicyError(f"policy is not valid JSON: {exc}") from exc
    except RecursionError as exc:
        raise PolicyError("policy JSON is nested too deeply") from exc

    if not isinstance(raw, Mapping):
        raise PolicyError("policy must be a JSON object")

    return Policy.from_mapping(raw)


class PolicyEngine:
    """Deterministic, side-effect-free policy evaluator."""

    def __init__(self, policy: Policy) -> None:
        if not isinstance(policy, Policy):
            raise TypeError("PolicyEngine requires a validated Policy")
        self._policy = policy

    @property
    def policy(self) -> Policy:
        return self._policy

    def evaluate(self, order: NormalizedOrder) -> Decision:
        """Evaluate one canonical order against the operator policy.

        Rules are applied in ``RULE_ORDER``. The first violation wins and is
        reported with both the observed value and the configured limit.
        """
        if not isinstance(order, NormalizedOrder):
            raise TypeError("PolicyEngine.evaluate requires a NormalizedOrder")

        policy = self._policy
        policy_hash = policy.sha256()

        if order.side not in policy.side_allowlist:
            return Decision(
                allowed=False,
                rule="side_allowlist",
                reason=(
                    f"side {order.side!r} is not allowed "
                    f"(allowed: {sorted(policy.side_allowlist)})"
                ),
                policy_hash=policy_hash,
            )

        if order.symbol not in policy.symbol_allowlist:
            return Decision(
                allowed=False,
                rule="symbol_allowlist",
                reason=(
                    f"symbol {order.symbol!r} is not allowed "
                    f"(allowed: {sorted(policy.symbol_allowlist)})"
                ),
                policy_hash=policy_hash,
            )

        if order.order_type not in policy.order_type_allowlist:
            return Decision(
                allowed=False,
                rule="order_type_allowlist",
                reason=(
                    f"order_type {order.order_type!r} is not allowed "
                    f"(allowed: {sorted(policy.order_type_allowlist)})"
                ),
                policy_hash=policy_hash,
            )

        if order.quantity > policy.max_quantity:
            return Decision(
                allowed=False,
                rule="max_quantity",
                reason=(
                    f"quantity {order.quantity} exceeds maximum "
                    f"{policy.max_quantity}"
                ),
                policy_hash=policy_hash,
            )

        if (
            order.side == "buy"
            and order.notional > policy.max_gross_buy_notional_usd
        ):
            return Decision(
                allowed=False,
                rule="max_gross_buy_notional_usd",
                reason=(
                    f"gross buy notional {order.notional} exceeds maximum "
                    f"{policy.max_gross_buy_notional_usd}"
                ),
                policy_hash=policy_hash,
            )

        return Decision(
            allowed=True,
            rule="policy",
            reason="Order complies with policy",
            policy_hash=policy_hash,
        )