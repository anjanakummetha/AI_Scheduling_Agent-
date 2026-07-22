#!/usr/bin/env bash
# Lexi watchdog (plan Phase 4). Runs every few minutes via lexi-watchdog.timer.
# If /api/health is unreachable or returns non-200 (degraded: DB down or the
# orchestrator heartbeat is stale), it alerts Kory in Teams and restarts the worker.
set -uo pipefail

APP_DIR="${LEXI_APP_DIR:-/opt/lexi}"
PORT="${LEXI_WEBHOOK_PORT:-8780}"
URL="http://127.0.0.1:${PORT}/api/health"
PY="${APP_DIR}/.venv/bin/python"

code="$(curl -s -o /tmp/lexi_health.json -w '%{http_code}' --max-time 10 "${URL}" || echo 000)"

if [[ "${code}" == "200" ]]; then
  exit 0
fi

reason="health ${code}"
[[ -s /tmp/lexi_health.json ]] && reason="${reason} — $(head -c 300 /tmp/lexi_health.json)"
echo "$(date -Is) watchdog: unhealthy (${reason}); restarting lexi-hermes" >&2

# Alert Kory (best-effort) then restart.
( cd "${APP_DIR}" && LEXI_ENV=production "${PY}" -m app.ops.health_alert \
    "worker unhealthy (${code}); restarting" ) || true
sudo systemctl restart lexi-hermes.service || systemctl restart lexi-hermes.service || true
