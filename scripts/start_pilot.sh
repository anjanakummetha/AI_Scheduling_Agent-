#!/usr/bin/env bash
# Start Lexi pilot locally (Hermes-only Teams).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== Lexi pilot — start ==="
echo "1) Hermes gateway (Teams :3978) — run in this terminal or another:"
echo "     hermes gateway run --replace"
echo ""
echo "2) Lexi inbox worker (polls Kory) — required for email even before Teams chat:"
echo "     .venv/bin/python -m app.worker"
echo ""
echo "3) ngrok (you run manually):  ngrok http 3978"
echo "   → Azure Bot messaging URL: https://<ngrok-host>/api/messages"
echo ""
echo "Bootstrap checks:  .venv/bin/python scripts/bootstrap_pilot.py"
echo ""

if [[ "${1:-}" == "--worker-only" ]]; then
  exec .venv/bin/python -m app.worker
fi

if command -v hermes >/dev/null 2>&1; then
  echo "Starting Hermes gateway..."
  exec hermes gateway run --replace
fi

echo "hermes not found in PATH. Start worker only:"
exec .venv/bin/python -m app.worker
