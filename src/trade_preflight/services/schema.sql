-- TradePreflight SQLite schema.
--
-- Decimal values are stored as TEXT. SQLite's INTEGER/REAL affinity would
-- silently coerce numeric-looking strings to binary floats, which is exactly
-- what this project forbids.
--
-- All statements are idempotent. The schema is executed through
-- ``plugins.plugin_storage.plugin_db("trade-preflight")``.

CREATE TABLE IF NOT EXISTS audit_log (
    tool_call_id TEXT PRIMARY KEY,
    timestamp    TEXT NOT NULL,
    tool_name    TEXT NOT NULL,
    order_json   TEXT NOT NULL,
    decision     TEXT NOT NULL CHECK (
        decision IN (
            'EXECUTION_BLOCKED',
            'EXECUTION_ALLOWED',
            'EXECUTION_SUCCEEDED',
            'EXECUTION_FAILED',
            'EXECUTION_OUTCOME_UNKNOWN'
        )
    ),
    reason       TEXT NOT NULL,
    policy_hash  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp
    ON audit_log (timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_audit_log_tool_name
    ON audit_log (tool_name);

CREATE TABLE IF NOT EXISTS paper_ledger (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol    TEXT NOT NULL,
    side      TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    quantity  TEXT NOT NULL,
    price     TEXT NOT NULL,
    notional  TEXT NOT NULL,
    timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_paper_ledger_timestamp
    ON paper_ledger (timestamp DESC);
