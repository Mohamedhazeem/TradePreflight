#!/usr/bin/env python3
"""TradePreflight demo story — six acts, one command, no Hermes required.

Every act drives the *real* plugin code: the same ``pre_tool_call`` and
``post_tool_call`` hooks, the same broker adapters, the same policy engine and
the same handlers Hermes calls. Only three Hermes-owned seams are redirected
into a temporary directory:

* the operator's policy file,
* the audit database,
* the paper-trading ledger database.

Nothing is written outside the temporary directory, no network is used, no
credentials are needed, and every run produces the same output.

Usage:
    python demo/story.py                 # the story, with the human commentary
    python demo/story.py --quiet         # the story, without the commentary
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from trade_preflight.adapters import get_adapter  # noqa: E402
from trade_preflight.hooks import execution_gate as gate  # noqa: E402
from trade_preflight.services import engine as engine_module  # noqa: E402
from trade_preflight.services.audit import AuditStore  # noqa: E402
from trade_preflight.tools import paper_trades  # noqa: E402

DEMO_DIR = Path(__file__).resolve().parent
POLICY_FILE = DEMO_DIR / "policy.json"
BROKEN_POLICY_FILE = DEMO_DIR / "policy_broken.json"

_WIDTH = 78


@dataclass(frozen=True)
class Step:
    """One tool call the story makes, and what it expects to happen."""

    act: str
    title: str
    tool: str
    args: dict[str, Any]
    call_id: str
    policy: Path
    expectation: str  # "allowed" or "blocked"
    note: str = ""


@dataclass
class Outcome:
    """What actually happened to one step."""

    step: Step
    allowed: bool
    message: str = ""
    rule: str = ""
    reason: str = ""
    policy_hash: str = ""
    order: dict[str, str] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)


def _build_steps(policy: Path, broken_policy: Path) -> list[Step]:
    """The storyboard, as executable steps."""
    return [
        Step(
            act="Act 1 - A compliant order gets through",
            title="Broker A buys 20 AAPL at 150.00 (notional 3000.00)",
            tool="paper_place_order_a",
            args={
                "symbol": "AAPL",
                "side": "buy",
                "quantity": "20",
                "order_type": "limit",
                "limit_price": "150.00",
            },
            call_id="a1",
            policy=policy,
            expectation="allowed",
            note="the order complies with the operator policy",
        ),
        Step(
            act="Act 2 - The risk caps bite",
            title="Broker A buys 100 AAPL at 150.00 (notional 15000.00 > 10000.00)",
            tool="paper_place_order_a",
            args={
                "symbol": "AAPL",
                "side": "buy",
                "quantity": "100",
                "order_type": "limit",
                "limit_price": "150.00",
            },
            call_id="a2",
            policy=policy,
            expectation="blocked",
            note="the handler never ran; nothing reached the ledger",
        ),
        Step(
            act="Act 2 - The risk caps bite",
            title="Broker A buys 300 AAPL at 10.00 (quantity 300 > 200)",
            tool="paper_place_order_a",
            args={
                "symbol": "AAPL",
                "side": "buy",
                "quantity": "300",
                "order_type": "limit",
                "limit_price": "10.00",
            },
            call_id="a3",
            policy=policy,
            expectation="blocked",
            note="the handler never ran; nothing reached the ledger",
        ),
        Step(
            act="Act 3 - One policy, two broker schemas",
            title="Broker B buys 10 TSLA at 200.00 (symbol not on the allowlist)",
            tool="paper_place_order_b",
            args={
                "ticker": "TSLA",
                "direction": "buy",
                "qty": "10",
                "order_type": "limit",
                "price": "200.00",
            },
            call_id="a4",
            policy=policy,
            expectation="blocked",
            note="the handler never ran; a different broker schema, the same policy",
        ),
        Step(
            act="Act 3 - One policy, two broker schemas",
            title="Broker B buys 20 AAPL at 150.00 (same canonical order as Broker A)",
            tool="paper_place_order_b",
            args={
                "ticker": "AAPL",
                "direction": "buy",
                "qty": "20",
                "order_type": "limit",
                "price": "150.00",
            },
            call_id="a5",
            policy=policy,
            expectation="allowed",
            note="the same canonical order as Broker A, so the same policy applies",
        ),
        Step(
            act="Act 3 - One policy, two broker schemas",
            title="Broker B sells 20 AAPL at 150.00 (side not on the allowlist)",
            tool="paper_place_order_b",
            args={
                "ticker": "AAPL",
                "direction": "sell",
                "qty": "20",
                "order_type": "limit",
                "price": "150.00",
            },
            call_id="a6",
            policy=policy,
            expectation="blocked",
            note="the handler never ran; nothing reached the ledger",
        ),
        Step(
            act="Act 4 - Garbage in, nothing out",
            title="Broker A with a float quantity 20.0",
            tool="paper_place_order_a",
            args={
                "symbol": "AAPL",
                "side": "buy",
                "quantity": 20.0,
                "order_type": "limit",
                "limit_price": "150.00",
            },
            call_id="a7",
            policy=policy,
            expectation="blocked",
            note="the model sees only a generic refusal; the exact reason is in the audit trail",
        ),
        Step(
            act="Act 4 - Garbage in, nothing out",
            title="Broker A with fractional shares 20.5",
            tool="paper_place_order_a",
            args={
                "symbol": "AAPL",
                "side": "buy",
                "quantity": "20.5",
                "order_type": "limit",
                "limit_price": "150.00",
            },
            call_id="a8",
            policy=policy,
            expectation="blocked",
            note="the handler never ran; the model sees only a generic refusal, "
            "and the exact reason is in the audit trail",
        ),
        Step(
            act="Act 4 - Garbage in, nothing out",
            title="Broker A with a boolean quantity",
            tool="paper_place_order_a",
            args={
                "symbol": "AAPL",
                "side": "buy",
                "quantity": True,
                "order_type": "limit",
                "limit_price": "150.00",
            },
            call_id="a9",
            policy=policy,
            expectation="blocked",
            note="the handler never ran; the model sees only a generic refusal, "
            "and the exact reason is in the audit trail",
        ),
        Step(
            act="Act 5 - A broken policy stops everything",
            title="Broker A buys 20 AAPL at 150.00 under a policy with a typo",
            tool="paper_place_order_a",
            args={
                "symbol": "AAPL",
                "side": "buy",
                "quantity": "20",
                "order_type": "limit",
                "limit_price": "150.00",
            },
            call_id="a10",
            policy=broken_policy,
            expectation="blocked",
            note="the handler never ran; an unreadable policy is not an empty "
            "policy, so every order stops",
        ),
    ]


def _describe(step: Step) -> tuple[str, str, str]:
    """Rule, reason and policy hash the engine produced (display only)."""
    try:
        adapter = get_adapter(step.tool)
        if adapter is None:
            return "", "", ""
        order = adapter.normalize(step.args)
        policy = engine_module.load_policy(step.policy)
        decision = engine_module.PolicyEngine(policy).evaluate(order)
    except Exception:
        return "", "", ""
    return decision.rule, decision.reason, decision.policy_hash


def _run_step(step: Step) -> Outcome:
    """Run one step through the real hook, and the real handler when allowed."""
    gate.load_policy = lambda: engine_module.load_policy(step.policy)

    decision = gate.pre_tool_call(
        tool_name=step.tool, args=step.args, tool_call_id=step.call_id
    )
    rule, reason, policy_hash = _describe(step)

    if decision is not None:
        return Outcome(
            step=step,
            allowed=False,
            message=str(decision.get("message", "")),
            rule=rule,
            reason=reason,
            policy_hash=policy_hash,
        )

    handler = (
        paper_trades.place_order_a
        if step.tool == "paper_place_order_a"
        else paper_trades.place_order_b
    )
    result = handler(step.args)
    payload = json.loads(result)
    gate.post_tool_call(
        tool_name=step.tool, result=result, status="success", tool_call_id=step.call_id
    )
    return Outcome(
        step=step,
        allowed=True,
        rule=rule,
        reason=reason,
        policy_hash=policy_hash,
        order=dict(payload.get("order", {})),
        payload=payload,
    )


def _silence_fail_closed_tracebacks() -> None:
    """Keep the console clean.

    The hook logs every fail-closed block as an exception, which is right in
    production (the operator wants the stack trace) and wrong in a demo
    recording. The precise reason is not lost: it is in the audit trail, which
    the story prints at the end.
    """
    logging.getLogger("trade_preflight.hooks.execution_gate").setLevel(logging.CRITICAL)


def run_story(
    policy_file: Path = POLICY_FILE,
    broken_policy_file: Path = BROKEN_POLICY_FILE,
) -> dict[str, Any]:
    """Run the whole story and return everything the demo asserts on."""
    _silence_fail_closed_tracebacks()
    steps = _build_steps(policy_file, broken_policy_file)

    workspace = Path(tempfile.mkdtemp(prefix="tradepreflight-demo-"))
    audit_db = workspace / "audit.db"
    ledger_db = workspace / "ledger.db"

    # The three seams below are process-wide. Save and restore them so the
    # story can run inside a test session without leaking state.
    saved = (
        gate.load_policy,
        gate.default_audit_store,
        paper_trades._ledger_connection_factory,
        paper_trades.handler_invocation_count,
        paper_trades._order_counter,
    )
    store = AuditStore(connection_factory=lambda: sqlite3.connect(str(audit_db)))
    gate.default_audit_store = lambda: store
    paper_trades.reset_handler_invocation_count()
    paper_trades._ledger_connection_factory = lambda: sqlite3.connect(str(ledger_db))

    try:
        outcomes = [_run_step(step) for step in steps]

        with sqlite3.connect(str(ledger_db)) as connection:
            connection.row_factory = sqlite3.Row
            ledger_rows = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT symbol, side, quantity, price, notional, timestamp
                      FROM paper_ledger
                     ORDER BY id
                    """
                ).fetchall()
            ]

        audit_rows = list(reversed(store.recent(50)))  # chronological for the demo

        return {
            "outcomes": outcomes,
            "audit_rows": audit_rows,
            "ledger_rows": ledger_rows,
            "handler_invocations": paper_trades.handler_invocation_count,
            "policy_file": policy_file,
            "broken_policy_file": broken_policy_file,
            "workspace": workspace,
        }
    finally:
        (
            gate.load_policy,
            gate.default_audit_store,
            paper_trades._ledger_connection_factory,
            paper_trades.handler_invocation_count,
            paper_trades._order_counter,
        ) = saved


def _rule(width: int = _WIDTH) -> None:
    print("-" * width)


def _act(title: str) -> None:
    print()
    _rule()
    print(title)
    _rule()


def _print_story(result: dict[str, Any], quiet: bool) -> None:
    outcomes: list[Outcome] = result["outcomes"]

    print("=" * _WIDTH)
    print("TradePreflight demo story - six acts, no Hermes, no network")
    print("=" * _WIDTH)
    print()
    print("Policy in force : demo/policy.json (operator-owned, re-read every call)")
    print("Policy SHA-256  :", outcomes[0].policy_hash or "(unavailable)")
    print("Workspace       : temporary directory (nothing written outside it)")

    current_act = ""
    for outcome in outcomes:
        step = outcome.step
        if step.act != current_act:
            current_act = step.act
            _act(current_act)

        print()
        print(f"  Tool call : {step.tool}")
        print(f"  Arguments : {json.dumps(step.args, sort_keys=True, default=str)}")
        if outcome.allowed:
            order = outcome.order
            print(f"  Decision  : ALLOWED  (rule={outcome.rule})")
            print(f"  Result    : {outcome.payload.get('message')}")
            print(
                f"  Canonical : {order.get('symbol')} {order.get('side')} "
                f"{order.get('quantity')} @ {order.get('limit_price')} "
                f"(notional {order.get('notional')})"
            )
            if not quiet and step.note:
                print(f"  Why       : {step.note}")
        else:
            print("  Decision  : BLOCKED")
            print(f"  Message   : {outcome.message}")
            if not quiet and step.note:
                print(f"  Why       : {step.note}")

    _act("Act 6 - The evidence")
    print()
    print("  Audit trail (oldest first)")
    for row in result["audit_rows"]:
        print(f"    {row['tool_call_id']:<4} {row['decision']:<24} {row['reason']}")
    print()
    print("  Paper ledger (the only rows that exist)")
    for row in result["ledger_rows"]:
        print(
            f"    {row['symbol']} {row['side']} {row['quantity']} @ {row['price']}"
            f"  notional={row['notional']}"
        )
    print()
    blocked = sum(1 for outcome in outcomes if not outcome.allowed)
    print(f"  Tool calls made   : {len(outcomes)}")
    print(f"  Handler invocations: {result['handler_invocations']}")
    print(f"  Ledger rows        : {len(result['ledger_rows'])}")
    print(f"  Blocked calls      : {blocked}")
    print()
    print("  Every blocked call stopped before the handler. Every allowed call")
    print("  produced exactly one ledger row, from either broker schema.")
    print()
    _rule()
    print("Next: paste the prompts in demo/STORYBOARD.md into Hermes to see the")
    print("same gate fire on a live agent conversation.")
    _rule()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the TradePreflight demo story.")
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="print the decisions without the commentary lines",
    )
    args = parser.parse_args(argv)

    result = run_story()
    _print_story(result, args.quiet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
