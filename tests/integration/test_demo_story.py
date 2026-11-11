"""The demo story must keep telling the truth.

``demo/story.py`` is what the recorded walkthrough shows. This module runs the
same story through the same code path and asserts the claims the README and
the storyboard make, so the video cannot quietly drift away from the plugin's
real behaviour.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_DIR = REPO_ROOT / "demo"
POLICY_FILE = DEMO_DIR / "policy.json"
BROKEN_POLICY_FILE = DEMO_DIR / "policy_broken.json"


def _load_story() -> ModuleType:
    """Import ``demo/story.py`` by path; ``demo/`` is not a package."""
    spec = importlib.util.spec_from_file_location(
        "tradepreflight_demo_story", DEMO_DIR / "story.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


story = _load_story()


@pytest.fixture(scope="module")
def result() -> dict[str, Any]:
    """Run the whole story once; every assertion reads this run."""
    return story.run_story(policy_file=POLICY_FILE, broken_policy_file=BROKEN_POLICY_FILE)


@pytest.fixture(scope="module")
def policy() -> dict[str, Any]:
    """The operator policy the story enforces, read from disk."""
    return json.loads(POLICY_FILE.read_text(encoding="utf-8"))


def _by_call_id(result: dict[str, Any]) -> dict[str, Any]:
    return {outcome.step.call_id: outcome for outcome in result["outcomes"]}


def test_story_makes_ten_tool_calls(result: dict[str, Any]) -> None:
    assert len(result["outcomes"]) == 10


def test_only_compliant_orders_reach_the_handler(result: dict[str, Any]) -> None:
    outcomes = _by_call_id(result)
    allowed = [call_id for call_id, outcome in outcomes.items() if outcome.allowed]
    assert allowed == ["a1", "a5"]


def test_handler_and_ledger_counts_match_the_storyboard(result: dict[str, Any]) -> None:
    assert result["handler_invocations"] == 2
    assert len(result["ledger_rows"]) == 2


def test_act_one_allows_a_compliant_order(result: dict[str, Any]) -> None:
    outcome = _by_call_id(result)["a1"]
    assert outcome.allowed is True
    assert outcome.rule == "policy"
    assert outcome.payload["status"] == "SUCCESS"
    assert outcome.order["symbol"] == "AAPL"
    assert outcome.order["notional"] == "3000.00"


def test_notional_cap_blocks_before_the_handler(
    result: dict[str, Any], policy: dict[str, Any]
) -> None:
    outcome = _by_call_id(result)["a2"]
    assert outcome.allowed is False
    assert outcome.rule == "max_gross_buy_notional_usd"
    assert "15000.00" in outcome.reason
    assert policy["max_gross_buy_notional_usd"] in outcome.reason


def test_quantity_cap_blocks(result: dict[str, Any], policy: dict[str, Any]) -> None:
    outcome = _by_call_id(result)["a3"]
    assert outcome.allowed is False
    assert outcome.rule == "max_quantity"
    assert str(policy["max_quantity"]) in outcome.reason


def test_symbol_allowlist_blocks_the_other_broker_schema(result: dict[str, Any]) -> None:
    outcome = _by_call_id(result)["a4"]
    assert outcome.allowed is False
    assert outcome.rule == "symbol_allowlist"
    assert "TSLA" in outcome.reason


def test_side_allowlist_blocks(result: dict[str, Any]) -> None:
    outcome = _by_call_id(result)["a6"]
    assert outcome.allowed is False
    assert outcome.rule == "side_allowlist"


def test_both_broker_schemas_produce_the_same_canonical_order(result: dict[str, Any]) -> None:
    outcomes = _by_call_id(result)
    broker_a = outcomes["a1"].order
    broker_b = outcomes["a5"].order
    assert broker_a == broker_b
    assert broker_a["notional"] == "3000.00"


def test_broken_policy_blocks_everything(result: dict[str, Any]) -> None:
    outcome = _by_call_id(result)["a10"]
    assert outcome.allowed is False
    assert "policy evaluation failed" in outcome.message
    assert outcome.rule == ""  # no policy was loaded, so no rule applied


def test_garbage_arguments_never_reach_the_handler(result: dict[str, Any]) -> None:
    outcomes = _by_call_id(result)
    for call_id in ("a7", "a8", "a9"):
        outcome = outcomes[call_id]
        assert outcome.allowed is False
        assert "policy evaluation failed" in outcome.message


def test_audit_trail_records_every_call(result: dict[str, Any]) -> None:
    rows = result["audit_rows"]
    assert len(rows) == 10
    decisions = [row["decision"] for row in rows]
    assert decisions.count("EXECUTION_SUCCEEDED") == 2
    assert decisions.count("EXECUTION_BLOCKED") == 8


def test_audit_rows_keep_the_exact_reason(result: dict[str, Any]) -> None:
    reasons = {row["tool_call_id"]: row["reason"] for row in result["audit_rows"]}
    assert "floats are not permitted" in reasons["a7"]
    assert "fractional shares are not supported" in reasons["a8"]
    assert "booleans are not valid numeric values" in reasons["a9"]
    assert "missing required keys" in reasons["a10"]


def test_every_decision_is_stamped_with_the_policy_hash(result: dict[str, Any]) -> None:
    hashes = {
        row["tool_call_id"]: row["policy_hash"]
        for row in result["audit_rows"]
        if row["decision"] != "EXECUTION_BLOCKED" or not row["reason"].startswith("FAIL_CLOSED")
    }
    assert len(set(hashes.values())) == 1
    assert next(iter(hashes.values()))


def test_failed_policy_evaluation_is_not_attributed_to_a_policy(result: dict[str, Any]) -> None:
    rows = {row["tool_call_id"]: row for row in result["audit_rows"]}
    assert rows["a10"]["policy_hash"] == ""


def test_ledger_holds_only_the_allowed_orders(result: dict[str, Any]) -> None:
    rows = result["ledger_rows"]
    assert [row["symbol"] for row in rows] == ["AAPL", "AAPL"]
    assert [row["quantity"] for row in rows] == ["20", "20"]
    assert [row["notional"] for row in rows] == ["3000.00", "3000.00"]


def test_the_story_does_not_leak_process_state(result: dict[str, Any]) -> None:
    """The story restores the seams it redirects, so the suite stays clean."""
    from trade_preflight.hooks import execution_gate as gate

    assert callable(gate.load_policy)
    assert gate.load_policy.__name__ != "<lambda>"
    assert result["handler_invocations"] == 2
