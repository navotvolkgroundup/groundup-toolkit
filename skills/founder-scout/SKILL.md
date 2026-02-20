---
name: founder-scout
description: Proactively discover Israeli tech founders about to start new companies via LinkedIn + web signals.
homepage: https://groundup.vc
metadata: {"clawdbot":{"emoji":"🔍"}}
---

# Founder Scout

Automated scouting for Israeli tech founders and operators who are about to start new companies — before they announce or raise. Uses Brave Search + LinkedIn browser automation to detect signals and send alerts.

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
# Daily scan — run rotated Brave searches, detect signals
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
- `BRAVE_SEARCH_API_KEY` — for web searches
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

### 3. LinkedIn browser (optional)
If the LinkedIn browser skill is configured, high-signal candidates get full profile lookups via `openclaw browser`.

## Email Recipients
Reports are sent to team members configured in `config.yaml`.

## Rate Limits
- Brave Search: 6-8 queries/day (rotated from pool of 10)
- Claude API: max 10 calls/day (~$0.10/day)
- LinkedIn browser: max 5 profile lookups/day
