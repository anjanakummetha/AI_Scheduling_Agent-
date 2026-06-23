# Local Demo Runbook

## Verified Configuration

- Hermes gateway: `provider: anthropic` in `~/.hermes/config.yaml` (e.g. `claude-opus-4-7`).
- Lexi pipeline: `ANTHROPIC_API_KEY` in `.env` or `~/.hermes/.env` → `https://api.anthropic.com/v1` (OpenAI-compatible SDK).
- Composio: `KORY_COMPOSIO_CONNECTION_ID` + `COMPOSIO_ENTITY_ID` for Kory's Outlook.

## Run The Dashboard

```bash
./venv/bin/uvicorn app.main:app --reload
```

Open:

```text
http://127.0.0.1:8000
```

## Current Safe Test

Use **Create Demo Email** in the dashboard to test:

1. Local email/proposal creation.
2. Hermes structured proposal generation.
3. Rule validation.
4. Separate approval buttons.
5. Audit logging.

Mock dashboard emails are blocked from creating real Outlook events or sending mail.

## Real Outlook Test Path

1. Start dashboard locally.
2. Expose FastAPI with ngrok:

```bash
ngrok http 8000
```

3. Register the Composio webhook URL:

```text
https://YOUR-NGROK-DOMAIN/webhooks/composio
```

4. Enable the `OUTLOOK_MESSAGE_TRIGGER` for the connected Outlook account.
5. Send a scheduling email to the demo Outlook account.
6. Review the generated proposal in the dashboard.
7. Use separate buttons:
   - **Approve Email Only**
   - **Approve Calendar Only**
   - **Approve All**
   - **Reject**

## Safety Rule

All existing Outlook calendar events are treated as conflicts. If the proposed slot overlaps a busy event, the app records a failed calendar execution and does not create the new event.

## Local Fallback Without Ngrok

If ngrok is not installed, run the dashboard and the Composio SDK listener in
two terminals:

```bash
./venv/bin/uvicorn app.main:app --reload
```

```bash
./venv/bin/python scripts/ensure_outlook_trigger.py
./venv/bin/python scripts/listen_outlook_local.py
```

Then send a scheduling email to the connected demo Outlook account. The listener
will process the Outlook trigger and create a pending approval in the dashboard.
