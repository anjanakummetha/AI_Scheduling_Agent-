"""Central logging with rotation (plan Phase 4).

File logs under logs/ previously grew unbounded. This installs a rotating file
handler (20 MB × 5 = 100 MB cap) plus a console handler, idempotently.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False
_FMT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def configure_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    level = os.getenv("LEXI_LOG_LEVEL", "INFO").upper()
    root = logging.getLogger()
    root.setLevel(level)

    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(_FMT))
        root.addHandler(console)

    try:
        from app.config import ROOT_DIR

        log_dir = Path(os.getenv("LEXI_LOG_DIR", str(ROOT_DIR / "logs")))
        log_dir.mkdir(parents=True, exist_ok=True)
        max_bytes = int(os.getenv("LEXI_LOG_MAX_BYTES", str(20 * 1024 * 1024)))
        backups = int(os.getenv("LEXI_LOG_BACKUPS", "5"))
        if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
            fileh = RotatingFileHandler(
                log_dir / "lexi.log", maxBytes=max_bytes, backupCount=backups
            )
            fileh.setFormatter(logging.Formatter(_FMT))
            root.addHandler(fileh)
    except Exception:
        # File logging is best-effort; console logging already covers the journal.
        pass

    _CONFIGURED = True
