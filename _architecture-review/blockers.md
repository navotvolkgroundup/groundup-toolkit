# Blockers & Risks

Items that need human decision or are too risky to execute autonomously.

---

## Critical — Needs Human Action

### 1. Google cookies in git history
- **File:** `skills/meeting-bot/google-cookies.json`
- **Issue:** Real Google auth cookies (SID, HSID, SSID, APISID, etc.) are in git history
- **Required action:** Run `git filter-repo` or BFG to purge from history. This rewrites git history and requires force-push.
- **Status:** BLOCKED — destructive operation, needs explicit user approval and coordination

### 2. Server vs repo divergence (gws-auth migration)
- **Issue:** Server has been migrated from `gog` to `gws-auth` with shared `lib/gws.py`. Repo still uses `gog`.
- **Required action:** Port server migration to repo (Phase 8 of modernization plan)
- **Status:** DEFERRED — out of scope for this rearchitecture pass; will be addressed separately

---

## Low — Remaining Items

### 3. Server deployment sync
- **Issue:** All local repo changes need to be deployed to server (77.42.93.149)
- **Action:** Copy updated scripts to `/root/` and `/root/.openclaw/scripts/` on server
- **Status:** Ready — all changes committed

---

## Resolved

- **deck-analyzer deprecation** — Deprecation notice added to SKILL.md
- **vc-automation/linkedin-api-helper.py** — Deleted (non-functional)
- **whatsapp-healthcheck.sh** — Deleted (redundant)
- **whatsapp-watchdog.sh** — Deleted (escalation merged into health-check.sh)
- **HubSpot stage IDs** — Added `stages` to config.yaml, reminders.py reads from config with fallback
- **Opt-in handler** — Replaced source-code regex modification with JSON file (`data/meeting-brief-optin.json`)
- **SQLite context managers** — All connections in scout.py and radar.py now use `with` blocks
- **State file consolidation** — All state files now use `data/` directory (content-writer, deal-analyzer, meeting-bot, health-alerts)
