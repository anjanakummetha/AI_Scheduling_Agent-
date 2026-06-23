#!/usr/bin/env bash
# Phase B — start Hermes + show checklist (Outlook send/write stay OFF)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo ""
echo "=== Lexi Phase B — Teams UAT launcher ==="
echo ""

echo "1) Verifying Teams + safety locks..."
.venv/bin/python scripts/verify_teams_connection.py || true
.venv/bin/python scripts/verify_read_only_deploy.py || exit 1

echo ""
echo "2) Hermes MCP config (merge if needed):"
.venv/bin/python scripts/setup_hermes_mcp.py | head -20

echo ""
echo "3) Start Hermes (Teams chat ingress):"
echo "   hermes gateway run --replace"
echo ""
echo "4) If local, tunnel Azure Bot → Hermes:"
echo "   ngrok http 3978"
echo "   Azure Bot → Messaging endpoint: https://<ngrok-host>/api/messages"
echo ""
echo "5) Optional — test proactive Teams DM:"
echo "   .venv/bin/python scripts/verify_teams_connection.py --live-ping"
echo ""
echo "6) Test prompts: docs/PHASE_B_TEAMS_TEST_PROMPTS.md"
echo ""
echo "Safety: LEXI_DRY_RUN + Kory read-only + no lexi@ sends (unchanged)."
echo ""
