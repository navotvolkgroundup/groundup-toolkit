# Skills Reference

Each skill is an OpenClaw automation module. Skills are invoked by the AI agent, by cron, or manually.

---

## Meeting Reminders

**Path**: `skills/meeting-reminders/`

Sends WhatsApp reminders 10-15 minutes before calendar meetings. Includes HubSpot context (company, deal stage, last note) and optionally enriches attendees with LinkedIn, Crunchbase, and GitHub data.

**Features**:
- Per-member timezone support
- 10 WhatsApp retries with 5-second intervals
- Email fallback when WhatsApp is down
- SQLite deduplication (won't send the same reminder twice)
- On-demand "next meeting" query

**Usage**:
```bash
# Run reminder check (normally via cron)
./skills/meeting-reminders/meeting-reminders reminders

# Query next meeting for a user
./skills/meeting-reminders/reminders.py query user@yourcompany.com
```

---

## Meeting Bot

**Path**: `skills/meeting-bot/`

Two components:
1. **meeting-auto-join** - Checks calendar every 3 min, auto-joins meetings via headless browser
2. **meeting-bot** - Processes recordings, extracts action items with Claude, emails summaries

**Requirements**: Camoufox browser running on port 9377, Google cookies configured.

---

## Deal Automation

**Path**: `skills/deal-automation/`

Monitors Gmail for emails from team members containing company/deal information. Automatically creates HubSpot companies and deals, assigns to the sender.

**Related script**: `scripts/email-to-deal-automation.py`

---

## Deck Analyzer

**Path**: `skills/deck-analyzer/`

AI-powered pitch deck data extraction. Supports DocSend, Google Drive, Dropbox, and direct PDF links. Extracts: company name, product overview, problem/solution, team, go-to-market, traction, and fundraising details.

---

## VC Automation

**Path**: `skills/vc-automation/`

Two tools:
- **meeting-notes-to-crm** - Processes meeting notes, extracts key points, updates HubSpot deals
- **research-founder** - Comprehensive founder background research using web search, LinkedIn, and Crunchbase

---

## Ping Teammate

**Path**: `skills/ping-teammate/`

Calls a team member's phone via Twilio when triggered by a WhatsApp message. Security: only configured team members can use it, can't self-ping.

---

## Google Workspace

**Path**: `skills/google-workspace/`

Wrapper scripts for the gog CLI:
- Calendar operations (list, create, delete events)
- Gmail operations (send, read, search)
- Google Drive/Docs access

---

## LinkedIn

**Path**: `skills/linkedin/`

LinkedIn profile research via MCP bridge. Requires LinkedIn authentication cookie.

---

## Content Writer

**Path**: `skills/content-writer/`

Generates written content (LinkedIn posts, Substack notes, LinkedIn messages, newsletters) in team members' authentic voice. Uses per-member voice profiles, audience data, brand context, and Brave web research. Includes a humanizer pass to strip AI writing patterns.

**How it works**:
1. Team member sends a WhatsApp message like "write a LinkedIn post about X"
2. OpenClaw matches the trigger and calls `content-writer generate "<message>" "<phone>"`
3. The skill detects content type, selects the member's voice profile, runs web research on the topic, generates with Claude Sonnet, then humanizes the output
4. Delivers via WhatsApp (short-form) or WhatsApp preview + email (newsletters)

**Content types**:
- **LinkedIn post** — 150-300 words, direct, insight-driven. Trigger: "write a post about..."
- **LinkedIn message** — 2-5 sentences, warm and direct outreach. Trigger: "write a LinkedIn message to..."
- **Substack note** — 1-10 sentences, punchy, single-insight. Trigger: "write a note about..."
- **Newsletter/article** — 800-1500 words, long-form. Trigger: "write a newsletter about..."

**Trigger examples** (via WhatsApp):
```
write a LinkedIn post about why most VC content is boring
draft a post about founder red flags I've seen
write a LinkedIn message to the CTO of Acme about our AI infra thesis
write a note about the state of AI infra
write a newsletter about what seed-stage founders get wrong about GTM
```

Hebrew messages work — output will be in Hebrew with English tech terms.

**Manual usage** (on server):
```bash
# Generate content from a message
~/.openclaw/skills/content-writer/content-writer generate "write a post about X" "+972..."

# Run test (sends a LinkedIn post to the alert phone)
~/.openclaw/skills/content-writer/content-writer test
```

**Per-member profiles**: `profiles/<name>/` contains `voice.json`, `audience.json`, and `brand.json` for each team member. See `profiles/example/` for templates.

**Requires**: `ANTHROPIC_API_KEY`, `BRAVE_API_KEY` (for research)

---

## Deal Logger

**Path**: `skills/deal-logger/`

Scans WhatsApp conversations for deal-related discussions, summarizes with AI, and logs to tracking system.
