#!/usr/bin/env bash
# Start local UAT stack: Hermes (Teams + worker) + Kory inbox listener.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo ""
echo "=== Lexi UAT — start services ==="
echo ""

.venv/bin/python scripts/init_lexi_db.py
.venv/bin/python scripts/verify_local_mac.py || exit 1

mkdir -p logs

if lsof -i :3978 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "[ok] Hermes already listening on :3978"
else
  echo "[start] Hermes gateway (Teams + Lexi worker + MCP) → logs/hermes_gateway.log"
  nohup hermes gateway run --replace >> logs/hermes_gateway.log 2>&1 &
  echo $! > logs/hermes_gateway.pid
  sleep 3
fi

if pgrep -f "listen_outlook_local.py" >/dev/null 2>&1; then
  echo "[ok] listen_outlook_local.py already running"
else
  echo "[start] Kory inbox listener → logs/listen_outlook.log"
  nohup .venv/bin/python scripts/listen_outlook_local.py >> logs/listen_outlook.log 2>&1 &
  echo $! > logs/listen_outlook.pid
  sleep 2
fi

echo ""
echo "=== Runtime (expect worker_running=true in status) ==="
.venv/bin/python -c "
from app.assistant.actions import get_lexi_system_status
s = get_lexi_system_status()
print('  write_mode:', s.get('lexi_write_mode'))
print('  dry_run:', s.get('lexi_dry_run'))
print('  loopback:', s.get('sandbox_email_loopback'))
print('  worker_running:', s.get('ingress', {}).get('worker_running'))
print('  db:', s.get('note', '')[:80])
"

echo ""
echo "=== You still need (if testing Teams on this Mac) ==="
echo "  ngrok http 3978"
echo "  Azure Bot messaging endpoint → https://<ngrok>/api/messages"
echo "  Stop VPS: ssh lexi@2.24.111.64 'sudo systemctl stop lexi-hermes'"
echo ""
echo "=== Test emails ==="
echo "  Step 1 (you = prospect): your email → Kory only (no CC Lexi), subject must include TEST"
echo "  Step 2 (Kory): reply on thread, CC lexi@iconicfounders.com + 'looping in Lexi'"
echo ""
echo "Logs: tail -f logs/hermes_gateway.log logs/listen_outlook.log"
echo ""
