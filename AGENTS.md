# AGENTS.md — Engineering Rules for TradePreflight

This file is a hard contract for every human or AI contributor. Read it before
touching code. If a request conflicts with these rules, stop and surface the
conflict instead of weakening the firewall.

## Non-negotiable invariants

1. **Fail closed.** An order that cannot be proven compliant is blocked.
2. **The agent proposes; the policy gate decides.** Model output is untrusted input.
3. **The policy engine is broker-agnostic.** It only ever receives a `NormalizedOrder`.
4. **Money is never a `float`.**
5. **No network calls and no third-party financial libraries.**

---

## 1. Financial math — `Decimal` only

- **NEVER** use binary floats for money, prices, quantities, or notional.
  This includes literals such as `1.0`, `0.1`, `100.00`, and `float(...)`.
- **ALWAYS** use `decimal.Decimal` for monetary and quantity values.
- Use `Decimal("...")` from a string. Do not use `Decimal(0.1)`.
- Reject booleans explicitly. In Python, `True == 1`, so a boolean can silently
  become a valid quantity.
- Reject `NaN`, `Infinity`, and `-Infinity` with `value.is_finite()`.
- Reject negative and zero prices/quantities.
- Reject fractional shares in the MVP (`quantity == quantity.to_integral_value()`).
- Never trust a model-supplied notional. Always derive
  `notional = quantity * limit_price` inside the domain layer.
- Persist decimal values as `TEXT`, never as SQLite `REAL`.

**Correct:**

```python
from decimal import Decimal, InvalidOperation

def parse_money(raw: object, field: str) -> Decimal:
    if isinstance(raw, bool):
        raise ValueError(f"{field}: booleans are not valid amounts")
    if isinstance(raw, float):
        raise ValueError(f"{field}: floats are not permitted")
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field}: invalid decimal") from exc
    if not value.is_finite():
        raise ValueError(f"{field}: non-finite values are not permitted")
    return value
```

**Forbidden:**

```python
notional = quantity * 150.0          # float arithmetic
qty = Decimal(0.1)                   # float constructor
if quantity > 100: ...               # silently accepts True / 100.5
```

## 2. Fail closed in `pre_tool_call`

The `pre_tool_call` hook is the security boundary. It must:

- Wrap **all** of its logic in `try/except Exception`.
- Explicitly return `{"action": "block", "message": "<non-empty reason>"}` on
  any exception, malformed argument, missing policy, unknown schema, timeout, or
  ambiguous result.
- Never return `None` for a guarded tool unless a policy decision explicitly
  allowed the order.
- Never let an exception escape. Hermes treats a raising or timed-out
  `pre_tool_call` as a block, but relying on the host is not sufficient.
- Keep the model-facing block message free of secrets, stack traces, and raw
  policy contents. Log details locally.

Template:

```python
def pre_tool_call(tool_name="", args=None, tool_call_id="", **kwargs):
    adapter = get_adapter(tool_name)
    if adapter is None:
        return None  # not a guarded tool; this plugin does not police it

    try:
        order = adapter.normalize(args or {})
        decision = PolicyEngine(load_policy()).evaluate(order)
        audit_decision(tool_call_id, order, decision)
        if decision.allowed:
            return None
        return {"action": "block", "message": decision.reason}
    except Exception:
        logger.exception("TradePreflight failed closed for %s", tool_name)
        audit_failure_best_effort(tool_call_id, tool_name, args)
        return {
            "action": "block",
            "message": "TradePreflight blocked this order because policy evaluation failed.",
        }
```

A block with an empty message is invalid in Hermes. Always provide one.

## 3. Broker agnosticism

- The policy engine accepts **only** `trade_preflight.domain.order.NormalizedOrder`.
  It must not import adapter modules, Hermes modules, or broker-specific field names.
- Broker translation belongs in `adapters/` only.
- Two adapters are mandatory and must remain behaviorally equivalent:
  - **Broker A** — `paper_place_order_a(symbol, side, quantity, order_type, limit_price)`
  - **Broker B** — `paper_place_order_b(ticker, direction, qty, order_type, price)`
- Both must normalize to the same canonical order for equivalent inputs, e.g.
  `AAPL / buy / 10 / limit / 150.00`.
- Adding a broker means adding an adapter and registering its tool name. It must
  not require a change to the policy engine or the policy schema.
- Never accept a `notional` argument from a broker schema. Derive it.

## 4. Paper trading handlers

`paper_place_order_a` and `paper_place_order_b` are the only execution handlers
in the MVP. When implemented (Slice 3), each handler must:

1. Re-validate and normalize its raw arguments through its adapter. Do not trust
   the hook to have done it.
2. Insert exactly one row into the `paper_ledger` table using parameterized SQL.
3. Return a JSON string with a success payload, for example:

   ```json
   {"status": "SUCCESS", "order_id": "mock-...", "message": "Simulated buy of 10 AAPL shares executed."}
   ```

4. Never raise. Catch all exceptions and return a JSON error payload.
5. Make no network requests and touch no real broker API.

The ledger is append-only. Do not update or delete rows.

## 5. Database rules

- Use **only** `sqlite3` through the Hermes helper:

  ```python
  from plugins.plugin_storage import plugin_db

  conn = plugin_db("trade-preflight")
  ```

- Do not open raw `sqlite3.connect(...)` paths, create ad-hoc databases, or write
  into the plugin install directory.
- All operator state, the policy file, and SQLite data live under
  `plugin_data_dir("trade-preflight")`, never in the plugin source tree.
- Use parameterized SQL (`?` placeholders). Never interpolate values into SQL.
- Keep schema creation idempotent (`CREATE TABLE IF NOT EXISTS`) and run it from
  `services/schema.sql`.
- Close connections after use; commit writes explicitly.
- Audit writes are best-effort on the block path: an audit failure must never
  turn a block into an allow. An **allowed** order must not execute without its
  `EXECUTION_ALLOWED` row; if that pre-execution write fails, block the order.
- `audit_log.tool_call_id` is the correlation key between `pre_tool_call` and
  `post_tool_call`. Treat IDs as opaque strings.

## 6. Testing rules

- Every policy rule must have a unit test that proves both the pass and fail path.
- Minimum required unit coverage:
  - max gross buy notional (equal to limit, over limit)
  - max quantity (equal to limit, over limit)
  - symbol allowlist (case normalization, unknown symbol)
  - order-type allowlist
  - side allowlist
- Financial edge cases require dedicated tests:
  - booleans (`True`, `False`)
  - `NaN`, `Infinity`, `-Infinity`
  - negative and zero values
  - fractional shares
  - float input rejection
  - string, integer, and `Decimal` inputs
- Adapter tests must assert that Broker A and Broker B produce an identical
  `NormalizedOrder` for equivalent inputs.
- Hook tests must assert that a corrupt policy, missing argument, adapter error,
  and engine exception all return a block directive.
- Integration tests must assert:
  - a blocked order leaves `paper_ledger` unchanged
  - an allowed order writes exactly one ledger row
  - `audit_log` records `EXECUTION_BLOCKED` or `EXECUTION_ALLOWED` followed by
    `EXECUTION_SUCCEEDED` / `EXECUTION_FAILED` / `EXECUTION_OUTCOME_UNKNOWN`
- Use `pytest`. Do not require network access or real broker credentials.

## 7. Architecture and separation of concerns

- `domain/` — pure Python value objects and policy schema. No I/O, no Hermes
  imports, no logging side effects.
- `adapters/` — translation from broker-shaped arguments to `NormalizedOrder`.
- `services/` — orchestration and persistence (policy loading, engine, audit).
- `tools/` — Hermes tool schemas and handlers.
- `hooks/` — Hermes lifecycle wiring and fail-closed enforcement.
- Dependencies point inward: `hooks/tools -> services -> adapters/domain`.
  `domain` imports nothing from the other layers.
- Depend on abstractions (`BrokerAdapter`), not concrete broker modules.
- Keep functions small and side effects explicit. No global mutable state except
  the idempotent audit store and adapter registry.

## 8. Security boundaries

- The firewall protects only tools registered by this plugin:
  `paper_place_order_a` and `paper_place_order_b`.
- It does **not** protect arbitrary terminal commands, `curl`, direct broker SDK
  usage, other plugins' tools, or manual trades placed in a broker app. Document
  this honestly; never imply blanket protection.
- The plugin exposes no policy-editing tool. Operators edit the policy file.
- An agent with unrestricted shell access under the same OS user could modify
  the policy file. This is a documented limitation, not a feature.
- Do not add telemetry, analytics, or outbound HTTP.

## 9. Packaging and Hermes integration

These rules are not stylistic. Breaking them breaks installation, updates, or
the plugin manager's workspace.

- **The plugin root is not a Python distribution.** `pyproject.toml` holds
  tooling configuration only (pytest, coverage, ruff). Never add a
  `[project]` or `[build-system]` table: the Hermes plugin manager treats a
  directory with a `[project]` table as an installable uv workspace member
  named after the project, which collides with the plugin id
  (`trade-preflight`) and breaks `uv lock` and `hermes plugins enable` when
  more than one profile has the plugin enabled. Development dependencies live
  in `requirements-dev.txt`.
- **Import the implementation with relative imports.** The root `__init__.py`
  must use `from .src.trade_preflight...`. Hermes evicts plugin modules from
  `sys.modules` under the `hermes_plugins.<slug>` namespace only. A top-level
  `trade_preflight` package survives the eviction, so an updated plugin would
  keep running the previous version's code, and a second Hermes profile would
  reuse the first profile's modules.
- **Never commit `__pycache__`, `*.pyc`, binaries, or archives.** The catalog
  admission scanner refuses a plugin that ships unscannable payloads.
- **Declare capabilities truthfully.** `plugin.yaml` `provides_tools` /
  `provides_hooks` must match what `register(ctx)` registers, and the catalog
  entry's `capabilities:` block must match the manifest.

## 10. Definition of done

- [ ] `python -m compileall src` passes.
- [ ] `pytest` passes with no network access.
- [ ] `hermes plugins validate . --install-deps` passes.
- [ ] `hermes plugins doctor . --ci` passes.
- [ ] `plugin.yaml` `provides_tools` / `provides_hooks` match `register(ctx)`.
- [ ] The catalog draft in `plugin-catalog/` matches the manifest.
- [ ] No float literals in financial code paths.
- [ ] Every new policy rule has a unit test.
- [ ] Fail-closed behavior is covered by a test that injects an exception.
- [ ] README and ADR reflect the current behavior.
