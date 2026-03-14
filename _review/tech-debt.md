# GroundUp Toolkit — Tech Debt Registry

> Generated: 2026-03-14

---

## 1. Code Duplication

### Resolved (via shared libraries)

| Function | Was Duplicated | Centralized To | Status |
|----------|---------------|----------------|--------|
| `call_claude()` | 5 skills | `lib/claude.py` | Done |
| `brave_search()` | 3 skills | `lib/brave.py` | Done |
| `send_whatsapp()` | 5 skills | `lib/whatsapp.py` | Done |
| `send_email()` | 4+ skills | `lib/email.py` + `lib/gws.py` | Done |
| `search_company()` | 2 skills | `lib/hubspot.py` | Done |

### Remaining Duplication

| Item | Location A | Location B | Fix |
|------|-----------|-----------|-----|
| HubSpot owner ID map | `dashboard/app/api/stage-movements/route.ts` | `dashboard/app/api/team-activity/route.ts` | Extract to `dashboard/lib/constants.ts` |
| Pipeline stage labels | `dashboard/app/api/pipeline/route.ts` | `dashboard/app/api/stage-movements/route.ts` | Same constants file |
| Portfolio company list | `scripts/portfolio_monitor.py` (100+ entries) | `dashboard/app/api/portfolio/route.ts` (62 entries) | Single JSON config file |
| `extract_deck_links()` | `skills/deck-analyzer/analyzer.py` | `skills/deal-analyzer/analyzer.py` | Remove deck-analyzer (deprecated) |
| Log file path lists | `dashboard/app/api/service-health/route.ts` | `dashboard/app/api/notifications/route.ts` | Shared constants |
| Maton API base URL | Hardcoded in multiple dashboard routes | `dashboard/lib/hubspot.ts` | Already centralized but some routes bypass it |

---

## 2. Dead Code

### Files to Remove

| File | Reason | Size |
|------|--------|------|
| `skills/deck-analyzer/` (entire dir) | Deprecated — all functionality in deal-analyzer | ~800 LOC |
| `skills/vc-automation/linkedin-api-helper.py` | Non-functional LinkedIn API wrapper (API deprecated) | ~100 LOC |
| `skills/meeting-bot/force-join.js` | Unused join script variant | ~50 LOC |
| ~10 dead JS files in `skills/meeting-bot/` | Leftover from earlier iterations | ~500 LOC |

### Functions to Remove

| Function | File | Reason |
|----------|------|--------|
| `create_opt_in_instructions()` | `scripts/meeting-brief-optin-handler.py` | Defined but never called |
| `reload()` (partial) | `lib/config.py` | Only reloads YAML, not .env — confusing semantics |

### Placeholder/Incomplete

| Item | File | Status |
|------|------|--------|
| `deal-logger` skill | `skills/deal-logger/` | SKILL.md only, no implementation |
| `deal-pass-automation` | `skills/vc-automation/` | Referenced but not implemented |

---

## 3. Monolithic Files

| File | Lines | Problem | Recommended Split |
|------|-------|---------|------------------|
| `scripts/email-to-deal-automation.py` | ~2,000 | Handles scanning, extraction, CRM, opt-in, WhatsApp, portfolio routing | `email_scanner.py`, `company_extractor.py`, `hubspot_service.py`, `notification_service.py` |
| `skills/founder-scout/scout.py` | ~2,200 | Main + 5 subcommands + HubSpot sync + email + WhatsApp | Already has modules/ — extract more into them |
| `skills/meeting-reminders/reminders.py` | ~1,300 | Calendar check + attendee enrichment + WhatsApp + caching | `calendar_checker.py`, `attendee_enricher.py` |
| `skills/deal-analyzer/analyzer.py` | ~2,000 | 5-phase pipeline in one file | `deck_extractor.py`, `market_researcher.py`, `section_analyzer.py`, `report_generator.py` |

---

## 4. Inconsistent Patterns

### Error Handling

| Pattern | Where | Should Be |
|---------|-------|-----------|
| Bare `except:` | email-to-deal (3x), reminders.py (1x) | `except Exception:` |
| Silent failure (return None/[]) | `lib/brave.py`, `lib/hubspot.py` | Log error + return empty |
| No retry | `lib/brave.py`, `lib/hubspot.py` | Add retry for transient errors |
| 5-retry exponential | `lib/claude.py` | Good — standardize others to match |
| 3-retry simple | `lib/whatsapp.py` | Acceptable |

### Config Access

| Pattern | Where | Should Be |
|---------|-------|-----------|
| `config._data['founder_scout']` (private access) | `skills/founder-scout/scout.py` | Add accessor property |
| Hardcoded stage names in source | `meeting-reminders/reminders.py` | Use config.yaml stages |
| No config at all | `skills/vc-automation/research-founder` | Import from lib/config |

### State Storage

| Pattern | Where | Recommended |
|---------|-------|-------------|
| SQLite in `data/` | founder-scout, keep-on-radar, attendee-cache | Good (standardized) |
| JSON in skill dir | `content-writer/profiles/` | Acceptable (skill-specific) |
| JSON in `data/` | meeting-brief-optin, bot-joined-meetings | Good |
| In-memory only | dashboard service toggles | Persist to file |

### Datetime Handling

| Issue | Where |
|-------|-------|
| `datetime.utcnow()` (deprecated) | Multiple files |
| Hardcoded +02:00 timezone | `skills/google-workspace/create-calendar-event` |
| Naive vs aware datetime mixing | `skills/meeting-bot/meeting-auto-join` line 139 |

---

## 5. Missing Infrastructure

| Item | Impact | Effort |
|------|--------|--------|
| **No unit tests** | Can't catch regressions before production | XL |
| **No CI/CD** | Manual deployment via SSH | XL |
| **No Docker** | Non-reproducible server setup | XL |
| **No reverse proxy/TLS** | Dashboard exposed without encryption | L |
| **No Python requirements.txt** | Unpinned dependencies can break | M |
| **No structured logging** | Logs are print() to stderr, hard to parse | L |
| **No health endpoint** | No way to programmatically check dashboard health | S |

---

## 6. Security Debt

| Item | Status | Notes |
|------|--------|-------|
| 23 security audit findings | All fixed | Tracked in `_security-audit/` |
| NextAuth beta in production | Pinned to exact version | Upgrade when stable released |
| In-memory rate limiting | Works for single server | Migrate to Redis for multi-instance |
| IP header spoofing risk | Low risk (internal tool) | Ensure reverse proxy sets headers correctly |
| No HTTPS on dashboard | Must fix before external access | Add nginx + certbot |
| Python deps not pinned | Risk of supply chain issues | Create requirements.txt |

---

## 7. Dashboard-Specific Debt

### Unused/Questionable Components

| Component | Status | Action |
|-----------|--------|--------|
| `ChristinaAvatar.tsx` | Possibly unused | Verify and remove |
| `AddContextMenu.tsx` | Unclear if mounted | Verify usage |
| `KeyboardShortcuts.tsx` | In dashboard page | Verify functional |
| `MeetingPrep.tsx` | May be unused | Verify usage |
| `companyDescriptions.ts` | Loaded but unclear | Check if referenced |
| `soiNameMaps.ts` | Loaded but unclear | Check if referenced |

### Performance Issues

| Issue | Route | Impact |
|-------|-------|--------|
| No HubSpot caching | All HubSpot routes | Redundant API calls |
| Log parsing on every request | stats, signals, notifications | Slow responses |
| 15+ simultaneous API calls on dashboard load | Page component | Race conditions, slow paint |
| N+1 queries in portfolio | /api/portfolio | Serial association lookups |
| Fetch all + filter in-memory | /api/stage-movements | Over-fetching from HubSpot |

### Config Issues

| Issue | Files |
|-------|-------|
| Service state not persisted (in-memory PATCH) | `api/services/route.ts` |
| Log file paths hardcoded | `api/service-health/route.ts`, `api/notifications/route.ts` |
| No .env.example for dashboard | Dashboard directory |

---

## 8. Priority Matrix

```
                    LOW EFFORT          HIGH EFFORT
                ┌──────────────────┬──────────────────┐
    HIGH        │ File locks       │ Split monolithic  │
    IMPACT      │ Fix except:      │ Unit tests        │
                │ Remove dead code │ CI/CD pipeline    │
                │ Pin deps         │ Docker            │
                ├──────────────────┼──────────────────┤
    LOW         │ Fix timezone     │ Redis rate limit  │
    IMPACT      │ Fix shebang      │ Structured logging│
                │ Remove deck-anlz │ Zod validation    │
                │ datetime.utcnow  │ Error boundaries  │
                └──────────────────┴──────────────────┘

Do first: TOP-LEFT (high impact, low effort)
Do next:  TOP-RIGHT (high impact, high effort)
Do when convenient: BOTTOM-LEFT
Consider later: BOTTOM-RIGHT
```

---

## 9. Debt Reduction Targets

### By end of Week 1
- [ ] All file locks in place
- [ ] All bare except: fixed
- [ ] Dead code removed
- [ ] Dashboard constants centralized
- [ ] Python deps pinned

### By end of Month 1
- [ ] Portfolio list dynamic (from JSON/HubSpot)
- [ ] Dashboard caching implemented
- [ ] Structured logging in top 2 scripts
- [ ] Integration tests for email-to-deal

### By end of Quarter 1
- [ ] email-to-deal split into modules
- [ ] CI/CD pipeline operational
- [ ] 50%+ test coverage on critical paths
- [ ] HTTPS on dashboard
