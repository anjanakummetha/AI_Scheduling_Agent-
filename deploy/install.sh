#!/usr/bin/env bash
# Idempotent Lexi install/update for the Hostinger VPS (plan Phase 4).
# Run as a user with sudo, from the repo checkout at /opt/lexi.
set -euo pipefail

APP_DIR="${LEXI_APP_DIR:-/opt/lexi}"
PY="${APP_DIR}/.venv/bin/python"

echo "==> Lexi install/update in ${APP_DIR}"
cd "${APP_DIR}"

# 1. Virtualenv + pinned deps
if [[ ! -x "${PY}" ]]; then
  echo "==> Creating virtualenv"
  python3 -m venv "${APP_DIR}/.venv"
fi
echo "==> Installing pinned dependencies"
"${APP_DIR}/.venv/bin/pip" install --upgrade pip >/dev/null
"${APP_DIR}/.venv/bin/pip" install -r requirements.txt

# 2. Database schema (safe to re-run — CREATE TABLE IF NOT EXISTS)
echo "==> Initializing/verifying database"
"${PY}" scripts/init_lexi_db.py

# 3. Config sanity — refuse to proceed on a broken/incoherent env
echo "==> Validating environment"
LEXI_ENV=production "${PY}" -c "import app.config as c; print('safety posture:', c.safety_posture_summary())"

# 4. systemd units
echo "==> Installing systemd units"
sudo cp deploy/lexi-hermes.service   /etc/systemd/system/lexi-hermes.service
sudo cp deploy/lexi-api.service      /etc/systemd/system/lexi-api.service
sudo cp deploy/lexi-watchdog.service /etc/systemd/system/lexi-watchdog.service
sudo cp deploy/lexi-watchdog.timer   /etc/systemd/system/lexi-watchdog.timer
sudo cp deploy/lexi-backup.service   /etc/systemd/system/lexi-backup.service
sudo cp deploy/lexi-backup.timer     /etc/systemd/system/lexi-backup.timer
sudo systemctl daemon-reload

echo "==> Enabling + (re)starting services"
sudo systemctl enable --now lexi-hermes.service
sudo systemctl enable --now lexi-api.service     # read-only /api/v1 for the dashboard
sudo systemctl enable --now lexi-watchdog.timer
sudo systemctl enable --now lexi-backup.timer
sudo systemctl restart lexi-hermes.service
sudo systemctl restart lexi-api.service

echo "==> Done. Status:"
sudo systemctl --no-pager status lexi-hermes.service | head -12
echo "Health: curl -s http://127.0.0.1:${LEXI_WEBHOOK_PORT:-8780}/api/health"
