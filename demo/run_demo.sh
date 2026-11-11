#!/usr/bin/env bash
# TradePreflight demo launcher.
#
# Two halves, one command:
#
#   1. the offline story - the real plugin code driving the real gate against
#      a temporary workspace (no Hermes, no network, no credentials);
#   2. the live half - the exact prompts to paste into Hermes, where the same
#      gate fires on a real agent conversation.
#
# Usage:
#   ./demo/run_demo.sh            # offline story, then the Hermes prompts
#   ./demo/run_demo.sh --quiet    # offline story without the commentary
#
# Requirements: Python 3.10+. The live half additionally needs the plugin
# enabled in Hermes (hermes plugins enable trade-preflight).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON="${PYTHON:-python3}"
if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
    PYTHON="$REPO_ROOT/.venv/bin/python"
fi

echo "==> Running the offline story (real plugin code, temporary workspace)"
"$PYTHON" demo/story.py "$@"

echo
echo "==> The live half: the same gate, inside Hermes"
echo
echo "    Operator policy : <hermes-home>/plugin-data/trade-preflight/policy.json"
echo "                      (seeded on first run from the shipped policies/default.json)"
echo "    Plugin status   :"
if command -v hermes >/dev/null 2>&1; then
    # Capture first: `hermes plugins list | grep -q` under `pipefail` reports
    # SIGPIPE on the upstream command and would look like "not installed".
    PLUGIN_LIST="$(hermes plugins list 2>/dev/null || true)"
    if printf '%s\n' "$PLUGIN_LIST" | grep -qi "trade-preflight"; then
        printf '%s\n' "$PLUGIN_LIST" | grep -i "trade-preflight" | sed 's/^/      /'
    else
        echo "      trade-preflight is not installed in this profile - run:"
        echo "        hermes plugins enable trade-preflight"
    fi
else
    echo "      the hermes CLI is not on PATH - the live half needs Hermes installed"
fi
echo
echo "    Paste these prompts into Hermes, in order:"
echo
echo "  1) What am I allowed to trade?"
echo "     Use trade_policy_get and tell me the notional cap, the quantity cap"
echo "     and the allowlists you are enforcing."
echo
echo "  2) A compliant order"
echo "     Use the paper_place_order_a tool to buy 20 shares of AAPL as a limit"
echo "     order at 150.00."
echo
echo "  3) The notional cap bites"
echo "     Now buy 100 shares of AAPL as a limit order at 150.00."
echo
echo "  4) A different broker, the same policy"
echo "     Use the paper_place_order_b tool to buy 10 shares of TSLA as a limit"
echo "     order at 200.00."
echo
echo "  5) The evidence"
echo "     Show me the TradePreflight audit trail for the last 10 orders."
echo
echo "==> The full 90-second shot list is in demo/STORYBOARD.md"
