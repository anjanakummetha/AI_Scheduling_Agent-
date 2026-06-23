"""IFG HTML email signature for Lexi outbound mail."""

import os

from app.scheduling.lexi_html_signature import (
    build_lexi_html_email,
    build_lexi_html_signature_block,
    build_lexi_inline_logo_attachment,
    lexi_html_signature_enabled,
)


def test_html_signature_enabled_by_default() -> None:
    old = os.environ.pop("LEXI_HTML_SIGNATURE_ENABLED", None)
    try:
        assert lexi_html_signature_enabled() is True
    finally:
        if old is not None:
            os.environ["LEXI_HTML_SIGNATURE_ENABLED"] = old


def test_build_lexi_html_email_heidi_layout() -> None:
    html = build_lexi_html_email("Hi,\n\nThursday at 2pm works.")
    assert "Lexi</div>" in html or ">Lexi<" in html
    assert "Iconic Founders Group" in html
    assert "Assistant to Kory Mitchell" in html
    assert "lexi@iconicfounders.com" in html
    assert "Thank you," in html
    assert "<table" in html
    assert 'cid:ifg-logo.png' in html


def test_inline_logo_attachment() -> None:
    attachment = build_lexi_inline_logo_attachment()
    assert attachment is not None
    assert attachment["contentId"] == "ifg-logo.png"
    assert attachment["isInline"] is True
    assert attachment["contentBytes"]


def test_signature_block_two_column() -> None:
    block = build_lexi_html_signature_block(use_cid=True)
    assert "border-left:1px solid" in block
    assert "cid:ifg-logo.png" in block
