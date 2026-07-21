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


def test_build_lexi_html_email_no_logo_by_default() -> None:
    # Logo removed for now — the sign-off must carry no image/attachment reference.
    html = build_lexi_html_email("Hi,\n\nThursday at 2pm works.")
    assert "Lexi</div>" in html or ">Lexi<" in html
    assert "Iconic Founders Group" in html
    assert "Assistant to Kory Mitchell" in html
    assert "lexi@iconicfounders.com" in html
    assert "Thank you," in html
    assert "<table" in html
    assert "<img" not in html
    assert "cid:" not in html
    assert "data:image" not in html


def test_inline_logo_attachment_disabled_by_default() -> None:
    assert build_lexi_inline_logo_attachment() is None


def test_inline_logo_attachment_when_embed_enabled(monkeypatch) -> None:
    monkeypatch.setenv("LEXI_SIGNATURE_EMBED_LOGO", "true")
    attachment = build_lexi_inline_logo_attachment()
    assert attachment is not None
    assert attachment["contentId"] == "ifg-logo.png"
    assert attachment["isInline"] is True
    assert attachment["contentBytes"]


def test_signature_block_single_column_no_logo_by_default() -> None:
    block = build_lexi_html_signature_block(use_cid=True)
    assert "cid:ifg-logo.png" not in block
    assert "border-left:1px solid" not in block
    assert "Assistant to Kory Mitchell" in block


def test_signature_block_two_column_when_embed_enabled(monkeypatch) -> None:
    monkeypatch.setenv("LEXI_SIGNATURE_EMBED_LOGO", "true")
    block = build_lexi_html_signature_block(use_cid=True)
    assert "border-left:1px solid" in block
    assert "cid:ifg-logo.png" in block
