"""Shared guard for scripts that can perform real, irreversible actions.

Plan Phase 0: env kill switches alone must never be sufficient to fire a real
send/write from an ad-hoc script. Any script that can touch a real mailbox,
calendar, Asana, or HubSpot must call ``require_live_confirmation`` before doing
so. It demands BOTH:

  1. an explicit ``--i-am-sending-real-email`` CLI flag, and
  2. an interactive typed confirmation matching the target.

If either is missing the script exits non-zero without acting. This is
independent of LEXI_DRY_RUN / write-mode flags — it is a second, human gate.
"""

from __future__ import annotations

import sys

LIVE_FLAG = "--i-am-sending-real-email"


def live_flag_present(argv: list[str] | None = None) -> bool:
    return LIVE_FLAG in (argv if argv is not None else sys.argv[1:])


def require_live_confirmation(target_description: str, *, argv: list[str] | None = None) -> None:
    """Block until the operator explicitly authorizes a real action, or exit.

    ``target_description`` is a short human phrase for what will happen and to
    whom, e.g. "send a real email to kory@iconicfounders.com". The operator must
    pass the LIVE_FLAG and then type the exact phrase ``send-to-<first token>``.
    """
    if not live_flag_present(argv):
        print(
            f"\nREFUSED: this script performs a REAL action ({target_description}).\n"
            f"Re-run with {LIVE_FLAG} and be ready to type a confirmation.\n"
            "No action taken.",
            file=sys.stderr,
        )
        sys.exit(2)

    if not sys.stdin.isatty():
        print(
            "REFUSED: real actions require an interactive terminal for confirmation "
            "(stdin is not a TTY). No action taken.",
            file=sys.stderr,
        )
        sys.exit(2)

    token = (target_description.split() or ["action"])[-1]
    phrase = f"send-to-{token}"
    print(f"\nAbout to: {target_description}")
    print(f"This is REAL and may be irreversible. Type exactly: {phrase}")
    try:
        typed = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        typed = ""
    if typed != phrase:
        print("Confirmation did not match. No action taken.", file=sys.stderr)
        sys.exit(2)
    print("Confirmed. Proceeding.\n")
