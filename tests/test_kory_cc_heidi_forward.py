"""Kory always CC'd on Lexi sends; Heidi gets briefing + thread forward on escalation."""

from __future__ import annotations

from unittest.mock import patch

from app.integrations.outlook_email import merge_kory_cc_addresses


def test_merge_kory_cc_addresses_dedupes():
    with patch("app.integrations.outlook_email.settings") as mock_settings:
        mock_settings.kory_sender_emails = (
            "kory@ifg.vc",
            "Kory.Mitchell@iconicfounders.com",
        )
        merged = merge_kory_cc_addresses(["kory@ifg.vc", "other@example.com"])
    assert merged == ["kory@ifg.vc", "other@example.com", "kory.mitchell@iconicfounders.com"]


def test_escalate_to_heidi_forwards_thread(monkeypatch):
    # Heidi escalation is disabled by default (routes to Kory); enable it to exercise
    # the Heidi forwarding path this test covers.
    monkeypatch.setenv("LEXI_HEIDI_ESCALATION_ENABLED", "true")
    with patch("app.scheduling.heidi_escalation.build_scheduling_context_packet") as mock_packet:
        mock_packet.return_value = {
            "ok": True,
            "proposal_id": 7,
            "subject": "TEST intro",
            "sender": "prospect@example.com",
            "latest_inbound_body": "Can we meet?",
        }
        with patch("app.scheduling.heidi_escalation._send_heidi_email") as mock_send:
            mock_send.return_value = {"sent": True, "to": "heidi@example.com"}
            with patch("app.scheduling.heidi_escalation._forward_thread_to_heidi") as mock_forward:
                mock_forward.return_value = {"forwarded": True, "to": "heidi@example.com"}
                with patch("app.scheduling.heidi_escalation._mark_escalated"):
                    with patch("app.scheduling.heidi_escalation.teams_push_allowed", return_value=False):
                        from app.scheduling.heidi_escalation import escalate_to_heidi

                        result = escalate_to_heidi(7, failure_error="No slots found")
        mock_forward.assert_called_once()
        assert result["heidi_forward"]["forwarded"] is True


def test_escalate_routes_to_kory_by_default(monkeypatch):
    # Default (flag unset/false): no Heidi email, route to a Kory Teams notification.
    monkeypatch.delenv("LEXI_HEIDI_ESCALATION_ENABLED", raising=False)
    with patch("app.scheduling.heidi_escalation.build_scheduling_context_packet") as mock_packet:
        mock_packet.return_value = {
            "ok": True,
            "proposal_id": 7,
            "subject": "TEST intro",
            "sender": "prospect@example.com",
        }
        with patch("app.scheduling.heidi_escalation._send_heidi_email") as mock_send:
            with patch("app.scheduling.heidi_escalation.teams_push_allowed", return_value=False):
                with patch("app.scheduling.heidi_escalation._mark_needs_kory"):
                    from app.scheduling.heidi_escalation import escalate_to_heidi

                    result = escalate_to_heidi(7, failure_error="No compliant slot")
        mock_send.assert_not_called()
    assert result["path"] == "kory_notification"
    assert "needs your input" in result["summary"].lower()
