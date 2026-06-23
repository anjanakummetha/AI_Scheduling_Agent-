#!/usr/bin/env python3
"""Locate certifi cacert.pem for the active venv and print .env update instructions."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"


def _resolve_cert_path() -> Path:
    try:
        import certifi

        return Path(certifi.where()).resolve()
    except ImportError as exc:
        raise SystemExit(
            "certifi is not installed in the active environment. "
            "Run: .venv/bin/pip install certifi"
        ) from exc


def main() -> int:
    cert_path = _resolve_cert_path()
    if not cert_path.is_file():
        print(f"[error] Certificate bundle not found at: {cert_path}", file=sys.stderr)
        return 1

    print("Lexi SSL certificate fix")
    print("=" * 60)
    print(f"Resolved certifi bundle: {cert_path}")
    print()
    print("Add or update these lines in your project .env file:")
    print()
    print(f"SSL_CERT_FILE={cert_path}")
    print(f"REQUESTS_CA_BUNDLE={cert_path}")
    print()
    print("Then restart any running processes (uvicorn, orchestrator, Hermes gateway).")
    print()
    if ENV_PATH.exists():
        content = ENV_PATH.read_text()
        if "SSL_CERT_FILE=" in content:
            print(f"Note: {ENV_PATH} already defines SSL_CERT_FILE — replace the old path.")
        else:
            print(f"Note: {ENV_PATH} exists but has no SSL_CERT_FILE entry yet.")
    else:
        print(f"Note: {ENV_PATH} was not found — create it with the lines above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
