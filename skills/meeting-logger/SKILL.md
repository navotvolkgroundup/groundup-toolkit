---
name: meeting-logger
description: Log meeting notes (Granola, manual, etc.) to HubSpot portfolio company records via WhatsApp or Telegram.
metadata: {"openclaw": {"emoji": "📝", "requires": {}}}
---

# Meeting Logger

Logs meeting notes to HubSpot as portfolio company touchpoints. Team members paste notes (e.g. from Granola) and Christina logs them to the right company record with extracted metrics and action items.

## Commands

```bash
# Log meeting notes for a company
meeting-logger log <company_name> <notes>

# Log with full message (auto-extracts company name)
meeting-logger log-message <full_message>
```

## Trigger — Chat Message from Team Member

Team member sends meeting notes via WhatsApp or Telegram. Examples:
- "log to Standar: Met with Daniel, discussed product roadmap..."
- "meeting notes for Portless: Summary - discussed Q1 metrics..."
- "notes for Array: Call with Matt about the repositioning..."
- Or just paste Granola notes that mention a portfolio company name

## What Happens

1. Extracts the portfolio company name (regex patterns or Claude fallback)
2. Fuzzy-matches to known portfolio companies
3. Uses Claude to extract metrics, action items, and health signals
4. Creates a formatted note on the HubSpot company record
5. Confirms back with matched company name and summary

## Supported Formats

- **Granola exports**: Structured notes with Summary, Key Points, Action Items sections
- **Plain text**: Any freeform meeting notes
- **Copy-paste**: Raw notes with company name prefix ("log to [Company]: ...")
