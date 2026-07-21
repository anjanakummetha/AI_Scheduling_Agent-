#!/usr/bin/env bash
# Live Teams UAT launcher — SAFE posture.
#
# Sends are DRY-RUN (nothing real leaves any mailbox); Teams cards are pushed so
# the approval UX can be exercised; Kory's Outlook/calendar stay read-only; Kory
# is never CC'd; the recipient allowlist is active; and only emails whose SUBJECT
# contains "TEST" are processed by the worker.
#
# Usage:
#   1) Terminal A:  bash scripts/run_teams_uat.sh
#   2) Terminal B:  ngrok http 3978        (then copy the https URL)
#   3) Azure Bot → Configuration → Messaging endpoint = https://<ngrok>/api/messages → Apply
#   4) Message Lexi in Teams.
set -euo pipefail
cd "$(dirname "$0")/.."

export LEXI_ENV=testing
export LEXI_DRY_RUN=true                 # no real sends — everything simulated
export LEXI_KORY_SPACE_READ_ONLY=true    # never write Kory's Outlook/calendar
export LEXI_KORY_OUTBOUND_BLOCKED=true
export LEXI_CC_KORY_ENABLED=false        # do not CC Kory during testing
export LEXI_TEAMS_ENABLED=true           # Teams on
export LEXI_SUPPRESS_TEAMS_PUSH=false
export LEXI_FORCE_TEAMS_PUSH=true        # push cards to Teams despite dry-run (UAT only)
export LEXI_EMBED_WORKER=true
export LEXI_ORCHESTRATOR_ENABLED=true
export LEXI_LOCAL_MODE=true              # only process emails with TEST in the subject
export LEXI_ALLOWED_RECIPIENTS="anjanakummetha@gmail.com,anjana.kummetha@iconicfounders.com,lexi@iconicfounders.com"

echo "=== Lexi Teams UAT posture ==="
.venv/bin/python -c "
from app.config import settings
from app.safety.approval_gate import kory_approves_all, auto_execute_allowed, immediate_send_allowed
from app.safety.outbound_guard import teams_push_allowed
assert settings.lexi_dry_run and settings.lexi_kory_space_read_only and not settings.cc_kory_enabled
assert kory_approves_all() and not auto_execute_allowed() and not immediate_send_allowed()
assert teams_push_allowed(), 'teams push should be allowed for UAT'
print('dry_run=%s cc_kory=%s kory_read_only=%s teams_push=%s local_mode(TEST-only)=on' % (
    settings.lexi_dry_run, settings.cc_kory_enabled, settings.lexi_kory_space_read_only, teams_push_allowed()))
print('SAFE: no real sends, no Kory changes, no Kory CC.')
"
echo "=== Starting Hermes gateway on :3978 (Ctrl-C to stop) ==="
exec hermes gateway run --replace
