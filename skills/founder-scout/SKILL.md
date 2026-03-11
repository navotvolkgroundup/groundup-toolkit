---
name: founder-scout
description: Proactively discover Israeli tech founders about to start new companies via LinkedIn signals. Syncs leads to HubSpot and tracks approach status.
homepage: https://groundup.vc
metadata: {"clawdbot":{"emoji":"🔍"}}
---

# Founder Scout

Automated scouting for Israeli tech founders and operators who are about to start new companies — before they announce or raise. Uses LinkedIn browser automation exclusively to search for people, analyze profiles, and detect early signals. Syncs discovered founders to HubSpot as leads.

## Target Profile
- Israeli tech founders, CTOs, VPs who recently left a company
- Serial entrepreneurs between ventures
- 8200/Talpiot alumni starting something new
- Operators hinting at "stealth mode" or "building something new"

## Signal Tiers
- **High**: Left role, stealth mode, co-founding announcement
- **Medium**: Open to work, recent exit/acquisition, exploring opportunities
- **Low**: Accelerator completion, grants, advisory roles

## Commands

```bash
# Daily scan — run rotated LinkedIn searches, detect signals
founder-scout scan

# Weekly briefing — compile and email summary
founder-scout briefing

# Re-scan existing tracked people
founder-scout watchlist-update

# View current state
founder-scout status

# Manually add a person
founder-scout add "Name" "https://linkedin.com/in/username"

# Dismiss a tracked person
founder-scout dismiss <id>

# Sync all tracked people to HubSpot as lead contacts
founder-scout sync-hubspot

# Mark a person as approached (by name)
founder-scout approach "Yuval Lev"

# Mark a person as approached (by DB id)
founder-scout approach-id 42
```

## Handling "I approached X" Messages

**IMPORTANT — Assistant behavior for approach tracking:**

When a user says something like:
- "I approached Yuval Lev"
- "I reached out to Noa Kaufman"
- "Mark Yossi Cohen as approached"
- "We contacted the Fluent.ai founder"

The assistant MUST:
1. Run `founder-scout approach "<person name>"` to mark them as approached
2. This updates both the local database AND HubSpot (sets `hs_lead_status` to `CONTACTED`)
3. Confirm to the user that the person was marked as approached
4. If multiple matches are found, show the list and ask the user to clarify

If the person is not in the watchlist, tell the user and offer to add them first with `founder-scout add`.

## HubSpot Integration

Founder Scout syncs tracked people to HubSpot as **contacts** with `lifecyclestage = lead`.

### Custom Properties
These custom properties should exist in HubSpot (create them manually if needed):
- `scout_signal_tier` (text) — High / Medium / Low signal tier
- `scout_last_signal` (text) — Latest signal description

### Standard Properties Used
- `hs_linkedinid` — LinkedIn profile URL
- `hs_lead_status` — OPEN (default) or CONTACTED (approached)
- `lifecyclestage` — Set to "lead"

### Sync Schedule
Run `founder-scout sync-hubspot` after each daily scan (add to cron):
```bash
# Sync to HubSpot at 7:30 AM (after 7 AM scan completes)
30 7 * * * load-env.sh founder-scout -- scout.py sync-hubspot
```

## Setup

### 1. Environment
Requires these keys in `.env`:
- `ANTHROPIC_API_KEY` — for Claude signal analysis
- `MATON_API_KEY` — for HubSpot sync via Maton gateway

### 2. Cron (automated)
```bash
# Daily scan at 7:00 AM
0 7 * * * load-env.sh founder-scout -- scout.py scan

# Sync leads to HubSpot at 7:30 AM
30 7 * * * load-env.sh founder-scout -- scout.py sync-hubspot

# Weekly briefing Sunday 8:00 AM
0 8 * * 0 load-env.sh founder-scout -- scout.py briefing

# Watchlist re-scan Wed/Sat 14:00
0 14 * * 3,6 load-env.sh founder-scout -- scout.py watchlist-update
```

### 3. LinkedIn browser (required)
The LinkedIn browser skill must be configured and running. The scan will abort if the browser session is unavailable.

## Email Recipients
Reports are sent to team members configured in `config.yaml`.

## Rate Limits
- LinkedIn browser: max 15 profile lookups/scan, ~4s delay between navigations
- Claude API: max 10 calls/scan (~$0.10/scan)
