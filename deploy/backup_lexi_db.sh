#!/usr/bin/env bash
# SQLite backup for Lexi (plan Phase 4). Uses the online `.backup` command so it
# is consistent even while the worker is running. Keeps 24 hourly + 14 daily
# copies, and (optionally) pushes the daily copy off-VPS via rclone.
set -euo pipefail

APP_DIR="${LEXI_APP_DIR:-/opt/lexi}"
DB="${LEXI_DB_PATH:-${APP_DIR}/data/lexi.db}"
BK="${LEXI_BACKUP_DIR:-${APP_DIR}/backups}"
RCLONE_REMOTE="${LEXI_BACKUP_RCLONE_REMOTE:-}"   # e.g. "myremote:lexi-backups" (optional)

mkdir -p "${BK}"
[[ -f "${DB}" ]] || { echo "No DB at ${DB}"; exit 1; }

hour="$(date +%H)"
day="$(date +%Y%m%d)"
hourly="${BK}/lexi-hourly-${hour}.db"     # 24 rotating (overwritten each day)
daily="${BK}/lexi-daily-${day}.db"        # 14 rotating (pruned below)

sqlite3 "${DB}" ".backup '${hourly}'"
cp -f "${hourly}" "${daily}"

# Prune daily backups older than 14 days.
find "${BK}" -name 'lexi-daily-*.db' -mtime +14 -delete 2>/dev/null || true

# Optional off-VPS copy of the daily backup.
if [[ -n "${RCLONE_REMOTE}" ]] && command -v rclone >/dev/null 2>&1; then
  rclone copy "${daily}" "${RCLONE_REMOTE}" --quiet || echo "WARN: rclone push failed"
fi

echo "Backup OK: ${daily} ($(du -h "${daily}" | cut -f1))"
