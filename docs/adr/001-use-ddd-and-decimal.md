# ADR 001 — Use Domain-Driven Design and `Decimal` for the Execution Firewall

- **Status:** Accepted
- **Date:** 2026-11-10
- **Deciders:** TradePreflight maintainers
- **Related:** `AGENTS.md`, `trade-preflight/src/trade_preflight/domain/`

## Context

TradePreflight intercepts AI-generated equity orders before execution. Two
properties are non-negotiable:

1. **The policy decision must not depend on which broker schema the model used.**
   Broker A sends `symbol`, `quantity`, and `limit_price`; Broker B sends
   `ticker`, `qty`, and `price`. A rule engine coupled to either schema is a
   bypass waiting to happen: an agent can choose the unguarded shape.
2. **A one-cent error is a correctness and compliance failure.** Binary
   floating-point values cannot represent most decimal fractions exactly. A
   limit of `10000.00` compared against a float-derived notional can admit an
   order that is actually over the limit, or reject one that is not.

The project is also a long-lived integration surface: new brokers, new policy
rules, and new audit requirements are expected.

## Decision

### 1. Adopt a layered Domain-Driven Design

- `domain/` owns the canonical `NormalizedOrder`, the `Policy` schema, and the
  `Decision` value object. It imports only the Python Standard Library.
- `adapters/` owns all broker-specific translation and emits `NormalizedOrder`.
  The policy engine never imports an adapter.
- `services/` owns policy loading and rule evaluation (`engine.py`) and SQLite
  audit persistence (`audit.py`).
- `tools/` and `hooks/` are the Hermes delivery mechanism. They orchestrate
  inner layers and contain no financial rules.
- Dependencies point inward: `hooks/tools -> services -> adapters/domain`.

Broker A and Broker B are implemented as two concrete `BrokerAdapter`
implementations. Their existence is an executable proof that the engine is
broker-agnostic, not merely a diagram.

### 2. Use `decimal.Decimal` for every monetary and quantity value

- Money, prices, quantities, and notional are `Decimal`.
- Values are parsed from strings. `float` inputs are rejected at the domain
  boundary rather than silently converted.
- Booleans are rejected explicitly because `True == 1` in Python.
- `NaN`, `Infinity`, and `-Infinity` are rejected with `is_finite()`.
- Negative and zero values are rejected. Fractional shares are rejected in the
  MVP.
- Notional is always derived (`quantity * limit_price`), never accepted from the
  model.
- SQLite persists decimals as `TEXT` to avoid `REAL` affinity and precision
  loss.

### 3. Keep policy evaluation deterministic and side-effect free

`PolicyEngine.evaluate(order)` is a pure function of the normalized order and the
loaded policy. It performs no I/O, no network calls, and no logging. The hook is
responsible for loading the policy, writing the audit row, and turning the
decision into a Hermes directive.

## Consequences

### Positive

- Adding a broker is an adapter change, not a rules change.
- Rules are trivially unit-testable without Hermes, network, or a broker.
- Decimal arithmetic is exact for the values operators actually use.
- The fail-closed boundary is small and auditable: one hook, one engine call.
- The audit trail can record the exact policy hash used for each decision.

### Negative / costs

- More files and indirection than a single-module plugin.
- Adapters must be kept behaviorally identical; this requires contract tests.
- `Decimal` is slower than `float`. Irrelevant at trade-call volume.
- JSON has no decimal type, so APIs must carry decimal strings and adapters must
  reject floats. This is deliberate friction.
- SQLite stores decimals as text, so range queries require casting; audit queries
  are timestamp-based, so this is acceptable.

## Alternatives considered

| Alternative | Rejected because |
|---|---|
| Floats with rounding at the boundary | Rounding hides the error; comparisons can still misclassify an order. |
| One shared “universal” broker schema | Couples rules to a schema the model can vary; invites bypass through a different tool. |
| Third-party financial/decimal library | Unnecessary dependency and supply-chain surface; `decimal` is sufficient. |
| Validation inside each tool handler | The security boundary must be centralized in `pre_tool_call`; per-handler checks are easy to forget. |
| Policy checks in prompt instructions | Prompts are advisory. The model can ignore or reinterpret them. |

## Compliance

- Code review rejects float literals in financial paths.
- Unit tests cover booleans, `NaN`, infinities, negatives, fractional shares,
  floats, and valid decimal strings.
- `AGENTS.md` restates these rules as a hard contributor contract.
