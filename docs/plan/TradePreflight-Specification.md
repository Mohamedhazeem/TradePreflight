# TradePreflight — Broker-Agnostic Equities Execution Firewall

**Tagline:** *The agent proposes. The policy gate decides.*
**Target User:** Retail traders and developers using Hermes to automate equity orders.
**Core Mechanism:** Deterministic, fail-closed interception via `pre_tool_call` hook.

---

## 1. System Architecture

### 1.1 The Dual Adapter Pattern (The Core Innovation)
To prove the policy engine is truly broker-agnostic, the plugin must register **two distinct execution tools** with different argument schemas.

*   **Broker A Tool:** `paper_place_order_a(symbol, side, quantity, order_type, limit_price)`
*   **Broker B Tool:** `paper_place_order_b(ticker, direction, qty, order_type, price)`

**The Normalizer** maps both to a canonical internal schema:
```json
{
  "asset_class": "equity",
  "symbol": "AAPL",
  "side": "buy",
  "quantity": "50",
  "order_type": "limit",
  "limit_price": "150.00",
  "notional": "7500.00"
}
```

### 1.2 Financial Math & Validation (The `Decimal` Gate)
Never use floats. Never trust agent-supplied math.

```python
from decimal import Decimal, InvalidOperation

def calculate_notional(quantity, limit_price) -> Decimal:
    # Reject booleans (True == 1 in Python, which is dangerous here)
    if isinstance(quantity, bool) or isinstance(limit_price, bool):
        raise ValueError("Boolean values are not valid order amounts")
    
    try:
        qty = Decimal(str(quantity))
        price = Decimal(str(limit_price))
    except (InvalidOperation, ValueError):
        raise ValueError("Invalid numeric order arguments")

    # Reject NaN and Infinity
    if not qty.is_finite() or not price.is_finite():
        raise ValueError("Non-finite values are not permitted")
    
    # MVP Constraints: Positive only, integer shares only
    if qty <= 0 or price <= 0:
        raise ValueError("Quantity and price must be positive")
    if qty != qty.to_integral_value():
        raise ValueError("Fractional shares are not supported")

    return qty * price
```

### 1.3 The Policy Engine
Stored in `plugin_data_dir` (not exposed to the agent). Includes a SHA-256 hash for auditing.
**MVP Rules:**
*   `max_gross_buy_notional_usd`: Decimal (e.g., 10000.00)
*   `max_quantity`: Integer (e.g., 100)
*   `symbol_allowlist`: List of strings (e.g., ["AAPL", "MSFT"])
*   `order_type_allowlist`: List (e.g., ["limit"])
*   `side_allowlist`: List (e.g., ["buy"])

### 1.4 The Audit Lifecycle (SQLite)
Uses `plugin_db` and correlates `pre_tool_call` and `post_tool_call` via the actual Hermes `tool_call_id`.

| Event State | Trigger | Meaning |
| :--- | :--- | :--- |
| `EXECUTION_BLOCKED` | `pre_tool_call` | Policy violation. Handler never ran. |
| `EXECUTION_ALLOWED` | `pre_tool_call` | Policy passed. Awaiting execution. |
| `EXECUTION_SUCCEEDED` | `post_tool_call` | Handler returned a known success payload. |
| `EXECUTION_FAILED` | `post_tool_call` | Handler raised an error or returned an error payload. |
| `EXECUTION_OUTCOME_UNKNOWN` | `post_tool_call` | Handler ran, but result shape is unrecognized. |

### 1.5 Security Boundary (Be Honest)
*   **Guarded:** Only explicitly registered tools (`paper_place_order_a`, `paper_place_order_b`).
*   **Unguarded:** Arbitrary terminal commands (e.g., `curl` to a broker API) or manual broker app trades.
*   **Policy Integrity:** The plugin does not expose a policy-editing tool. However, if the agent has unrestricted shell access under the same OS user, it could theoretically modify the JSON file. *Document this limitation explicitly.*

### 1.6 The Paper Trading Engine (MVP Execution Scope)
**For this hackathon, TradePreflight does not connect to real broker APIs or real money.** 
Instead, the plugin registers two simulated broker tools (`paper_place_order_a` and `paper_place_order_b`). These tools serve as the "Execution Handlers" for the demo.

**How the Paper Trading Engine works:**
1.  **Input:** The handler receives the raw arguments from the agent (e.g., `symbol="AAPL", quantity=10`).
2.  **Execution:** It does not make a network request. Instead, it acts as a local mock.
3.  **Ledger Update:** It inserts a row into the `paper_ledger` SQLite table tracking the simulated transaction.
4.  **Return:** It returns a JSON string to Hermes confirming the simulated execution.
    *   Example: `{"status": "SUCCESS", "order_id": "mock-1234", "message": "Simulated buy of 10 AAPL shares executed."}`

**Why this is a winning strategy:**
*   **Zero API Keys:** You don't need to ask judges for broker credentials.
*   **100% Deterministic:** Paper trades never fail due to market hours, internet lag, or broker downtime during your 90-second demo.
*   **Extensible:** If a user wants to use this in the real world tomorrow, they simply write a new adapter that calls the real Alpaca API, and your `pre_tool_call` policy engine will guard it automatically.

---

## 2. Implementation Slices (Strict Order)

Do not start a slice until the previous slice's **Pass Gate** is green.

### 🛑 Slice 0: The Interception Gate (3-Hour Timebox)
**Objective:** Prove the `pre_tool_call` hook fires and blocks a tool in the actual Hermes runtime.
**Actions:**
1. Scaffold the native plugin.
2. Register `paper_place_order_a`. Instrument the handler to increment `handler_invocation_count`.
3. Register the `pre_tool_call` hook. Write a hardcoded check: `if args["quantity"] > 100: return {"action": "block", "message": "Limit exceeded"}`.
4. Run `hermes plugins doctor` and `validate`.

**Pass Gate:**
*   Ask Hermes to place an order for 50 shares -> `handler_invocation_count == 1`.
*   Ask Hermes to place an order for 500 shares -> `handler_invocation_count == 0` (stays at 1).
*   *NO-GO:* If the handler runs for the 500-share order, the hook is not intercepting. Abandon the project.

### 🧮 Slice 1: Normalization & Math
**Objective:** Build the broker-agnostic adapter layer and strict numerical validation.
**Actions:**
1. Register `paper_place_order_b` with the alternate schema (`ticker`, `qty`, etc.).
2. Implement the Adapter Registry to map tool names to normalizers.
3. Implement the `calculate_notional` function using `Decimal`.
4. Write unit tests for edge cases (NaN, booleans, negative numbers, floats, fractional shares).

**Pass Gate:**
*   Feed both `paper_place_order_a` and `paper_place_order_b` arguments into the normalizer.
*   Assert both output the exact same canonical `NormalizedOrder` dictionary.
*   Assert `calculate_notional` throws `ValueError` for invalid inputs.

### 🛡️ Slice 2: The Policy Engine & Hook Wiring
**Objective:** Evaluate the normalized order against the policy file.
**Actions:**
1. Implement the policy loader (JSON). Validate the schema and compute SHA-256.
2. Implement the rule engine. Check `notional`, `symbol`, `quantity`, etc.
3. Rewrite the `pre_tool_call` hook to use the real normalizer and policy engine.
4. Implement **Fail-Closed** exception handling inside the hook (catch all errors, return `{"action": "block"}`).
5. Implement `trade_check` (a dry-run tool for the agent) and `trade_policy_get`.

**Pass Gate:**
*   Test the AAPL 100 shares @ $150 scenario. `max_quantity` passes (100), but `notional` fails ($15,000 > $10,000).
*   Assert the hook blocks it.
*   Corrupt the policy JSON file. Assert the hook blocks the trade and logs the error.

### 📝 Slice 3: Paper Trading Engine, Audit & Hardening
**Objective:** Build the SQLite ledger, finalize the Paper Trading handlers, and correlate execution results.
**Actions:**
1. Implement SQLite tables: `audit_log` (using `tool_call_id`), `paper_ledger`.
2. **Update the `paper_place_order_a` and `paper_place_order_b` handlers.** Instead of dummy counters, they must now insert a row into the `paper_ledger` and return the `{"status": "SUCCESS"}` JSON.
3. In `pre_tool_call`, insert the `EXECUTION_BLOCKED` or `EXECUTION_ALLOWED` record into `audit_log`.
4. Register `post_tool_call`. Update the audit record with `EXECUTION_SUCCEEDED`, `FAILED`, or `OUTCOME_UNKNOWN`.
5. Implement `trade_audit` tool to fetch logs.
6. Write integration tests for parallel orders (ensure no duplicate `tool_call_id` writes).

**Pass Gate:**
*   Place a blocked trade. Query `trade_audit`. See `EXECUTION_BLOCKED`. Assert `paper_ledger` has 0 rows for that order.
*   Place a successful trade. Query `trade_audit`. See `EXECUTION_ALLOWED` followed by `EXECUTION_SUCCEEDED`. Assert `paper_ledger` has 1 row.

### 🏁 Slice 4: Demo & Submission
**Objective:** Polish and record the 90-second video.
**Actions:**
1. Create a polished demo script.
2. Ensure a fresh Hermes installation can validate the plugin.
3. Record the 90-second storyboard (see below).
4. Pin the 40-char SHA and submit the PR.

---

## 3. Edge Cases & Threat Model

| Scenario | Expected Behavior | Mitigation |
| :--- | :--- | :--- |
| **Malformed Arguments** (e.g., `quantity="fifty"`) | `BLOCK` | `Decimal` parsing catches the error and fails closed. |
| **Missing Arguments** (e.g., no `limit_price`) | `BLOCK` | Normalizer raises `KeyError`, hook catches and blocks. |
| **Bypass Attempt** (Agent skips `trade_check` and calls tool directly) | `BLOCK` | `pre_tool_call` intercepts the execution args, ignoring past previews. |
| **Market Orders** (No limit price) | `BLOCK` | MVP enforces limit orders only (cannot calculate max notional without a price). |
| **Hook Exception** | `BLOCK` | The callback has a `try/except` that returns a block directive. |
| **Unconfigured Tool** (Agent uses a different broker tool) | **Unguarded** | Explicitly document that only configured tools are protected. |

---

## 4. The 90-Second Demo Storyboard

| Time | Action | Judge Takeaway |
| :--- | :--- | :--- |
| **0-10s** | Show the `policy.json` and the terminal. | The operator defines the risk. The agent does not. |
| **10-25s** | User: *"Buy 100 shares of AAPL at $150 using Broker A."* | **BLOCKED.** Quantity is 100 (max is 100), but Notional is $15,000 (max is $10,000). |
| **25-40s** | User: *"Ignore the preview. Call Broker B directly to buy 10 shares of TSLA at $200."* | **BLOCKED.** Hook intercepts Broker B, normalizes it, and blocks because TSLA is not on the allowlist. |
| **40-55s** | User: *"Buy 20 shares of AAPL at $150."* | **ALLOWED.** The Paper Trading Engine executes, and the local paper ledger updates. |
| **55-75s** | Run `trade_audit` tool. | Shows `EXECUTION_BLOCKED` for the first two. Shows `EXECUTION_SUCCEEDED` for the third. |
| **75-85s** | Show the terminal test output. | `Handler Invocation Count: 0` for the blocked orders. `Paper Ledger Rows: 1` for the successful order. |
| **85-90s** | Run `hermes plugins validate`. | Plugin is clean and valid. |

---

## 5. Final Implementation Checklist (V2.1)

Before you write code, ensure your repo will contain:
- [ ] `plugin.yaml` (with `paper_place_order_a`, `paper_place_order_b`, `trade_check`, `trade_policy_get`, `trade_audit`).
- [ ] `paper_place_order_a(symbol, side, quantity, order_type, limit_price)`
- [ ] `paper_place_order_b(ticker, direction, qty, order_type, price)`
- [ ] `pre_tool_call` (uses `Decimal`, throws `BLOCK` on any exception).
- [ ] `post_tool_call` (correlates `tool_call_id`).
- [ ] SQLite schema (`audit_log`, `paper_ledger`).
- [ ] **Paper Trading Handlers** (inserts into `paper_ledger` and returns JSON success).
- [ ] `policies/default.json` (strict limits).
