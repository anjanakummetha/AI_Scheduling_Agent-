#!/usr/bin/env python3
"""Read-only check: does Kory's Outlook signature appear in sent mail / draft API?

Does NOT send email. Does NOT create drafts unless --probe-draft and unlock flags are set.

Usage:
  PYTHONPATH=. .venv/bin/python scripts/test_kory_outlook_signature.py
  PYTHONPATH=. .venv/bin/python scripts/test_kory_outlook_signature.py --top 5
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SIGNATURE_MARKERS = (
    ("iconic founders", r"iconic\s+founders"),
    ("preserving legacy", r"preserving\s+legacy"),
    ("the turn podcast", r"the\s+turn"),
    ("ceo title", r"kory\s+mitchell\s*[-–—]?\s*ceo"),
    ("phone", r"720[-.\s]?561[-.\s]?0611"),
    ("iconicfounders.com", r"iconicfounders\.com"),
    ("html image", r"<img\b"),
)


def _body_text(message: dict) -> str:
    body = message.get("body") or {}
    if isinstance(body, dict):
        content = body.get("content") or ""
        content_type = (body.get("contentType") or "").lower()
        if content_type == "html" or "<" in content:
            return content
        return str(content)
    preview = message.get("bodyPreview") or ""
    return str(preview)


def _score_signature(text: str) -> dict[str, bool]:
    lowered = text.lower()
    return {
        name: bool(re.search(pattern, lowered, flags=re.IGNORECASE))
        for name, pattern in SIGNATURE_MARKERS
    }


def analyze_sent_mail(*, top: int) -> list[dict]:
    from app.integrations.outlook_sent import list_sent_messages

    results: list[dict] = []
    for message in list_sent_messages(top=top):
        text = _body_text(message)
        hits = _score_signature(text)
        results.append(
            {
                "id": message.get("id"),
                "subject": message.get("subject"),
                "sentDateTime": message.get("sentDateTime"),
                "signature_hits": hits,
                "hit_count": sum(1 for v in hits.values() if v),
                "has_html_image": hits.get("html image", False),
                "body_preview": text[:400].replace("\n", " "),
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Kory Outlook signature in sent mail (read-only)")
    parser.add_argument("--top", type=int, default=5, help="Number of sent messages to inspect")
    args = parser.parse_args()

    print("\n=== Kory Outlook signature probe (read-only) ===\n")
    print("Lexi sends plain-text body via API. Outlook may append Kory's rich signature")
    print("when composing/sending from the client — this script checks what appears in Sent Items.\n")

    try:
        rows = analyze_sent_mail(top=max(1, min(args.top, 15)))
    except Exception as exc:
        print(f"[FAIL] Could not read sent mail: {type(exc).__name__}: {exc}")
        print("Ensure KORY_COMPOSIO_CONNECTION_ID and COMPOSIO_API_KEY are set.")
        return 1

    if not rows:
        print("[WARN] No sent messages returned.")
        return 1

    with_signature = 0
    for index, row in enumerate(rows, start=1):
        print(f"--- Sent #{index}: {row.get('subject') or '(no subject)'} ---")
        print(f"  hits: {row['hit_count']}/{len(SIGNATURE_MARKERS)}  image_tag={row['has_html_image']}")
        for name, found in row["signature_hits"].items():
            if found:
                print(f"    ✓ {name}")
        if row["hit_count"] >= 3:
            with_signature += 1
        print()

    print(f"Summary: {with_signature}/{len(rows)} messages show strong signature markers in Sent Items.")

    report = {
        "messages_checked": len(rows),
        "with_rich_signature_markers": with_signature,
        "note": (
            "API sends from Lexi use plain text (Let's Win, / Kory). "
            "If hits are high here, Outlook added signature on send. "
            "Lexi does not inject the HTML/image block programmatically."
        ),
        "samples": rows,
    }
    out = ROOT / "docs" / "KORY_SIGNATURE_PROBE.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report: {out}\n")

    print("Draft-on-screen test: not run (read-only). When writes unlock, Outlook may still")
    print("append signature on CREATE_DRAFT_REPLY — verify manually once in pilot.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
