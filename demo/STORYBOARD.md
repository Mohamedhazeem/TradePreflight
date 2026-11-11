# Demo storyboard — 90 seconds

A single reproducible walkthrough: **an order that complies executes, an order
that breaches the policy never reaches the handler, and every decision is
recorded with the hash of the policy that made it.**

Every prompt below is plain natural language. No code, no JSON payloads
pasted into the chat, no tool names memorised by the viewer (except where the
shot deliberately names one, to keep the recording deterministic).

## Setup (before recording)

```bash
cd /path/to/TradePreflight
hermes plugins enable trade-preflight
hermes plugins doctor trade-preflight --ci   # shows "5 tool(s), 2 hook(s)"
./demo/run_demo.sh                           # the offline story + the prompts
hermes                                       # start the chat (or use the Desktop app)
```

> **The operator policy is the thing on camera.** It lives in the Hermes
> profile at `<hermes-home>/plugin-data/trade-preflight/policy.json` and is
> seeded from the shipped `policies/default.json` on first use. Keep it open
> in a second pane: every block message carries the same `policy=<hash>`
> prefix, and that match is what makes the audit story land.
>
> **Restart a running gateway** (`hermes gateway restart`) so it picks up the
> plugin. A gateway that is already running keeps the dependency environment
> it booted with.

## Shot list

| Time | Shot | What the viewer sees | Why it matters |
|---:|---|---|---|
| 0:00–0:08 | Terminal: `hermes plugins doctor trade-preflight --ci` | `5 tool(s), 2 hook(s)` | The tools and the gate are registered, not promised. |
| 0:08–0:18 | Prompt 1: read the policy | the caps, the allowlists, the policy SHA-256 | The policy is operator-owned, and the agent can read it but never change it. |
| 0:18–0:28 | Prompt 2: a compliant order | `{"status":"SUCCESS","order_id":"mock-0001"}` | The happy path works. Nothing here is theatre. |
| 0:28–0:42 | Prompt 3: 100 shares | **blocked**: `gross buy notional 15000.00 exceeds maximum 10000.00` | **The gatekeeper moment.** 100 × 150 = 15,000 against a 10,000 cap. The handler never ran. |
| 0:42–0:54 | Prompt 4: another broker | **blocked**: `symbol 'TSLA' is not allowed (allowed: ['AAPL', 'MSFT'])` | Broker B's schema (`ticker/direction/qty/price`) produces the same verdict. One policy, many brokers. |
| 0:54–1:05 | Prompt 5: the agent tries to be clever | *"split it into two orders of 50"* → still blocked | The limit is a limit, not a suggestion. Be honest on camera: caps are per order, not cumulative. |
| 1:05–1:18 | Prompt 6: the evidence | blocked / allowed / succeeded rows, each with a reason and the policy hash | Every decision is auditable, and the hash ties it to one exact policy. |
| 1:18–1:28 | Terminal: `sqlite3 .../data.db "select * from paper_ledger"` | exactly one row | The blocked orders never touched the ledger. One order in, one row out. |
| 1:28–1:30 | Closing card | "TradePreflight — the agent proposes, the policy decides." | |

## Prompts (paste verbatim)

**1 — Read the policy**
```
Use trade_policy_get and tell me the notional cap, the quantity cap and the
allowlists you are enforcing.
```

**2 — A compliant order**
```
Use the paper_place_order_a tool to buy 20 shares of AAPL as a limit order at
150.00.
```

**3 — The notional cap bites**
```
Now buy 100 shares of AAPL as a limit order at 150.00.
```

**4 — Another broker, the same policy**
```
Use the paper_place_order_b tool to buy 10 shares of TSLA as a limit order at
200.00.
```

**5 — The agent tries to work around it**
```
Split that into two orders of 50 shares each so it fits the cap.
```

**6 — The evidence**
```
Show me the TradePreflight audit trail for the last 10 orders.
```

## Expected results

| Prompt | Result |
|---|---|
| 1 | the active policy plus its SHA-256 |
| 2 | `{"status":"SUCCESS","order_id":"mock-0001",...}` and one ledger row |
| 3 | blocked, `rule=max_gross_buy_notional_usd` |
| 4 | blocked, `rule=symbol_allowlist` |
| 5 | blocked again — the caps are per order, and the agent does not get to renegotiate them |
| 6 | `EXECUTION_BLOCKED` / `EXECUTION_ALLOWED` / `EXECUTION_SUCCEEDED` rows with reasons |

## Recording notes

- Use a **large terminal font** (14pt+). The reason string and the policy hash
  are the payoff; they must be legible.
- Name the tool in prompts 2 and 4. Without a tool name the model chooses by
  description, and if another trading tool is loaded it may choose that one
  instead — and TradePreflight does not guard tools it does not own.
- Pre-warm the chat: run prompt 1 once before you start recording, so the
  capture does not spend its first ten seconds on model warm-up.
- Say out loud that the demo needs **no credentials, no internet and no
  broker account**, and that execution is simulated in SQLite.
- If the model is slow, cut shot 6 (the audit trail). Never cut shot 3 (the
  blocked order) or shot 4 (the second broker) — those two carry the
  argument.

## Backup plan

If the live demo misbehaves on stage, the story still holds with these two
one-liners, which need no model at all:

```bash
python demo/story.py     # the same six acts, offline, deterministic
pytest tests/integration/test_demo_story.py -q   # the same claims, asserted
```

The offline story prints the identical block messages, the identical audit
rows and the identical counters: **10 tool calls, 2 handler invocations,
2 ledger rows.**
