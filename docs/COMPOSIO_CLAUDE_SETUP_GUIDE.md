# Iconic — Composio & Claude Console Setup Guide

**For:** Heidi (Iconic admin)  
**Purpose:** Create production accounts for Lexi (scheduling agent)  
**Send completed values to:** Anju (secure channel — not in a group email)

Attach screenshots at each step where noted.

---

## Before you start

- Use an **Iconic-owned email** to create both accounts (not a personal account).
- Sign in as **Kory** (or an admin with access to his Outlook, Asana, and billing).
- **API keys and secrets are shown only once.** Copy each value immediately into a secure note and send to Anju when done.
- Do **not** paste secrets in Teams, Slack, or email threads.

---

## Part 1 — Composio (Outlook, Asana, Lexi email)

**Dashboard:** [https://app.composio.dev](https://app.composio.dev)  
**Pricing / plan:** [https://composio.dev/pricing](https://composio.dev/pricing)  
**Outlook toolkit docs:** [https://docs.composio.dev/toolkits/outlook](https://docs.composio.dev/toolkits/outlook)

### Step 1 — Create Iconic organization

1. Go to [app.composio.dev](https://app.composio.dev) and sign up or log in with an Iconic email.
2. Create a new **Organization** for Iconic Founders (if prompted).
3. Subscribe to **Ridiculously Cheap** ($29/month, 200k tool calls/month).
4. Screenshot: billing/plan page. *(attach image)*

### Step 2 — Copy the Composio API key

1. In the Composio dashboard, open **Settings** or **API Keys** (or **AI Clients** → your client).
2. Create or copy the **Organization API key**.
3. **Important:** This key is often shown **only once**. Save it now.

**Send to Anju:** `COMPOSIO_API_KEY`

### Step 3 — Connect Kory’s Outlook (required)

1. In Composio, go to **Connected Accounts** or **Connect Apps**.
2. Search **Microsoft Outlook** and click **Connect**.
3. Sign in with **Kory’s Microsoft 365 account** and approve permissions (mail + calendar).
4. After success, open the connection details and copy the **Connection ID** (starts with `ca_`).
5. Copy the **User / Entity ID** shown for that connection (used as `COMPOSIO_ENTITY_ID`).

**Send to Anju:**
- `KORY_COMPOSIO_CONNECTION_ID` (Outlook — Kory)
- `COMPOSIO_ENTITY_ID` (Kory entity / user id)

Screenshot: connected Outlook account. *(attach image)*

**Note:** If Composio asks for custom Azure OAuth, see [Outlook OAuth guide](https://composio.dev/auth/outlook). For most setups, **Composio managed auth** (click Connect → Microsoft sign-in) is enough.

### Step 4 — Connect Asana (required for reservation reminders)

1. In Composio, connect **Asana**.
2. Sign in with the account that has access to **Kory NON-IFG** and the **Reservation Reminders** board.
3. Copy the **Connection ID** (`ca_...`).

**Send to Anju:** `ASANA_COMPOSIO_CONNECTION_ID`

Screenshot: connected Asana account. *(attach image)*

### Step 5 — Connect Lexi email (when mailbox exists)

*Skip until `lexi@iconicfounders.com` (or similar) is created.*

1. Create the Lexi mailbox in Microsoft 365 (shared mailbox or user).
2. In Composio, connect **Microsoft Outlook** again — this time sign in as **lexi@**.
3. Copy the **Connection ID**.

**Send to Anju:** `LEXI_COMPOSIO_CONNECTION_ID` and the Lexi email address.

### Step 6 — Optional connections (later outreach tools)

Not required for Lexi scheduling v1. Connect when ready:

| App | Composio search name | Send to Anju |
|-----|----------------------|--------------|
| LinkedIn | LinkedIn | `LINKEDIN_COMPOSIO_CONNECTION_ID` |
| HubSpot | HubSpot | `HUBSPOT_COMPOSIO_CONNECTION_ID` |

Screenshot each when connected. *(attach images)*

### Step 7 — Enable new-mail webhook (Anju will configure URL)

1. In Composio, open **Triggers** for the Kory Outlook connection.
2. Confirm **OUTLOOK_MESSAGE_TRIGGER** (or “New message”) is available.
3. Anju will provide the webhook URL after VPS deploy; Heidi can paste it when asked.

**Note:** Webhook replaces constant inbox polling and saves API calls.

---

## Part 2 — Claude Console (Anthropic API for Teams chat)

**Console:** [https://platform.claude.com](https://platform.claude.com)  
**Billing:** [https://platform.claude.com/settings/billing](https://platform.claude.com/settings/billing)  
**Spend limits:** [https://platform.claude.com/settings/limits](https://platform.claude.com/settings/limits)  
**API keys:** [https://platform.claude.com/settings/keys](https://platform.claude.com/settings/keys)

### Step 1 — Use or create Iconic organization

1. Log in at [platform.claude.com](https://platform.claude.com).
2. Use the **Iconic Founders** organization (or create one under Iconic billing).
3. Add a payment method under **Settings → Billing** if not already set.

Screenshot: organization name. *(attach image)*

### Step 2 — Set monthly spend limit

1. Go to **Settings → Limits**: [platform.claude.com/settings/limits](https://platform.claude.com/settings/limits)
2. Under **Spend limits**, click **Set spend limit** or **Change limit**.
3. Set **$25/month** to start (we can raise after a few weeks of real use).
4. Save.

Screenshot: spend limit set to $25. *(attach image)*

**What this controls:** Maximum Anthropic spend per month for Lexi/Hermes (Teams chat + email drafting). It is **not** the same as Composio.

### Step 3 — Create API key for Lexi production

1. Go to **Settings → API Keys**: [platform.claude.com/settings/keys](https://platform.claude.com/settings/keys)
2. Click **Create Key** (name it e.g. `Lexi Production`).
3. **Important:** The full key is shown **only once**. Copy and save immediately.

**Send to Anju:** `ANTHROPIC_API_KEY` (or confirm existing Iconic Founders key should be used).

**Do not** share this key in chat or email.

### When Anthropic is used (for reference)

- Kory messages Lexi in **Teams**
- **New inbound email** triage
- **Drafting** a reply after Kory approves

Reading Outlook calendar/inbox and sending mail after approval uses **Composio**, not Anthropic.

---

## Checklist — send Anju when complete

Copy this list into a **secure message** (1Password share, encrypted email, etc.):

```
COMPOSIO_API_KEY=
KORY_COMPOSIO_CONNECTION_ID=        (Kory Outlook)
COMPOSIO_ENTITY_ID=                 (Kory user/entity id)
ASANA_COMPOSIO_CONNECTION_ID=
LEXI_COMPOSIO_CONNECTION_ID=        (optional — when lexi@ exists)
LEXI_MAILBOX_EMAIL=                 (optional — e.g. lexi@iconicfounders.com)
LINKEDIN_COMPOSIO_CONNECTION_ID=    (optional — later)
HUBSPOT_COMPOSIO_CONNECTION_ID=     (optional — later)
ANTHROPIC_API_KEY=                  (or note: use existing Iconic key)
Claude spend limit set to: $25/month
Composio plan: Ridiculously Cheap ($29/mo)
```

Also confirm:
- [ ] Iconic owns both Composio and Claude orgs (not Anju’s personal accounts)
- [ ] Kory Outlook connected (read mail + calendar)
- [ ] Asana connected (Kory NON-IFG access)
- [ ] Claude spend cap set to $25
- [ ] Screenshots attached for Anju’s records

---

## Security reminders

| Item | Rule |
|------|------|
| API keys | Shown once — save immediately |
| Where to send | Secure channel to Anju only |
| Where not to send | Teams, Slack, group email, screenshots in public channels |
| Rotation | If a key is leaked, revoke in dashboard and create a new one |

---

## Questions

Contact Anju if Composio asks for custom Azure app registration, if Outlook connect fails, or if the Claude org is under the wrong billing account.
