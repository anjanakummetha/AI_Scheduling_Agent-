#!/usr/bin/env python3
"""Run the full local test loop (no Azure Teams required).

Usage:
    .venv/bin/python scripts/test_full_stack.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def _run(name: str, script: str, *extra: str) -> bool:
    print(f"\n{'=' * 60}\n{name}\n{'=' * 60}")
    result = subprocess.run(
        [PY, str(ROOT / script), *extra],
        cwd=ROOT,
        capture_output=False,
    )
    ok = result.returncode == 0
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    return ok


def main() -> int:
    results: list[tuple[str, bool]] = []

    results.append(("DB init", _run("DB init", "scripts/init_lexi_db.py")))
    results.append(("Stack verify", _run("Stack verify", "scripts/verify_stack.py")))

    # validators inline
    print(f"\n{'=' * 60}\nValidators unit\n{'=' * 60}")
    code = subprocess.run(
        [
            PY,
            "-c",
            """
from app.rules.validators import validate_proposal_slots
r = validate_proposal_slots(
    [{"start":"2026-06-11T19:00:00-06:00","end":"2026-06-11T20:00:00-06:00"}],
    intent="pitch",
)
assert not r.valid
r2 = validate_proposal_slots(
    [{"start":"2026-06-11T13:00:00-06:00","end":"2026-06-11T13:30:00-06:00"}],
    intent="pitch",
)
assert r2.valid
print('validators ok')
""",
        ],
        cwd=ROOT,
    ).returncode
    results.append(("Validators unit", code == 0))
    print(f"[{'PASS' if code == 0 else 'FAIL'}] Validators unit")

    for name, script, *extra in [
        ("Kory phase suite", "scripts/test_kory_phase_suite.py"),
        ("Mock pipeline", "scripts/test_lexi_pipeline.py"),
        ("Sandbox integration", "scripts/test_sandbox_integration.py"),
        ("Live E2E (staging)", "scripts/test_live_e2e.py", "--skip-approval"),
        ("MCP / Hermes bridge", "scripts/test_mcp_tools.py"),
    ]:
        results.append((name, _run(name, script, *extra)))

    print(f"\n{'=' * 60}\nSUMMARY\n{'=' * 60}")
    failed = [name for name, ok in results if not ok]
    for name, ok in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    if failed:
        print(f"\n{len(failed)} step(s) failed.")
        return 1
    print("\nAll stack tests passed. Use Hermes CLI + MCP for chat approvals without Azure.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
