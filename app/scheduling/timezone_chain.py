"""Extract recipient-authored text from an email chain (exclude Kory/IFG quoted blocks)."""

from __future__ import annotations

import re

_INTERNAL_FROM_RE = re.compile(
    r"(?im)^from:\s*[^<\n]*<[^>@]+@(?:iconicfounders\.com|ifg\.vc)>",
)
_CHAIN_SPLIT_RE = re.compile(
    r"(?im)(?:^from:\s|^-----original message-----|^________________________________)",
)


def recipient_chain_text(body: str) -> str:
    """Recipient lines across the thread — skips quoted Kory/IFG message blocks."""
    text = (body or "").replace("\r\n", "\n").strip()
    if not text:
        return ""

    segments = _CHAIN_SPLIT_RE.split(text)
    kept: list[str] = []
    for segment in segments:
        chunk = segment.strip()
        if not chunk:
            continue
        if _INTERNAL_FROM_RE.search(chunk[:300]):
            continue
        if re.search(r"@(?:iconicfounders\.com|ifg\.vc)\b", chunk[:400], re.I):
            # Likely a quoted internal signature block.
            if re.search(r"(?im)^(kory|heidi)\b", chunk[:200]):
                continue
        kept.append(chunk)
    return "\n\n".join(kept).strip()
