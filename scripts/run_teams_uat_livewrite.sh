#!/usr/bin/env bash
# Live Teams UAT launcher — SANDBOX LIVE-WRITE posture (real writes, Kory protected).
#
# Real sends/holds EXECUTE, but:
#   - write connection = Lexi sandbox (ca_4BTJ6d0O8sSZ), re-asserted != Kory at runtime
#   - SANDBOX_EMAIL_LOOPBACK=true -> every send is redirected to lexi@ (no external recipient)
#   - recipient allowlist = your test addresses only
#   - Kory is NEVER CC'd; Kory's Outlook/Asana/HubSpot are never the write target
#   - approval still required; no autonomous send/execute
#
# Run it (detached) from the Claude prompt with:   ! bash scripts/run_teams_uat_livewrite.sh
set -euo pipefail
cd "$(dirname "$0")/.."

export PYTHONPATH="$PWD"
export LEXI_ENV=testing
export LEXI_DATABASE_PATH=data/lexi_test.db   # pin DB so gateway + injector share one store
export LEXI_DRY_RUN=false
export LEXI_WRITE_MODE=sandbox
export SANDBOX_EMAIL_LOOPBACK=true
export SANDBOX_MAILBOX_EMAIL=lexi@iconicfounders.com
export SANDBOX_COMPOSIO_CONNECTION_ID=ca_4BTJ6d0O8sSZ
export LEXI_KORY_SPACE_READ_ONLY=false
export LEXI_KORY_OUTBOUND_BLOCKED=false
export LEXI_CC_KORY_ENABLED=false
export LEXI_REQUIRE_KORY_APPROVAL=true
export LEXI_ALLOW_IMMEDIATE_SEND=false
export LEXI_AUTO_EXECUTE_ENABLED=false
export LEXI_TEAMS_ENABLED=true
export LEXI_TEAMS_TEXT_ONLY=false
export LEXI_SUPPRESS_TEAMS_PUSH=false
export LEXI_FORCE_TEAMS_PUSH=true
export LEXI_EMBED_WORKER=true
export LEXI_ORCHESTRATOR_ENABLED=true
export LEXI_LOCAL_MODE=true
export LEXI_ALLOWED_RECIPIENTS="anjana.kummetha@iconicfounders.com,lexi@iconicfounders.com"

mkdir -p logs
LOG="logs/gateway_livewrite.log"

echo "=== SAFETY PRE-FLIGHT (aborts if Kory not provably protected) ==="
.venv/bin/python scripts/uat/preflight_livewrite.py || { echo "PREFLIGHT FAILED — not starting gateway."; exit 1; }

echo "=== Starting Hermes gateway on :3978 (detached, live-write sandbox) ==="
nohup hermes gateway run --replace > "$LOG" 2>&1 &
GW_PID=$!
disown || true
sleep 3
echo "Gateway PID=$GW_PID  log=$LOG"
if lsof -nP -iTCP:3978 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "OK — gateway listening on :3978 in SANDBOX LIVE-WRITE mode."
else
  echo "WARNING — gateway not yet listening; check $LOG"
fi
