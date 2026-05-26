# Kory's AI Scheduling Agent

Phase 1 — Kory approves all actions before execution.

## Files

| File | Purpose |
|---|---|
| `rules.py` | All of Kory's scheduling rules — edit this to adjust any rule |
| `prompts.py` | Builds the system prompt from rules — feeds rules to Hermes |
| `agent.py` | Main agent — listens for emails, proposes actions, waits for approval |
| `setup.py` | Run once to register the Outlook email trigger with Composio |
| `.env` | Your API keys and config (create from `.env.example`) |
| `logs/decisions.log` | Full log of every decision the agent makes |

---

## Setup (Do This Once)

### 1. Install dependencies
```bash
cd /Users/anjanakummetha/IEP_Project/agent
pip install -r requirements.txt
```

### 2. Create your .env file
```bash
cp .env.example .env
```
Then open `.env` and fill in:
- `COMPOSIO_API_KEY` — from your Composio dashboard → Settings → API Keys
- `COMPOSIO_USER_ID` — the user ID you used when connecting Microsoft 365

### 3. Set up Hermes (choose one)

**Option A — Ollama (free, local):**
```bash
# Install Ollama from https://ollama.com, then:
ollama pull hermes3
# Leave LLM_BASE_URL=http://localhost:11434/v1 in .env
```

**Option B — Together AI (cloud, easiest):**
- Sign up at https://api.together.xyz
- Get an API key
- Set in `.env`: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`

### 4. Register the Outlook trigger (run once)
```bash
python setup.py
```
This tells Composio to watch Kory's Outlook inbox and notify the agent.

---

## Running the Agent

```bash
python agent.py
```

The agent will:
1. Connect to Composio
2. Start listening for new emails in Kory's Outlook inbox
3. When an email arrives — analyze it with Hermes using all of Kory's rules
4. Print the proposed action to your terminal
5. Wait for Kory to type `y` (approve) or `n` (reject)
6. Log every decision to `logs/decisions.log`

### Approval options at the prompt:
- `y` — approve and execute the proposed action
- `n` — reject, nothing happens
- `e` — edit: type your own instruction instead
- `s` — skip this email for now

---

## Adjusting the Rules

All scheduling rules live in `rules.py`. To change any rule:
1. Open `rules.py`
2. Edit the relevant section
3. Restart the agent (`Ctrl+C` then `python agent.py`)

No other files need to change when rules change.

---

## Checking the Decision Log

Every email the agent processes is logged:
```bash
cat logs/decisions.log
```

Each entry includes: timestamp, email sender, subject, proposed action summary, and whether Kory approved it.
