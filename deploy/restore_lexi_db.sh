#!/usr/bin/env bash
# Restore Lexi's SQLite DB from a backup (plan Phase 4).
# Usage: restore_lexi_db.sh <backup-file> [target-db-path]
# Stops the worker, backs up the current DB, restores, restarts.
set -euo pipefail

SRC="${1:?usage: restore_lexi_db.sh <backup-file> [target-db]}"
APP_DIR="${LEXI_APP_DIR:-/opt/lexi}"
DB="${2:-${LEXI_DB_PATH:-${APP_DIR}/data/lexi.db}}"

[[ -f "${SRC}" ]] || { echo "Backup not found: ${SRC}"; exit 1; }

echo "==> Verifying backup integrity"
sqlite3 "${SRC}" "PRAGMA integrity_check;" | grep -q "^ok$" || { echo "Backup failed integrity check"; exit 1; }

echo "==> Stopping worker"
sudo systemctl stop lexi-hermes.service || true

if [[ -f "${DB}" ]]; then
  ts="$(date +%Y%m%d-%H%M%S)"
  cp -f "${DB}" "${DB}.pre-restore-${ts}"
  echo "==> Current DB saved to ${DB}.pre-restore-${ts}"
fi

echo "==> Restoring ${SRC} -> ${DB}"
cp -f "${SRC}" "${DB}"

echo "==> Restarting worker"
sudo systemctl start lexi-hermes.service
echo "==> Restore complete."
