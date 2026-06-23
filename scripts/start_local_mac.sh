#!/usr/bin/env bash
# Start local Mac testing against Kory's live inbox (approval-gated).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo ""
echo "=== Lexi — local Mac testing ==="
echo ""

if ! grep -q '^LEXI_LOCAL_MODE=true' .env 2>/dev/null; then
  echo "WARN: LEXI_LOCAL_MODE is not true in .env — add it before local testing."
fi

echo "1) Initialize local database (isolated from VPS)..."
.venv/bin/python scripts/init_lexi_db.py

echo ""
echo "2) Safety gate..."
.venv/bin/python scripts/verify_local_mac.py || exit 1

echo ""
echo "3) Hermes MCP path (should point to this project):"
.venv/bin/python scripts/setup_hermes_mcp.py | head -12

echo ""
echo "=== Open 3 terminals ==="
echo ""
echo "  A) Hermes + Lexi worker:"
echo "     cd \"$ROOT\" && hermes gateway run --replace"
echo ""
echo "  B) Teams tunnel (point Azure Bot messaging endpoint here):"
echo "     ngrok http 3978"
echo "     → https://<ngrok-host>/api/messages"
echo ""
echo "  C) Inbound email listener (Kory inbox → local orchestrator):"
echo "     cd \"$ROOT\" && .venv/bin/python scripts/listen_outlook_local.py"
echo ""
echo "=== Testing rules ==="
echo "  • From: anjana.kummetha@iconicfounders.com"
echo "  • Subject: must include TEST"
echo "  • To: Kory's inbox"
echo "  • All sends/holds: Kory approves in Teams first"
echo "  • Stop VPS first: ssh lexi@2.24.111.64 'sudo systemctl stop lexi-hermes'"
echo ""
echo "Full runbook: docs/LOCAL_MAC_TESTING.md"
echo ""
