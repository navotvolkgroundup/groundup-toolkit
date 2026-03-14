# GroundUp Toolkit — Upgrade Plan

> Generated: 2026-03-14 | Sorted by Priority (Critical → Low)

## Scoring Legend

| Dimension | Scale |
|-----------|-------|
| **Impact** | How much value/risk-reduction this delivers |
| **Effort** | S = <1h, M = 1-4h, L = 4-8h, XL = 8h+ |
| **Risk** | Low = safe to deploy, Med = needs testing, High = could break production |

---

## CRITICAL (Do immediately)

### C-1: Add file lock to email-to-deal-automation.py
- **Impact:** Prevents duplicate deal creation from overlapping cron runs
- **Effort:** S (15 min)
- **Risk:** Low
- **File:** `scripts/email-to-deal-automation.py`
- **Fix:** Add `fcntl.flock()` at script entry point
```python
lock_path = os.path.join(DATA_DIR, 'email-to-deal.lock')
lock_fd = open(lock_path, 'w')
try:
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    sys.exit(0)  # Another instance running
```

### C-2: Fix bare `except:` clauses
- **Impact:** Prevents swallowing KeyboardInterrupt and SystemExit
- **Effort:** S (20 min)
- **Risk:** Low
- **Files:** `email-to-deal-automation.py` (3 locations), `meeting-reminders/reminders.py` (1)
- **Fix:** Replace `except:` with `except Exception:`

### C-3: Fix email-to-deal company name extraction
- **Impact:** Prevents bogus deal names like "Re: Fluent.ai -" or "Re: Intro call?"
- **Effort:** M (2h)
- **Risk:** Med — needs testing with real emails
- **File:** `scripts/email-to-deal-automation.py`
- **Fix:** Loop-strip Fwd:/Re: prefixes, add email domain extraction fallback, Claude fallback for ambiguous names
- **Status:** Plan exists (see plan file), partially implemented

---

## HIGH PRIORITY (This week)

### H-1: Centralize hardcoded HubSpot owner IDs
- **Impact:** Prevents dashboard breakage when team changes
- **Effort:** M (2h)
- **Risk:** Low
- **Files:** `dashboard/app/api/stage-movements/route.ts`, `dashboard/app/api/team-activity/route.ts`
- **Fix:** Create `dashboard/lib/constants.ts` with shared OWNER_NAMES map, or read from config.yaml

### H-2: Centralize hardcoded pipeline stage IDs
- **Impact:** Single source of truth for pipeline config
- **Effort:** M (2h)
- **Risk:** Low
- **Files:** `dashboard/app/api/pipeline/route.ts`, `dashboard/app/api/stage-movements/route.ts`
- **Fix:** Shared constants file or API call to fetch stage labels

### H-3: Move portfolio company list to config/database
- **Impact:** Portfolio changes without code deploys
- **Effort:** L (4h)
- **Risk:** Med
- **Files:** `scripts/portfolio_monitor.py` (100+ hardcoded), `dashboard/app/api/portfolio/route.ts` (62 hardcoded)
- **Fix:** JSON config file synced from HubSpot nightly. `portfolio_monitor.py` already has `sync_portfolio_from_hubspot()` — make it the single source.

### H-4: Add HubSpot response caching to dashboard
- **Impact:** Reduces API calls, faster dashboard load
- **Effort:** M (3h)
- **Risk:** Low
- **Files:** `dashboard/lib/hubspot.ts`, multiple API routes
- **Fix:** In-memory cache with 5-15 min TTL for pipeline, team activity, deal sources

### H-5: Persist service toggle state
- **Impact:** Service toggles survive server restarts
- **Effort:** M (2h)
- **Risk:** Low
- **Files:** `dashboard/app/api/services/route.ts`
- **Fix:** Write to JSON file on PATCH, read on GET (currently in-memory only)

### H-6: Add file lock to meeting-bot recording processor
- **Impact:** Prevents duplicate recording processing
- **Effort:** S (15 min)
- **Risk:** Low
- **File:** `skills/meeting-bot/post-meeting-processor`

### H-7: Pin Python dependencies
- **Impact:** Reproducible deployments, no surprise breakages
- **Effort:** M (2h)
- **Risk:** Low
- **Fix:** Create `requirements.txt` with pinned versions for all Python deps

---

## MEDIUM PRIORITY (This month)

### M-1: Split email-to-deal-automation.py into modules
- **Impact:** Maintainability — currently 2,000 lines in one file
- **Effort:** XL (8h+)
- **Risk:** High — core production pipeline
- **Fix:** Extract into: email_scanner.py, company_extractor.py, hubspot_service.py, notification_service.py

### M-2: Add request.Session() connection pooling
- **Impact:** Faster API calls, reduced connection overhead
- **Effort:** M (2h)
- **Risk:** Low
- **Files:** `deal-analyzer/analyzer.py`, `founder-scout/scout.py`
- **Fix:** Use `requests.Session()` in main loop

### M-3: Fix hardcoded timezone in calendar event creation
- **Impact:** Correct event times during DST transitions
- **Effort:** S (30 min)
- **Risk:** Low
- **File:** `skills/google-workspace/create-calendar-event`
- **Fix:** Use `pytz` or `zoneinfo` for Israel timezone

### M-4: Cache log file parsing in dashboard
- **Impact:** Dashboard performance — currently re-parses logs on every request
- **Effort:** M (3h)
- **Risk:** Low
- **Files:** `dashboard/app/api/stats/route.ts`, `signals/route.ts`, `notifications/route.ts`
- **Fix:** In-memory cache with 5 min TTL for parsed log results

### M-5: Fix N+1 queries in portfolio API
- **Impact:** Faster portfolio page load
- **Effort:** M (2h)
- **Risk:** Low
- **File:** `dashboard/app/api/portfolio/route.ts`
- **Fix:** Batch association lookups instead of serial per-note queries

### M-6: Add structured logging
- **Impact:** Better log analysis, easier debugging
- **Effort:** L (6h)
- **Risk:** Med
- **Fix:** Replace print() with Python logging module across all skills. JSON format for machine parsing.

### M-7: Implement deal-logger skill
- **Impact:** Automated WhatsApp conversation→CRM logging
- **Effort:** XL (8h+)
- **Risk:** Med
- **Files:** `skills/deal-logger/` (currently placeholder)

### M-8: Implement deal-pass-automation in vc-automation
- **Impact:** Automated pass workflows
- **Effort:** L (4h)
- **Risk:** Low
- **File:** `skills/vc-automation/`

### M-9: Add notification before daily-maintenance.sh reboot
- **Impact:** Prevents killing long-running jobs
- **Effort:** S (30 min)
- **Risk:** Low
- **File:** `scripts/daily-maintenance.sh`
- **Fix:** Send WhatsApp/Slack alert 5 min before reboot

### M-10: Replace deprecated datetime.utcnow()
- **Impact:** Correctness + deprecation warnings
- **Effort:** S (30 min)
- **Risk:** Low
- **Fix:** `datetime.now(timezone.utc)` everywhere

---

## LOW PRIORITY (This quarter)

### L-1: Add unit tests for core skills
- **Impact:** Catch regressions before production
- **Effort:** XL (16h+)
- **Risk:** None
- **Coverage target:** email-to-deal, founder-scout, deal-analyzer, meeting-bot
- **Framework:** pytest for Python, vitest for TypeScript

### L-2: Add Zod validation to dashboard API responses
- **Impact:** Type safety for external data (HubSpot, logs)
- **Effort:** L (6h)
- **Risk:** Low
- **Fix:** Replace `JSON.parse()` → Zod schemas in API routes

### L-3: Docker/container deployment
- **Impact:** Reproducible deployments, easier scaling
- **Effort:** XL (16h+)
- **Risk:** High — significant infra change

### L-4: Migrate rate limiting to Redis
- **Impact:** Survives restarts, works across instances
- **Effort:** L (4h)
- **Risk:** Med — new dependency

### L-5: Remove deprecated deck-analyzer skill
- **Impact:** Code cleanup
- **Effort:** S (30 min)
- **Risk:** Low — verify no references first

### L-6: Add error boundaries to dashboard
- **Impact:** Graceful degradation on widget failures
- **Effort:** M (2h)
- **Risk:** Low

### L-7: Replace web scraping with APIs where possible
- **Impact:** Reliability — scraping breaks when sites change
- **Effort:** L (4h)
- **Risk:** Low
- **Files:** `meeting-reminders/reminders.py` (LinkedIn, Crunchbase, GitHub)
- **Fix:** Use official APIs where available; add fallback chain

### L-8: Add CI/CD pipeline
- **Impact:** Automated testing + deployment
- **Effort:** XL (8h+)
- **Risk:** Low

---

## Summary by Effort

| Effort | Count | Items |
|--------|-------|-------|
| S (<1h) | 7 | C-1, C-2, H-6, M-3, M-9, M-10, L-5 |
| M (1-4h) | 10 | C-3, H-1, H-2, H-4, H-5, H-7, M-2, M-5, L-6, L-7 |
| L (4-8h) | 4 | H-3, M-6, M-8, L-2, L-4 |
| XL (8h+) | 5 | M-1, M-7, L-1, L-3, L-8 |

## Summary by Impact

| Priority | Items | Quick Wins (S effort) |
|----------|-------|-----------------------|
| Critical | 3 | C-1, C-2 |
| High | 7 | H-6 |
| Medium | 10 | M-3, M-9, M-10 |
| Low | 8 | L-5 |
