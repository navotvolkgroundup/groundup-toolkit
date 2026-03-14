---
name: Google Workspace
description: Access Google Calendar, Gmail, and Google Docs/Drive using gws-auth CLI. Download Google Docs, manage calendar events, and send emails.
---

# Google Workspace Integration

Use the `gws-auth` CLI to interact with Google Calendar, Gmail, and Google Drive/Docs.

## Google Docs Operations

### Downloading Google Docs

To download a Google Doc as text:

```bash
~/.openclaw/skills/google-workspace/download-google-doc "DOCUMENT_URL_OR_ID"
```

**Examples:**
```bash
# Full URL
~/.openclaw/skills/google-workspace/download-google-doc "https://docs.google.com/document/d/1aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789_example/edit"

# Just the document ID
~/.openclaw/skills/google-workspace/download-google-doc "1aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789_example"
```

**When to use:**
- User shares a Google Docs link and asks you to process it
- User asks you to download or read a Google Doc
- User wants meeting notes from a Google Doc processed

**Important:** You CAN access Google Docs. Do NOT say you cannot access them.

Phone-to-email mappings are loaded from `config.yaml`. See `config.example.yaml` for format.

### Creating Calendar Events

**IMPORTANT:** The assistant has READ-ONLY access to team calendars. When creating events, create them on the assistant's calendar and invite the requesting user.

**Use the helper script** which handles Israel timezone (Asia/Jerusalem) automatically, including DST transitions:

```bash
~/.openclaw/skills/google-workspace/create-calendar-event <phone> <title_words...> <date> <time> [duration_minutes]
```

**Example: Create "Pick up kids from school" event:**

```bash
~/.openclaw/skills/google-workspace/create-calendar-event +1234567890 Pick up kids from school 2026-02-08 12:45 30
```

- Default duration: 30 minutes if not specified
- The script resolves the phone number to an email and adds them as attendee
- Timezone offset is computed automatically from `Asia/Jerusalem` (handles IST/IDT)

### Important Notes:

1. **Always use the create-calendar-event script** — do not manually construct timezone offsets
2. **If time is ambiguous**, ask the user for clarification

## Gmail Operations

### Send email:

```bash
gws-auth gmail +send --to user@example.com --subject "Subject" --body "Message body"
```

### Search threads:

```bash
gws-auth gmail users threads list --params '{"userId":"me","q":"from:user@example.com","maxResults":5}'
```

## Authentication

All commands use the assistant account credentials configured via `gws-auth auth login`.
Credentials are stored in `~/.config/gws/`.
