# Lexi — deployment runbook (Hostinger KVM2)

Host `srv1686061.hstgr.cloud`, user `lexi`, app dir `/opt/lexi`, service `lexi-hermes`.

The CEO Executive Dashboard deploys alongside the agent on the same VPS (see
"Joint deploy" at the bottom). Topology:

Single host `srv1686061.hstgr.cloud`, path-routed by Caddy (no separate domains):

```
Internet → Caddy (:443 auto-TLS on srv1686061.hstgr.cloud)
  ├ /api/messages   → 127.0.0.1:3978  lexi-gateway.service (Hermes Teams gateway ← Azure Bot)
  ├ /webhooks/*     → 127.0.0.1:8780  lexi-hermes.service  (worker + Composio webhook ingress)
  └ everything else → 127.0.0.1:3000  ceo-dashboard.service (Next standalone, behind login)
Localhost only: dashboard —bearer→ 127.0.0.1:8081  lexi-api.service (read-only /api/v1)
```

> **Teams needs TWO processes.** `lexi-hermes.service` (despite the name) runs the
> email worker on :8780. The Teams approval cards flow through `lexi-gateway.service`
> (`hermes gateway run`, :3978, `/api/messages`) — the Azure Bot endpoint. `hermes`
> is an external CLI (not a pip dep); see "Hermes Teams gateway" below.

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
| `lexi-hermes.service` | The worker (orchestrator + Composio webhook on :8780). `Restart=always`, `MemoryMax=1G`. |
| `lexi-gateway.service` | Hermes Teams gateway (`hermes gateway run`, :3978, `/api/messages`). Installed + enabled only if the `hermes` CLI is present. |
| `lexi-api.service` | Read-only `/api/v1` on `127.0.0.1:8081` for the dashboard (never proxied). |
| `lexi-watchdog.timer` → `.service` | Every 5 min: curls `/api/health`; on unhealthy → Teams alert + restart. |
| `lexi-backup.timer` → `.service` | Hourly SQLite `.backup` (24 hourly + 14 daily copies; optional rclone off-VPS). |

## Hermes Teams gateway (`lexi-gateway.service`)

`hermes` is an **external CLI**, not in `requirements.txt`. `install.sh` installs and
enables `lexi-gateway.service` **only if `hermes` is on PATH**; otherwise it skips it and
prints a warning (Teams won't work until you wire it up).

First-deploy setup:

1. Install the `hermes` CLI (or run the Hermes upstream Docker `gateway` service instead
   and leave `lexi-gateway.service` disabled).
2. `.venv/bin/python scripts/setup_hermes_mcp.py` prints the `mcp.servers.lexi-scheduling`
   block — **merge it into `~/.hermes/config.yaml`** (stdio entry → this repo's
   `hermes_mcp_server.py`, `PYTHONPATH=/opt/lexi`). Do **not** add the Composio MCP catalog.
3. Add `platforms.teams` (`enabled: true`, `port: 3978`) to `~/.hermes/config.yaml`.
4. Create `~/.hermes/.env`: `TEAMS_CLIENT_ID`, `TEAMS_CLIENT_SECRET`, `TEAMS_TENANT_ID`,
   `TEAMS_ALLOWED_USERS` (Kory's AAD object id), `ANTHROPIC_API_KEY`, `TEAMS_PORT=3978`.
5. `sudo systemctl enable --now lexi-gateway.service` (install.sh does this when `hermes` exists).

## Deploy-day external re-points (manual, one-time)

Two endpoints live outside this repo and must be pointed at the VPS after Caddy is up:

- **Azure Bot** messaging endpoint → `https://srv1686061.hstgr.cloud/api/messages`
  (Azure Portal → Bot → Configuration). Replaces the ngrok-era URL.
- **Composio** Outlook trigger webhook → `https://srv1686061.hstgr.cloud/webhooks/composio`
  (must equal `LEXI_WEBHOOK_PUBLIC_URL` in `.env.production`).

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

## Post-cutover: rebuild Kory's voice profile

`data/kory_voice_profile.json` (the "write like Kory" hints for drafting) is currently
built from a **seeded/demo Outlook mailbox** — the sent-mail samples are synthetic. Once
`KORY_COMPOSIO_CONNECTION_ID` points at Kory's **real** production Outlook, rebuild it
(read-only, no writes):

```bash
LEXI_ENV=production .venv/bin/python -c "from app.llm.kory_voice import rebuild_voice_profile; rebuild_voice_profile()"
```

Until then, draft voice-matching is degraded (generic), not wrong — safe to launch, worth
doing before enabling approved sends (Phase 5B).

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
   `deploy/Caddyfile` as-is (single host `srv1686061.hstgr.cloud`, already baked in;
   the dashboard is the catch-all route). The `lexi-api` service is **never**
   proxied — localhost only.

**Read-only tests before deploy** (in `CEO_Executive_Dashboard--main`):
`npm run build`, `npm run lint`, `npm run test:readonly`, `npm run test:no-write-slugs`,
and the `probe:asana` / `probe:outlook` / `probe:linkedin` read-only probes.

**Model key swap**: `HERMES_INFERENCE_MODEL` and `ANTHROPIC_API_KEY` are one-line
env changes on the dashboard; `restart ceo-dashboard.service` to apply.
