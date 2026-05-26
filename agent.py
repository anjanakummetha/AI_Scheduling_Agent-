"""
Kory's AI Scheduling Agent
─────────────────────────────────────────────────────────────
Phase 1: Kory approves ALL actions before execution.
Nothing sends or books without explicit approval.

Run this file to start the agent:
    python agent.py
"""

import os
import sys
import ssl
import certifi
import json
import logging
from datetime import datetime
from dotenv import load_dotenv

# Fix macOS SSL certificate verification before any network calls
os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
ssl._create_default_https_context = ssl.create_default_context

from openai import OpenAI
from composio import Composio

from prompts import build_system_prompt, build_email_context

load_dotenv()

# ─────────────────────────────────────────────────────────────
# LOGGING SETUP
# Every decision the agent makes is logged to /logs/decisions.log
# ─────────────────────────────────────────────────────────────

log_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(log_dir, "decisions.log")),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# Silence noisy Composio heartbeat and telemetry logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("composio").setLevel(logging.WARNING)
logging.getLogger("pysher").setLevel(logging.WARNING)


# ─────────────────────────────────────────────────────────────
# CLIENT SETUP
# ─────────────────────────────────────────────────────────────

def get_llm_client() -> OpenAI:
    """
    Returns an OpenAI-compatible client.
    Works with Ollama (local Hermes), Together AI, OpenRouter, or OpenAI.
    Set LLM_BASE_URL and LLM_API_KEY in your .env file.
    """
    base_url = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")  # default: Ollama
    api_key = os.getenv("LLM_API_KEY", "ollama")  # Ollama ignores the key
    return OpenAI(base_url=base_url, api_key=api_key)


def get_composio_client() -> Composio:
    api_key = os.getenv("COMPOSIO_API_KEY")
    if not api_key:
        logger.error("COMPOSIO_API_KEY not found in .env file.")
        sys.exit(1)
    return Composio(api_key=api_key)


# ─────────────────────────────────────────────────────────────
# LLM CALL
# ─────────────────────────────────────────────────────────────

def ask_hermes(llm: OpenAI, email_data: dict) -> str:
    """Sends the email to Hermes with Kory's full rule set and returns the proposed action."""
    model = os.getenv("LLM_MODEL", "hermes3")  # e.g. hermes3, mistralai/Mixtral-8x7B-Instruct-v0.1

    system_prompt = build_system_prompt()
    user_message = build_email_context(email_data)

    logger.info(f"Sending email to {model} for analysis...")

    response = llm.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=0.2,  # low temp = more rule-following, less creative
    )

    return response.choices[0].message.content


# ─────────────────────────────────────────────────────────────
# APPROVAL GATE — Phase 1 Core Feature
# ─────────────────────────────────────────────────────────────

def request_approval(email_data: dict, proposed_action: str) -> bool:
    """
    Displays the proposed action to Kory and waits for approval.
    Returns True if approved, False if rejected.
    """
    print("\n" + "═" * 60)
    print("  NEW EMAIL RECEIVED")
    print("═" * 60)
    print(f"  From:    {email_data.get('from', 'Unknown')}")
    print(f"  Subject: {email_data.get('subject', 'No subject')}")
    print(f"  Time:    {email_data.get('received_at', 'Unknown')}")
    print("─" * 60)
    print("  AGENT ANALYSIS & PROPOSED ACTION:")
    print("─" * 60)
    print(proposed_action)
    print("═" * 60)

    while True:
        choice = input("\n  Approve this action? [y]es / [n]o / [e]dit / [s]kip: ").strip().lower()
        if choice in ("y", "yes"):
            return True, None
        elif choice in ("n", "no"):
            print("  Action rejected. Nothing will be sent or booked.")
            return False, None
        elif choice in ("e", "edit"):
            print("  Enter your revised instruction (press Enter twice when done):")
            lines = []
            while True:
                line = input()
                if line == "":
                    if lines:
                        break
                else:
                    lines.append(line)
            override = "\n".join(lines)
            return True, override
        elif choice in ("s", "skip"):
            print("  Skipped. No action taken.")
            return False, None
        else:
            print("  Please enter y, n, e, or s.")


# ─────────────────────────────────────────────────────────────
# EXECUTE APPROVED ACTION VIA COMPOSIO
# ─────────────────────────────────────────────────────────────

def execute_action(composio_client: Composio, session, approved_action: str, email_data: dict):
    """
    After Kory approves, re-prompts Hermes with the full Composio toolset
    so it can execute the approved action via Outlook/Calendar tools.
    Hermes uses COMPOSIO_SEARCH_TOOLS → COMPOSIO_MULTI_EXECUTE_TOOL pattern.
    """
    llm = get_llm_client()
    model = os.getenv("LLM_MODEL", "hermes3")
    tools = session.tools()  # includes all Composio meta-tools

    execution_prompt = f"""
The following action has been approved by Kory. Execute it now using the available tools.

APPROVED ACTION:
{approved_action}

ORIGINAL EMAIL CONTEXT:
From: {email_data.get('from')}
Subject: {email_data.get('subject')}

Use COMPOSIO_SEARCH_TOOLS to find the right Outlook/Calendar tools, then execute with COMPOSIO_MULTI_EXECUTE_TOOL.
Sign all outgoing emails with "Let's Win" — never "Best" or "Warmly".
Quote the recipient's local timezone first with MT in parentheses for any time references.
"""

    logger.info("Executing approved action via Composio tools...")
    try:
        response = llm.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": execution_prompt}],
            tools=tools,
            temperature=0.1,
        )
        logger.info(f"Execution response: {response.choices[0].message.content}")
        print(f"\n  Execution complete.")
    except Exception as e:
        logger.error(f"Failed to execute action: {e}")
        print(f"\n  ERROR during execution: {e}")
        print("  The action was approved but could not be sent. Check logs.")


# ─────────────────────────────────────────────────────────────
# DECISION LOGGER
# ─────────────────────────────────────────────────────────────

def log_decision(email_data: dict, proposed_action: str, approved: bool, override: str = None):
    """Writes every decision to the log file for review."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "email_from": email_data.get("from"),
        "email_subject": email_data.get("subject"),
        "proposed_action_summary": proposed_action[:300] + "..." if len(proposed_action) > 300 else proposed_action,
        "approved_by_kory": approved,
        "kory_override": override,
    }
    log_path = os.path.join(log_dir, "decisions.log")
    with open(log_path, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ─────────────────────────────────────────────────────────────
# EMAIL TRIGGER HANDLER
# ─────────────────────────────────────────────────────────────

def handle_incoming_email(event_data: dict, llm: OpenAI, composio_client: Composio, session):
    """
    Called every time Composio fires an OUTLOOK_NEW_EMAIL_EVENT trigger.
    Full pipeline: analyze → propose → approve → execute → log.
    """
    logger.info(f"New email received: {event_data.get('subject', 'No subject')}")

    # Extract email fields from Composio trigger payload
    email_data = {
        "from": event_data.get("from", {}).get("emailAddress", {}).get("address", "Unknown"),
        "subject": event_data.get("subject", "No subject"),
        "body": event_data.get("body", {}).get("content", ""),
        "received_at": event_data.get("receivedDateTime", "Unknown"),
    }

    # Step 1: Ask Hermes to analyze and propose an action
    proposed_action = ask_hermes(llm, email_data)

    # Step 2: Present to Kory for approval (Phase 1 gate)
    approved, override = request_approval(email_data, proposed_action)

    # Step 3: Log the decision regardless of outcome
    log_decision(email_data, proposed_action, approved, override)

    if approved:
        logger.info("Action approved by Kory.")
        action_to_run = override if override else proposed_action
        execute_action(composio, session, action_to_run, email_data)
    else:
        logger.info("Action rejected or skipped by Kory.")


# ─────────────────────────────────────────────────────────────
# MAIN — START THE AGENT
# ─────────────────────────────────────────────────────────────

def main():
    print("\n" + "═" * 60)
    print("  KORY'S AI SCHEDULING AGENT — PHASE 1")
    print("  All actions require Kory's approval before execution.")
    print("═" * 60)

    llm = get_llm_client()
    composio_client = get_composio_client()
    user_id = os.getenv("COMPOSIO_USER_ID", "kory")

    # Create a Composio session for Kory's connected accounts
    session = composio_client.create(user_id=user_id)
    logger.info(f"Composio session created for user: {user_id}")

    # Subscribe to Outlook new email trigger
    logger.info("Subscribing to OUTLOOK_NEW_EMAIL_EVENT trigger...")
    print("  Listening for new emails in Kory's Outlook inbox...")
    print("  Press Ctrl+C to stop the agent.\n")

    try:
        listener = composio_client.triggers.subscribe()

        @listener.handle(trigger_slug="OUTLOOK_MESSAGE_TRIGGER", user_id=user_id)
        def on_new_email(event):
            handle_incoming_email(
                event_data=event.payload if hasattr(event, "payload") else event,
                llm=llm,
                composio_client=composio_client,
                session=session,
            )

        listener.wait_forever()

    except KeyboardInterrupt:
        print("\n\n  Agent stopped by user. Goodbye.")
        logger.info("Agent stopped by user (KeyboardInterrupt).")
    except Exception as e:
        logger.error(f"Agent error: {e}")
        print(f"\n  Agent encountered an error: {e}")
        print("  Check your .env file and Composio connection.")
        raise


if __name__ == "__main__":
    main()
