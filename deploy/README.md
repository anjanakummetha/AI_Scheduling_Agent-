# Lexi — deployment runbook (Hostinger KVM2)

Host `srv1686061.hstgr.cloud`, user `lexi`, app dir `/opt/lexi`, service `lexi-hermes`.

The CEO Executive Dashboard deploys alongside the agent on the same VPS (see
"Joint deploy" at the bottom). Topology:

```
Internet → Caddy (:443 auto-TLS)
  ├ dash.<domain>  → 127.0.0.1:3000  ceo-dashboard.service (Next standalone, user ceo)
  └ agent.<domain>/webhook* → 127.0.0.1:8780  lexi-hermes.service
Localhost only: dashboard —bearer→ 127.0.0.1:8081  lexi-api.service (read-only /api/v1)
```

## First deploy / update

```bash
# as the lexi user, from /opt/lexi (a git checkout)
git pull
cp .env.production.example .env.production   # first time only; fill in real values
bash deploy/install.sh
```

`install.sh` is idempotent: it creates the venv, installs **pinned** deps
(`requirements.txt`), initializes the DB, validates the environment (fails on a
broken/incoherent config), installs the systemd units, and (re)starts everything.

## Services installed

| Unit | Purpose |
|---|---|
| `lexi-hermes.service` | The worker (orchestrator + Composio webhook). `Restart=always`, `MemoryMax=1G`. |
| `lexi-watchdog.timer` → `.service` | Every 5 min: curls `/api/health`; on unhealthy → Teams alert + restart. |
| `lexi-backup.timer` → `.service` | Hourly SQLite `.backup` (24 hourly + 14 daily copies; optional rclone off-VPS). |

## Health

```bash
curl -s http://127.0.0.1:8780/api/health | python3 -m json.tool
```
Returns `200 ok` when healthy; `503 degraded` if the DB isn't writable or the
orchestrator heartbeat is stale (> 5 min). Fields include `heartbeat_age_seconds`,
`db_writable`, and `composio_budget` (month-to-date vs the 200k/mo cap).

## Backups & restore

- Backups land in `/opt/lexi/backups/`. Set `LEXI_BACKUP_RCLONE_REMOTE` for off-VPS copies.
- Restore (stops worker, snapshots current DB, restores, restarts):
  ```bash
  bash deploy/restore_lexi_db.sh /opt/lexi/backups/lexi-daily-YYYYMMDD.db
  ```

## Logs

- Journal: `journalctl -u lexi-hermes -f`
- Rotating file: `/opt/lexi/logs/lexi.log` (20 MB × 5).
- Decisions/audit: `logs/decisions.log` + the `audit_log` table.

## Common ops

```bash
sudo systemctl status  lexi-hermes
sudo systemctl restart lexi-hermes
sudo systemctl stop    lexi-hermes    # e.g. before running local Mac tests
journalctl -u lexi-hermes -n 100 --no-pager
```

## Go-live (enablement ladder — see plan Phase 6)

`.env.production` ships with gates CLOSED. Advance ONE rung at a time, soaking
between: calendar holds → drafts-only → approved sends. Never flip multiple gates
at once. The boot banner (`journalctl`) prints the effective posture each start.

## Joint deploy — CEO Executive Dashboard

The dashboard is a Next.js standalone app (read-only; it only reads Outlook/Asana
via Composio and the Lexi `/api/v1`, never writes). Deploy alongside the agent:

1. **Agent side** — `install.sh` already installs `lexi-api.service` (read-only
   `/api/v1` on `127.0.0.1:8081`). Set `LEXI_API_ENABLED=true` and a strong
   `LEXI_API_TOKEN` in `/opt/lexi/.env.production` (the dashboard uses the same token).
2. **Node 20** — install via NodeSource (`engines: >=20.9`).
3. **Build off-box, ship the bundle** (keeps the VPS lean):
   ```bash
   cd CEO_Executive_Dashboard--main && npm ci && npm run build
   rsync -a .next/standalone/ ceo@host:/opt/ceo-dashboard/
   rsync -a .next/static/     ceo@host:/opt/ceo-dashboard/.next/static/
   rsync -a public/           ceo@host:/opt/ceo-dashboard/public/
   ```
4. **Env** — `cp .env.production.example /opt/ceo-dashboard/.env.production`, fill
   `AUTH_SECRET`, `DASHBOARD_PASSWORD`, `COMPOSIO_API_KEY`, `ANTHROPIC_API_KEY`,
   `LEXI_API_TOKEN`. Set `DASHBOARD_DATA_DIR=/var/lib/ceo-dashboard` and
   `mkdir -p /var/lib/ceo-dashboard && chown ceo:ceo /var/lib/ceo-dashboard`.
5. **Services** — `cp deploy/ceo-dashboard.service /etc/systemd/system/`,
   `systemctl enable --now ceo-dashboard.service`. Install Caddy and use
   `deploy/Caddyfile` (edit the hostnames). The `lexi-api` service is **never**
   proxied — localhost only.

**Read-only tests before deploy** (in `CEO_Executive_Dashboard--main`):
`npm run build`, `npm run lint`, `npm run test:readonly`, `npm run test:no-write-slugs`,
and the `probe:asana` / `probe:outlook` / `probe:linkedin` read-only probes.

**Model key swap**: `HERMES_INFERENCE_MODEL` and `ANTHROPIC_API_KEY` are one-line
env changes on the dashboard; `restart ceo-dashboard.service` to apply.
