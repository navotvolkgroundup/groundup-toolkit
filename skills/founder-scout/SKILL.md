---
name: founder-scout
description: Proactively discover Israeli tech founders about to start new companies via LinkedIn signals.
homepage: https://groundup.vc
metadata: {"clawdbot":{"emoji":"🔍"}}
---

# Founder Scout

Automated scouting for Israeli tech founders and operators who are about to start new companies — before they announce or raise. Uses LinkedIn browser automation exclusively to search for people, analyze profiles, and detect early signals.

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
```

## Setup

### 1. Environment
Requires these keys in `.env`:
- `ANTHROPIC_API_KEY` — for Claude signal analysis
- `GOG_KEYRING_PASSWORD` + `GOG_ACCOUNT` — for email sending

### 2. Cron (automated)
```bash
# Daily scan at 7:00 AM
0 7 * * * load-env.sh founder-scout -- scout.py scan

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
