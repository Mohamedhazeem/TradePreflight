"""Unit tests for the policy schema, validation, and hashing."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from trade_preflight.domain.policy import Policy, PolicyError
from trade_preflight.services.engine import load_policy


def _valid_policy() -> dict:
    return {
        "max_gross_buy_notional_usd": "10000.00",
        "max_quantity": 200,
        "symbol_allowlist": ["AAPL", "MSFT"],
        "order_type_allowlist": ["limit"],
        "side_allowlist": ["buy"],
    }


def test_policy_from_mapping_validates_and_normalizes():
    policy = Policy.from_mapping(_valid_policy())
    assert policy.max_gross_buy_notional_usd == Decimal("10000.00")
    assert policy.max_quantity == 200
    assert policy.symbol_allowlist == frozenset({"AAPL", "MSFT"})
    assert policy.version == 1


def test_policy_rejects_missing_and_unknown_keys():
    for key in ("max_quantity", "symbol_allowlist"):
        raw = _valid_policy()
        del raw[key]
        with pytest.raises(PolicyError):
            Policy.from_mapping(raw)

    raw = _valid_policy()
    raw["extra"] = "x"
    with pytest.raises(PolicyError):
        Policy.from_mapping(raw)


def test_policy_rejects_empty_allowlists_and_wrong_types():
    for field in ("symbol_allowlist", "order_type_allowlist", "side_allowlist"):
        raw = _valid_policy()
        raw[field] = []
        with pytest.raises(PolicyError):
            Policy.from_mapping(raw)

    raw = _valid_policy()
    raw["max_quantity"] = True
    with pytest.raises(PolicyError):
        Policy.from_mapping(raw)

    raw = _valid_policy()
    raw["max_gross_buy_notional_usd"] = "NaN"
    with pytest.raises(PolicyError):
        Policy.from_mapping(raw)

    raw = _valid_policy()
    raw["max_gross_buy_notional_usd"] = "10000.001"
    with pytest.raises(PolicyError):
        Policy.from_mapping(raw)


def test_policy_hash_is_deterministic_and_sensitive_to_values():
    a = Policy.from_mapping(_valid_policy())
    b = Policy.from_mapping(_valid_policy())
    assert a.sha256() == b.sha256()

    changed = _valid_policy()
    changed["max_quantity"] = 100
    c = Policy.from_mapping(changed)
    assert c.sha256() != a.sha256()


def test_load_policy_rejects_duplicate_keys_and_invalid_json(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text('{"max_quantity": 1, "max_quantity": 2, "max_gross_buy_notional_usd": "1.00", "symbol_allowlist": ["AAPL"], "order_type_allowlist": ["limit"], "side_allowlist": ["buy"]}')
    with pytest.raises(PolicyError):
        load_policy(path)

    path.write_text("{not json")
    with pytest.raises(PolicyError):
        load_policy(path)

    path.write_text(json.dumps(_valid_policy()))
    policy = load_policy(path)
    assert policy.max_quantity == 200