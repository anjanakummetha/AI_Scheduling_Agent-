"""
Hooks called when dashboard approvals/rejections happen.
Records feedback into the lexi_feedback pipeline.
"""

from __future__ import annotations

from typing import Any

from app.lexi.feedback import record_from_dashboard_approval, record_from_dashboard_rejection


def on_approve(decision: dict[str, Any]) -> None:
    try:
        record_from_dashboard_approval(decision)
    except Exception:
        pass


def on_reject(decision: dict[str, Any], reason: str | None = None) -> None:
    try:
        record_from_dashboard_rejection(decision, reason)
    except Exception:
        pass
