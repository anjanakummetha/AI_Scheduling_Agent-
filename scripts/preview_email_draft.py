#!/usr/bin/env python3
"""Print example Lexi scheduling email draft (Kory formatting rules)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.scheduling.email_format import example_draft_preview

if __name__ == "__main__":
    sample = example_draft_preview()
    print("INBOUND")
    print(f"  From: {sample['inbound_from']}")
    print(f"  Subject: {sample['inbound_subject']}")
    print("\nDRAFT REPLY (what Lexi would stage after Kory says yes)\n")
    print("─" * 60)
    print(sample["draft_body"])
    print("─" * 60)
    print("\nFORMAT RULES")
    for rule in sample["format_rules"]:
        print(f"  • {rule}")
    print("\nJSON:", json.dumps(sample, indent=2))
