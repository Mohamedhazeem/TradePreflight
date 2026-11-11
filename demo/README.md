# TradePreflight demo fixture

A deterministic walkthrough of the whole value proposition: **an order that
complies is executed, an order that cannot be proven compliant is blocked
before it reaches the handler, and every decision leaves an audit trail.**

Nothing here talks to a broker, a network, or a credential store. The
offline half runs the *real* plugin code in a temporary workspace.

## Files

```text
demo/
├── README.md          # this file
├── STORYBOARD.md      # the 90-second shot list, with paste-ready prompts
├── run_demo.sh        # one command: the offline story + the Hermes prompts
├── story.py           # the deterministic story, driving the real gate
├── policy.json        # the operator policy the story enforces
└── policy_broken.json # a policy with a typo: everything stops (fail closed)
```

## Run it

```bash
./demo/run_demo.sh           # the offline story, then the prompts for Hermes
./demo/run_demo.sh --quiet   # the offline story without the commentary
```

Or just the story:

```bash
python demo/story.py
```

The story prints six acts:

| Act | What it shows | Outcome |
|---:|---|---|
| 1 | A compliant Broker A order | ALLOWED, one ledger row |
| 2 | A notional breach and a quantity breach | BLOCKED (`max_gross_buy_notional_usd`, `max_quantity`) |
| 3 | The same policy applied to Broker B's schema | TSLA BLOCKED, AAPL ALLOWED, sell BLOCKED |
| 4 | A float, fractional shares, a boolean | BLOCKED (fail closed, no order) |
| 5 | A policy with a typo | BLOCKED (fail closed, no order) |
| 6 | The audit trail and the paper ledger | 10 calls, 2 handler invocations, 2 ledger rows |

The counters are the point: **10 tool calls, 2 handler invocations, 2 ledger
rows.** Every blocked call stopped before the handler ran.

## The live half

The offline story proves the gate. The live half shows it inside a real
conversation:

```bash
hermes plugins enable trade-preflight
hermes plugins doctor trade-preflight --ci
hermes                             # or use the Desktop app
```

The prompts `run_demo.sh` prints are plain natural language. No code, no
JSON payloads pasted into the chat.

| Prompt | Result |
|---|---|
| Use `trade_policy_get` and tell me the caps | the active policy and its SHA-256 |
| Buy 20 AAPL at 150.00 with `paper_place_order_a` | `{"status":"SUCCESS", ...}` |
| Buy 100 AAPL at 150.00 | blocked: `gross buy notional 15000.00 exceeds maximum 10000.00` |
| Buy 10 TSLA at 200.00 with `paper_place_order_b` | blocked: `symbol 'TSLA' is not allowed` |
| Show the audit trail | blocked / allowed / succeeded rows, each with a reason and a policy hash |

Name the tool in the prompt when you record it. Without the tool name the
model picks a tool by description, and if another trading tool is loaded it
may pick that one instead - and TradePreflight does not guard tools it does
not own.

## Before recording

- The operator policy lives in the Hermes profile, not in this repository:
  `<hermes-home>/plugin-data/trade-preflight/policy.json`. It is seeded from
  the shipped `policies/default.json` on first use. Show the file open in a
  second pane: the block messages carry the same `policy=<hash>` prefix, and
  that match is what makes the audit story land.
- Restart a running gateway so it picks up the plugin:
  `hermes gateway restart`. A gateway that is already running keeps the
  dependency environment it booted with.
- The demo needs **no credentials, no internet, and no broker account**. Say
  it out loud; judges ask.

## The story in one line

The agent asked for 100 shares. The policy said 10,000 dollars. The order
never reached the handler, and the refusal is in the audit trail with the
hash of the policy that made it.

## What this demo does not show

- **Real execution.** Execution is simulated in SQLite. TradePreflight is a
  gate; it is not a broker and it places no real order.
- **Coverage of other tools.** Only `paper_place_order_a` and
  `paper_place_order_b` are guarded. Terminal commands, other plugins' tools
  and manual trades in a broker app are not.
- **Cumulative limits.** The caps are per order, not per day or per
  portfolio. Splitting a large order into smaller ones is not detected.
