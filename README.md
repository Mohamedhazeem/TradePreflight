# TradePreflight: Equities Execution Firewall

> **The agent proposes. The policy gate decides.**

TradePreflight is a native [Hermes Agent](https://github.com/NousResearch/hermes-agent)
plugin that intercepts AI-initiated equity trade tool calls and blocks them unless
they satisfy an operator-owned policy. It is deterministic, local-first, and
fail-closed: if the plugin cannot prove an order is compliant, the order does not
execute.

> **Project status: architectural scaffold.** The domain contracts, adapters,
> policy schema, audit store, tool registration, and fail-closed hook are in
> place. `PolicyEngine.evaluate()` and the paper-trading ledger writes are
> intentionally unimplemented and currently **block every guarded order**. That
> is the safe default. See [Roadmap](#roadmap).

---

## Table of contents

- [Why TradePreflight](#why-tradepreflight)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Architecture](#architecture)
- [Tools](#tools)
- [Policy](#policy)
- [Audit lifecycle](#audit-lifecycle)
- [Security boundaries](#security-boundaries)
- [Development](#development)
- [License](#license)

---

## Why TradePreflight

An LLM can generate a plausible-looking order in milliseconds. It cannot be
trusted to respect position limits, notional caps, or symbol restrictions. Prompt
instructions are suggestions; a policy gate is an enforcement mechanism.

TradePreflight sits on Hermes' `pre_tool_call` hook and applies the same decision
to every broker adapter:

1. Capture the raw tool call before the handler runs.
2. Normalize broker-specific arguments into one canonical `NormalizedOrder`.
3. Evaluate the order against the operator's policy file.
4. Block, with a human-readable reason, or allow the call to proceed.
5. Record the decision and the eventual execution outcome in SQLite.

The model never sees the policy file unless the operator exposes it through the
read-only `trade_policy_get` tool. The model cannot edit it.

## Installation

### Requirements

- Python 3.10+
- Hermes Agent with native plugin support
- PyYAML 6.x
- No broker account, API key, or network access is required

### Install as a native Hermes plugin

```bash
git clone https://github.com/tradepreflight/trade-preflight.git
cp -R trade-preflight ~/.hermes/plugins/trade-preflight
hermes plugins enable trade-preflight
hermes plugins doctor trade-preflight --ci
```

Restart Hermes (or the gateway) so the plugin is loaded.

### Install for local development

```bash
cd trade-preflight
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest
```

The package uses a `src/` layout. The root `__init__.py` is the Hermes entry
point and bootstraps `src/` onto `sys.path` for directory installs.

### Operator data locations

| Data | Location |
|---|---|
| Policy file | `plugin_data_dir("trade-preflight")/policy.json` |
| SQLite database | `plugin_data_dir("trade-preflight")/data.db` |
| Shipped default policy | `policies/default.json` (copied on first run) |

`plugin_data_dir()` resolves under the active Hermes profile
(`<HERMES_HOME>/plugin-data/trade-preflight/`) and survives plugin updates.
Never place operator state in the plugin install directory.

## Quick start

1. Start Hermes and ask for a trade:

   ```text
   Buy 20 shares of AAPL at $150 using Broker A.
   ```

2. Inspect the policy the gate is using:

   ```text
   Use trade_policy_get.
   ```

3. Dry-run an order without executing it:

   ```text
   Use trade_check with symbol AAPL, side buy, quantity 20,
   order_type limit, limit_price "150.00".
   ```

4. Review the audit trail:

   ```text
   Use trade_audit with limit 20.
   ```

5. Edit the policy file as the operator, then restart or wait for the next call.
   The policy is re-read on every guarded tool call and every decision records
   the SHA-256 of the policy that produced it.

## Architecture

TradePreflight follows Domain-Driven Design with a dependency rule that points
inward. Broker translation, persistence, and Hermes wiring are all replaceable;
the domain does not know they exist.

```text
                    Hermes Agent
                         |
             pre_tool_call / post_tool_call
                         |
                 hooks/execution_gate.py
                    /            \
        adapters/base.py       services/audit.py
          /          \                |
 broker_a.py    broker_b.py       SQLite (plugin_db)
          \          /                |
        NormalizedOrder               |
               |                      |
        services/engine.py  <----------+
               |
          domain/policy.py
```

### Layers

| Layer | Responsibility | May import |
|---|---|---|
| `domain/` | `NormalizedOrder`, `Policy`, `Decision`, validation | stdlib only |
| `adapters/` | Broker A/B argument translation, adapter registry | `domain` |
| `services/` | Policy loading, rule evaluation, SQLite audit | `domain` |
| `tools/` | Hermes tool schemas + handlers | `services`, `domain` |
| `hooks/` | `pre_tool_call` / `post_tool_call`, fail-closed wiring | all inner layers |

### The dual-adapter proof

The policy engine never sees a broker schema. Two adapters prove it:

| Broker A | Broker B | Canonical |
|---|---|---|
| `symbol` | `ticker` | `symbol` |
| `side` | `direction` | `side` |
| `quantity` | `qty` | `quantity` |
| `order_type` | `order_type` | `order_type` |
| `limit_price` | `price` | `limit_price` |
| — derived — | — derived — | `notional` |

Both adapters produce the same `NormalizedOrder` for equivalent inputs. Adding
Broker C requires one adapter and one registry entry; the policy engine and rules
do not change.

### Why `Decimal`

Binary floats cannot represent most decimal fractions exactly. `0.1 + 0.2` is
not `0.3` in IEEE-754, and a limit check that is off by a fraction of a cent is a
correctness and compliance bug. Every monetary value is a `decimal.Decimal`
parsed from a string. Booleans, `NaN`, `Infinity`, negative values, and
fractional shares are rejected at the domain boundary. See
[ADR 001](docs/adr/001-use-ddd-and-decimal.md).

## Tools

| Tool | Type | Purpose |
|---|---|---|
| `paper_place_order_a` | execution | Simulated Broker A order: `symbol`, `side`, `quantity`, `order_type`, `limit_price` |
| `paper_place_order_b` | execution | Simulated Broker B order: `ticker`, `direction`, `qty`, `order_type`, `price` |
| `trade_check` | read-only | Normalize and dry-run an order against the policy. Never executes. |
| `trade_policy_get` | read-only | Return the active policy and its SHA-256. |
| `trade_audit` | read-only | Return recent audit rows, newest first. |

All five tools are declared in `plugin.yaml` and registered from the root
`__init__.py`. The two execution tools are guarded by `pre_tool_call`; the
read-only tools are not.

### Handler contract

```python
def handler(args: dict, **kwargs) -> str:
    """Always return a JSON string, including on error. Never raise."""
```

## Policy

The policy is a JSON object owned by the operator:

```json
{
  "max_gross_buy_notional_usd": "10000.00",
  "max_quantity": 200,
  "symbol_allowlist": ["AAPL", "MSFT"],
  "order_type_allowlist": ["limit"],
  "side_allowlist": ["buy"]
}
```

| Key | Type | Rule |
|---|---|---|
| `max_gross_buy_notional_usd` | decimal string | Buy notional may not exceed this value |
| `max_quantity` | integer | Share quantity may not exceed this value |
| `symbol_allowlist` | string array | Symbol must be listed (case-insensitive, normalized to upper) |
| `order_type_allowlist` | string array | Order type must be listed (MVP: `limit` only) |
| `side_allowlist` | string array | Side must be listed (MVP: `buy` only) |

Rules:

- Missing keys, unknown keys, wrong types, empty allowlists, non-finite values,
  and malformed JSON are configuration errors. A configuration error **blocks**
  every guarded call.
- `max_gross_buy_notional_usd` is parsed and compared as `Decimal`, never float.
- The policy file is re-read per guarded call so operator edits take effect
  without a restart.
- Every audit row stores the SHA-256 of the exact policy used for the decision.
- There is no policy-editing tool. Only the operator may edit the file.

## Audit lifecycle

`pre_tool_call` writes the initial decision; `post_tool_call` correlates the
handler outcome by the Hermes `tool_call_id`.

| State | Written by | Meaning |
|---|---|---|
| `EXECUTION_BLOCKED` | `pre_tool_call` | Policy violation or fail-closed error. Handler never ran. |
| `EXECUTION_ALLOWED` | `pre_tool_call` | Policy passed. Awaiting execution. |
| `EXECUTION_SUCCEEDED` | `post_tool_call` | Handler returned a recognized success payload. |
| `EXECUTION_FAILED` | `post_tool_call` | Handler raised or returned an error payload. |
| `EXECUTION_OUTCOME_UNKNOWN` | `post_tool_call` | Handler ran but the result shape was unrecognized. |

Audit writes are best-effort and never weaken a block. Decimal values are stored
as `TEXT`; timestamps are ISO-8601 UTC.

## Security boundaries

Read this section carefully. Overstating coverage is a safety defect.

### Guarded

- `paper_place_order_a`
- `paper_place_order_b`

These are the only tools intercepted by `pre_tool_call`. The check is keyed by
exact tool name.

### Not guarded

- **Manual broker app trades are not protected.** If a human places an order in
  a brokerage app or website, TradePreflight never sees it. The plugin is an
  execution firewall for Hermes tool calls, not a broker-side risk system.
- Arbitrary terminal commands, scripts, `curl`, or broker SDK calls made outside
  a registered tool.
- Other plugins' tools, including other trading tools that do not use these
  adapters.
- Trades placed before the plugin loads or after it is disabled.
- Market orders, fractional shares, options, futures, crypto, and any asset class
  other than long-only equities. These are rejected by the domain layer, not
  risk-managed.

### Policy integrity

The plugin does not expose a policy-editing tool and never accepts policy values
from the model. However, the policy file lives in the active Hermes profile. An
agent with unrestricted shell access under the same OS user could read or modify
it. Mitigations are OS-level: run Hermes as a dedicated user, restrict file
permissions (`0600`), use Hermes approvals for shell access, and keep the policy
outside any directory the agent can write.

### Operational boundaries

- No external API calls, telemetry, or network sockets.
- No real broker integration in the MVP; execution is simulated in SQLite.
- Paper results are not market data and do not prove a strategy is profitable.
- The plugin is not a substitute for a broker's own risk controls or regulatory
  obligations.

## Development

```bash
cd trade-preflight
python -m compileall -q src
pytest
hermes plugins doctor . --ci
```

Repository conventions:

- `AGENTS.md` is binding for all contributors.
- Domain tests must cover every policy rule and every Decimal edge case.
- `tests/unit/` contains pure domain/adapter/engine tests.
- `tests/integration/` exercises hooks, tools, and SQLite together.
- Do not add third-party financial libraries. The allowed dependency surface is
  the Python Standard Library plus PyYAML for YAML configuration.

## License

MIT. See [LICENSE](LICENSE).
