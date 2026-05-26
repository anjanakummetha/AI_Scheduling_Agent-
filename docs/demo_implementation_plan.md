# AI Scheduling Agent Demo Implementation Plan

## Goal

Build a web dashboard demo that connects to a demo Microsoft Outlook account, processes inbound scheduling emails, proposes actions with Hermes, validates them against YAML rules, and updates Outlook email/calendar only after dashboard approval.

## Phase 1 Demo Flow

1. Outlook receives a new email.
2. Composio sends a webhook event to the FastAPI app.
3. The app fetches the full Outlook message.
4. Hermes creates a structured scheduling proposal.
5. YAML rules and validators check the proposal.
6. Dashboard shows the pending approval.
7. Approval creates/sends the Outlook draft and updates the Outlook calendar.
8. Rejection records the decision and performs no Outlook action.

## Implementation Checkpoints

1. Durable dashboard foundation with SQLite and YAML rules.
2. Hermes proposal flow returning structured JSON.
3. Composio webhook intake for `OUTLOOK_MESSAGE_TRIGGER`.
4. Outlook calendar availability check and approved calendar event creation.
5. Approved draft creation/sending.
6. End-to-end test against the demo Outlook account and mock calendar.

## Long-Term Architecture Rule

Hermes proposes. YAML rules validate. The dashboard approves. Composio executes. Internal audit logs prove what happened.
