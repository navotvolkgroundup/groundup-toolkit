# GroundUp Toolkit — 7-Day Development Roadmap

> Generated: 2026-03-14 | Assumes 3-4 hours/day

## Overview

This roadmap prioritizes: safety fixes first, then reliability, then performance, then features. Each day has a clear deliverable.

---

## Day 1 (Sunday) — Safety & Locks
**Theme:** Eliminate data corruption risks

| # | Task | Effort | File(s) |
|---|------|--------|---------|
| 1 | Add fcntl file lock to email-to-deal-automation.py | 15 min | `scripts/email-to-deal-automation.py` |
| 2 | Add fcntl file lock to post-meeting-processor | 15 min | `skills/meeting-bot/post-meeting-processor` |
| 3 | Fix bare `except:` → `except Exception:` (4 locations) | 20 min | `email-to-deal-automation.py`, `reminders.py` |
| 4 | Fix email-to-deal company name extraction (loop-strip Fwd:/Re:, domain fallback, Claude fallback) | 2h | `scripts/email-to-deal-automation.py` |
| 5 | Test email-to-deal with sample emails | 30 min | Manual |

**Deliverable:** No more duplicate deals, no more garbled company names.

---

## Day 2 (Monday) — Dashboard Hardening
**Theme:** Centralize config, add caching

| # | Task | Effort | File(s) |
|---|------|--------|---------|
| 1 | Create `dashboard/lib/constants.ts` with OWNER_NAMES and STAGE_LABELS | 30 min | New file |
| 2 | Update stage-movements and team-activity routes to use constants | 30 min | 2 API routes |
| 3 | Persist service toggle state to JSON file | 1h | `dashboard/app/api/services/route.ts` |
| 4 | Add in-memory cache (5 min TTL) for HubSpot API calls | 1.5h | `dashboard/lib/hubspot.ts` |
| 5 | Add in-memory cache for log file parsing | 1h | `stats`, `signals`, `notifications` routes |

**Deliverable:** Dashboard loads faster, survives restarts, single source of truth for HubSpot IDs.

---

## Day 3 (Tuesday) — Portfolio & Config
**Theme:** Dynamic portfolio, pinned dependencies

| # | Task | Effort | File(s) |
|---|------|--------|---------|
| 1 | Create `data/portfolio-companies.json` from current hardcoded lists | 30 min | New file |
| 2 | Update `portfolio_monitor.py` to read from JSON, write from HubSpot sync | 1.5h | `scripts/portfolio_monitor.py` |
| 3 | Update dashboard portfolio API to read from same JSON | 1h | `dashboard/app/api/portfolio/route.ts` |
| 4 | Create `requirements.txt` with pinned Python deps | 1h | New file |
| 5 | Fix hardcoded timezone in calendar event creation | 15 min | `skills/google-workspace/create-calendar-event` |

**Deliverable:** Portfolio changes without code deploys. Reproducible Python environment.

---

## Day 4 (Wednesday) — Meeting Bot Reliability
**Theme:** Bulletproof meeting automation

| # | Task | Effort | File(s) |
|---|------|--------|---------|
| 1 | Add pre-reboot notification to daily-maintenance.sh | 30 min | `scripts/daily-maintenance.sh` |
| 2 | Fix N+1 queries in portfolio API (batch associations) | 1.5h | `dashboard/app/api/portfolio/route.ts` |
| 3 | Add requests.Session() to deal-analyzer | 30 min | `skills/deal-analyzer/analyzer.py` |
| 4 | Add requests.Session() to founder-scout | 30 min | `skills/founder-scout/scout.py` |
| 5 | Replace deprecated datetime.utcnow() across codebase | 30 min | Multiple files |

**Deliverable:** Faster API calls, no surprise reboots, correct timezone handling.

---

## Day 5 (Thursday) — Cleanup & Dead Code
**Theme:** Remove cruft, improve clarity

| # | Task | Effort | File(s) |
|---|------|--------|---------|
| 1 | Remove deprecated deck-analyzer skill (verify no refs first) | 30 min | `skills/deck-analyzer/` |
| 2 | Remove dead JS files from meeting-bot | 15 min | `skills/meeting-bot/` |
| 3 | Remove unused `create_opt_in_instructions()` | 10 min | `scripts/meeting-brief-optin-handler.py` |
| 4 | Remove non-functional linkedin-api-helper.py | 10 min | `skills/vc-automation/` |
| 5 | Fix escaped shebang in google-workspace skill | 5 min | `skills/google-workspace/google-workspace` |
| 6 | Review and remove unused dashboard components | 1h | `dashboard/components/` |
| 7 | Update dashboard services.ts to match current state | 30 min | `dashboard/lib/data/services.ts` |

**Deliverable:** Cleaner codebase, no dead code, accurate dashboard metadata.

---

## Day 6 (Friday) — Observability
**Theme:** Better logging and monitoring

| # | Task | Effort | File(s) |
|---|------|--------|---------|
| 1 | Add Python logging module to email-to-deal (replace print) | 1.5h | `scripts/email-to-deal-automation.py` |
| 2 | Add Python logging to founder-scout | 1h | `skills/founder-scout/scout.py` |
| 3 | Add error boundaries to dashboard widgets | 1h | `dashboard/components/` |
| 4 | Enhance log-watcher with more error patterns | 30 min | `scripts/log-watcher.py` |

**Deliverable:** Structured logging for the 2 largest scripts. Dashboard doesn't crash on widget errors.

---

## Day 7 (Saturday/Buffer) — Testing & Documentation
**Theme:** Confidence and knowledge capture

| # | Task | Effort | File(s) |
|---|------|--------|---------|
| 1 | Write integration tests for email-to-deal company extraction | 2h | New test file |
| 2 | Write tests for HubSpot lib functions | 1h | New test file |
| 3 | Update README.md with current architecture overview | 30 min | `README.md` |
| 4 | Deploy all changes to server | 30 min | SSH |

**Deliverable:** Test coverage for highest-risk code. Documentation current.

---

## Weekly Summary

| Day | Theme | Hours | Key Deliverable |
|-----|-------|-------|----------------|
| Sun | Safety & Locks | 3.5h | No duplicate deals, clean company names |
| Mon | Dashboard Hardening | 4.5h | Faster dashboard, centralized config |
| Tue | Portfolio & Config | 4h | Dynamic portfolio, pinned deps |
| Wed | Meeting Bot Reliability | 3.5h | Faster APIs, no surprise reboots |
| Thu | Cleanup & Dead Code | 2.5h | Clean codebase |
| Fri | Observability | 4h | Structured logging, error boundaries |
| Sat | Testing & Docs | 4h | Tests + documentation |
| **Total** | | **~26h** | |

## What's NOT in this week

These are important but require more than a week:
- Splitting email-to-deal-automation.py into modules (XL effort, high risk)
- Implementing deal-logger skill (XL effort)
- Docker/container deployment (XL effort)
- CI/CD pipeline (XL effort)
- Migrating rate limiting to Redis (L effort, new dependency)
- Full unit test suite (XL effort, ongoing)
