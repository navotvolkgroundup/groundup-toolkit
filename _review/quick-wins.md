# GroundUp Toolkit — Quick Wins

> Generated: 2026-03-14 | S effort (< 1 hour) + Low risk only

These are changes that can be deployed immediately with minimal risk.

---

## Safety Fixes (30 min total)

- [ ] **Add file lock to email-to-deal-automation.py** (15 min)
  - File: `scripts/email-to-deal-automation.py`
  - Add `fcntl.flock(LOCK_EX | LOCK_NB)` at script entry
  - Prevents duplicate deals from overlapping cron runs

- [ ] **Add file lock to post-meeting-processor** (15 min)
  - File: `skills/meeting-bot/post-meeting-processor`
  - Same pattern — prevents duplicate recording processing

## Bug Fixes (40 min total)

- [ ] **Fix bare `except:` → `except Exception:`** (20 min)
  - `scripts/email-to-deal-automation.py` (3 locations)
  - `skills/meeting-reminders/reminders.py` (1 location)
  - Prevents swallowing KeyboardInterrupt/SystemExit

- [ ] **Fix hardcoded timezone in calendar events** (15 min)
  - File: `skills/google-workspace/create-calendar-event`
  - +02:00 is wrong during summer DST; use zoneinfo

- [ ] **Fix escaped shebang** (5 min)
  - File: `skills/google-workspace/google-workspace`
  - `#\!/bin/bash` → `#!/bin/bash`

## Code Cleanup (30 min total)

- [ ] **Replace deprecated `datetime.utcnow()`** (15 min)
  - Multiple files across skills and scripts
  - Use `datetime.now(timezone.utc)` instead

- [ ] **Remove dead `create_opt_in_instructions()` function** (5 min)
  - File: `scripts/meeting-brief-optin-handler.py`
  - Function defined but never called

- [ ] **Remove non-functional linkedin-api-helper.py** (5 min)
  - File: `skills/vc-automation/linkedin-api-helper.py`
  - Non-functional LinkedIn API wrapper (API deprecated)

- [ ] **Remove dead JS files from meeting-bot** (5 min)
  - Files: `skills/meeting-bot/force-join.js` and similar
  - ~10 unused JavaScript files

## Operational Improvements (45 min total)

- [ ] **Add pre-reboot WhatsApp alert to daily-maintenance.sh** (15 min)
  - File: `scripts/daily-maintenance.sh`
  - Send alert before `apt-get upgrade` / reboot

- [ ] **Remove deprecated deck-analyzer skill** (15 min)
  - Directory: `skills/deck-analyzer/`
  - Verify no references, then remove (functionality in deal-analyzer)

- [ ] **Update dashboard services.ts** (15 min)
  - File: `dashboard/lib/data/services.ts`
  - Ensure descriptions, triggers, and statuses match current reality

---

## Total Estimated Time: ~2.5 hours

All items are:
- **S effort** (under 1 hour each, most under 15 min)
- **Low risk** (safe to deploy without extensive testing)
- **High impact** relative to effort (safety fixes prevent data corruption)

## Recommended Order

1. Safety fixes first (file locks) — prevents active data corruption
2. Bug fixes — correctness issues
3. Code cleanup — reduce confusion
4. Operational — better maintenance experience
