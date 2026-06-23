"""Email body formatting for Kory outbound drafts."""

from app.scheduling.email_format import finalize_outbound_email_body


def test_sign_off_on_separate_lines() -> None:
    body = finalize_outbound_email_body("Hi Dan,\n\nThanks.\n\nLet's Win, Kory")
    assert body.endswith("Let's Win,\nKory")
    assert "Let's Win, Kory" not in body.replace("Let's Win,\nKory", "")


def test_paragraph_spacing() -> None:
    body = finalize_outbound_email_body(
        "Hi Jane,\nFirst point here.\nSecond point here.\n\nThanks."
    )
    assert "First point here.\n\nSecond point here." in body
    assert body.endswith("Let's Win,\nKory")


def test_adds_sign_off_when_missing() -> None:
    body = finalize_outbound_email_body("Hi there,\n\nQuick note.")
    assert body.endswith("Let's Win,\nKory")
