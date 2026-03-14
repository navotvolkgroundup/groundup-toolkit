# GroundUp Toolkit — System Map

> Generated: 2026-03-14 | 249 files | ~18,000 LOC

## Project Overview

GroundUp Toolkit is an AI-powered automation platform for GroundUp Ventures, a VC fund. The system ("Christina") automates deal sourcing, meeting management, portfolio monitoring, and content creation via WhatsApp, email, and a web dashboard.

**Server:** Ubuntu arm64 @ 77.42.93.149 | **Runtime:** Python 3 + Node.js | **Gateway:** OpenClaw v0.24

---

## File Inventory Summary

| Category | Files | LOC (est.) |
|----------|-------|------------|
| Shared Libraries (`lib/`) | 11 | 1,755 |
| Skills (13 dirs) | ~65 | ~10,000 |
| Scripts | 9 | ~3,500 |
| Dashboard (`dashboard/`) | 94 | ~6,000 |
| Documentation | 40 | ~2,000 |
| Config/JSON | 33 | ~500 |
| **Total** | **249** | **~18,000** |

### By Extension

| Ext | Count | | Ext | Count |
|-----|-------|-|-----|-------|
| .tsx | 51 | | .json | 33 |
| .ts | 40 | | .sh | 6 |
| .md | 40 | | .js | 3 |
| .py | 36 | | Other | 7 |

---

## Shared Libraries (`lib/`)

| File | Lines | Purpose | Used By |
|------|-------|---------|---------|
| `hubspot.py` | 560 | HubSpot CRM ops via Maton gateway | 6+ skills |
| `gws.py` | 408 | Google Workspace (Gmail, Calendar, Drive) | 10+ skills |
| `config.py` | 284 | Central config singleton (YAML + .env) | All Python skills |
| `safe_url.py` | 129 | SSRF protection with domain allowlist | deal-analyzer, deck-analyzer |
| `config.js` | 110 | Node.js config loader | meeting-bot |
| `claude.py` | 81 | Claude API client with retry/backoff | 8+ skills |
| `whatsapp.py` | 53 | WhatsApp via OpenClaw CLI | All messaging |
| `safe_log.py` | 49 | PII/credential redaction in logs | All skills |
| `brave.py` | 47 | Brave Search API wrapper | 4 skills |
| `email.py` | 34 | Email sender via gws | 4+ skills |
| `__init__.py` | 1 | Package marker | - |

---

## Skills (13 directories)

### Deal Sourcing (5 skills)

| Skill | Status | LOC | Trigger | APIs Used |
|-------|--------|-----|---------|-----------|
| **founder-scout** | Active | ~2,200 + 11 modules | Cron daily 7am, weekly Sunday, watchlist Wed/Sat | LinkedIn browser, Claude, HubSpot, SQLite |
| **deal-analyzer** | Active | ~2,000 | WhatsApp, email, CLI | Claude (Haiku+Sonnet), Brave, HubSpot, Drive |
| **deal-automation** (email-to-deal) | Active | ~2,000 | Cron every 2h | Gmail, Claude, HubSpot, WhatsApp |
| **deal-logger** | Placeholder | ~50 | Not implemented | - |
| **deck-analyzer** | Deprecated | ~800 | - | Replaced by deal-analyzer |

### Scheduling (3 skills)

| Skill | Status | LOC | Trigger | APIs Used |
|-------|--------|-----|---------|-----------|
| **meeting-reminders** | Active | ~2,200 | Cron */5 min, WhatsApp | Calendar, HubSpot, LinkedIn scraping, WhatsApp |
| **meeting-bot** | Active | ~1,200 | Cron */3 min | Calendar, Camofox browser, Drive, Claude, Gmail |
| **ping-teammate** | Active | ~100 | WhatsApp | Twilio voice |

### Portfolio & Content (2 skills)

| Skill | Status | LOC | Trigger | APIs Used |
|-------|--------|-----|---------|-----------|
| **keep-on-radar** | Active | ~1,500 | Cron 15th monthly, reply poll */2h | HubSpot, Brave, Claude, Gmail, WhatsApp |
| **content-writer** | Active | ~1,200 | WhatsApp | Claude, Brave, voice profiles |

### Internal/Utility (3 skills)

| Skill | Status | LOC | Trigger | APIs Used |
|-------|--------|-----|---------|-----------|
| **vc-automation** | Active (partial) | ~300 | WhatsApp, CLI | HubSpot, Claude, Brave, Calendar |
| **linkedin** | Active | ~50 | Used by other skills | OpenClaw browser |
| **google-workspace** | Active | ~200 | Used by other skills | gws-auth CLI |

### Founder Scout Intelligence Modules

| Module | Purpose |
|--------|---------|
| `idf_classifier.py` | Investor Decision Framework scoring |
| `github_enhanced.py` | GitHub activity monitoring |
| `registrar.py` | Israeli Companies Registrar scan |
| `domain_monitor.py` | Domain registration tracking |
| `event_tracker.py` | Startup event detection |
| `retention_clock.py` | Acquisition retention period tracking |
| `social_graph.py` | Network/connection analysis |
| `competitive_intel.py` | Competitive landscape analysis |
| `going_dark.py` | Stealth mode signal detection |
| `advisor_tracker.py` | Advisory role monitoring |
| `scoring.py` | Composite scoring system |

---

## Scripts (`scripts/`)

| Script | Lines | Purpose | Schedule |
|--------|-------|---------|----------|
| `email-to-deal-automation.py` | ~2,000 | Main email→deal pipeline | Cron */2h |
| `portfolio_monitor.py` | ~800 | Portfolio email handling + HubSpot sync | Cron daily 3am |
| `health-check.sh` | ~300 | System health + escalation (email, Twilio) | Cron */15 min |
| `meeting-brief-optin-handler.py` | ~300 | Opt-in/out for meeting briefs | Cron */2h |
| `log-watcher.py` | ~170 | Monitor 11 log files, alert on errors | Cron */30 min + daily |
| `generate_tearsheet.py` | ~170 | Portfolio tear sheet PDF generation | On demand |
| `load-env.sh` | ~100 | Safe .env loading (no shell injection) | Called by cron jobs |
| `daily-maintenance.sh` | ~60 | OpenClaw updates, server upgrades | Cron daily 4am |
| `run-scheduled.sh` | ~40 | Run scheduled tasks | Cron */2h |

---

## Dashboard (`dashboard/`)

**Stack:** Next.js 16.1 + React 19 + TypeScript + Tailwind + shadcn/ui + Zustand + TanStack Query + Recharts

### Pages

| Page | Purpose |
|------|---------|
| `/` | Main dashboard (15+ widgets) |
| `/login` | Google OAuth (@groundup.vc only) |
| `/portfolio` | Portfolio monitoring view |
| `/settings` | Service configuration |

### API Routes (22 endpoints)

| Endpoint | Rate | Data Source |
|----------|------|-------------|
| `GET /api/pipeline` | 30/min | HubSpot |
| `GET /api/stats` | 30/min | HubSpot + logs |
| `GET /api/signals` | 30/min | SQLite + logs |
| `GET /api/deal-flow` | 20/min | HubSpot |
| `GET /api/leads` | 30/min | SQLite |
| `GET /api/meetings` | 20/min | Log parsing |
| `POST /api/chat` | 20/min | OpenClaw agent |
| `GET /api/portfolio` | 30/min | HubSpot |
| `GET /api/portfolio/add-context` | 30/min | HubSpot |
| `GET /api/portfolio/investment-data` | 30/min | HubSpot |
| `GET /api/portfolio/news` | 30/min | Web search |
| `GET /api/portfolio/tear-sheet` | 30/min | HubSpot |
| `GET/PATCH /api/services` | 60/min | In-memory |
| `GET /api/service-health` | 30/min | Log analysis |
| `GET /api/signal-conversion` | 20/min | HubSpot + logs |
| `GET /api/stage-movements` | 20/min | HubSpot |
| `GET /api/team-activity` | 20/min | HubSpot |
| `GET /api/notifications` | 120/min | 10 log files |
| `POST /api/actions` | 10/min | Shell exec |
| `GET /api/deal-sources` | 20/min | HubSpot |
| `GET /api/response-time` | 20/min | Log parsing |

### Components (45 files)

- **UI primitives** (10): avatar, badge, button, dropdown, input, scroll-area, separator, sheet, switch, tooltip
- **Dashboard widgets** (18): PipelineFunnel, DealFlowChart, TeamHeatmap, SignalFeed, LeadsPanel, StatsBar, DealSources, StaleDeals, DealMovements, SignalConversion, ResponseTime, MeetingPrep, QuickActions, ActivityFeed, Greeting, KeyboardShortcuts, PortfolioMonitoring, AddContextMenu
- **Chat** (5): ChatFAB, ChatWindow, ChatInput, ChatMessage, TypingIndicator
- **Layout** (4): AppShell, Sidebar, TopBar, StatusBadge
- **Services** (4): ServiceGrid, ServiceCard, ServiceHelp, ServiceToggle
- **Notifications** (2): NotificationPanel, NotificationItem
- **Other** (2): ChristinaAvatar, providers

---

## External API Dependencies

| Service | Auth | Wrapper | Skills Using |
|---------|------|---------|-------------|
| **Claude API** (Anthropic) | API key | `lib/claude.py` | 8+ |
| **HubSpot** (via Maton) | Bearer token | `lib/hubspot.py` | 6+ |
| **Google Workspace** | OAuth2 (gws-auth) | `lib/gws.py` | 10+ |
| **Brave Search** | API key | `lib/brave.py` | 4 |
| **WhatsApp** (OpenClaw) | Gateway auth | `lib/whatsapp.py` | All messaging |
| **Twilio** | Account SID + key | Direct in scripts | ping-teammate, health-check |
| **LinkedIn** (browser) | Browser session | OpenClaw CDP | founder-scout, meeting-reminders |

---

## Data Stores

| Store | Location | Used By |
|-------|----------|---------|
| `founder-scout.db` (SQLite) | `data/` | founder-scout, dashboard signals/leads |
| `keep-on-radar.db` (SQLite) | `data/` | keep-on-radar |
| `attendee_cache.db` (SQLite) | `data/` | meeting-reminders |
| `deal-analyzer-audit.db` (SQLite) | `data/` | deal-analyzer |
| `meeting-brief-optin.json` | `data/` | meeting-reminders |
| `bot-joined-meetings.json` | `data/` | meeting-bot |
| Voice profiles (24 JSON files) | `skills/content-writer/profiles/` | content-writer |
| Google cookies | `skills/meeting-bot/` | meeting-bot |
| Log files (11) | `/var/log/` | log-watcher, dashboard |

---

## Cron Schedule (~26 jobs)

| Frequency | Jobs |
|-----------|------|
| */3 min | meeting-auto-join |
| */5 min | meeting-reminders |
| */15 min | health-check, post-meeting-processor |
| */30 min | log-watcher alert |
| */2 hours | email-to-deal, run-scheduled, keep-on-radar replies, optin handler |
| Daily | founder-scout scan (7am), maintenance (4am), portfolio sync (3am), session health (7am), log digest (8pm) |
| Weekly | founder-scout briefing (Sun 8am), watchlist (Wed+Sat 2pm) |
| Monthly | keep-on-radar review (15th 10am) |

---

## Security Posture

| Area | Status | Notes |
|------|--------|-------|
| Secrets management | Green | All in .env, gitignored |
| Auth (dashboard) | Green | Google OAuth, @groundup.vc only, JWT 7-day |
| Input validation | Yellow | API routes validated; some bare except: |
| SSRF protection | Green | Domain allowlist + IP pinning |
| Shell injection | Green | List-based subprocess everywhere |
| Rate limiting | Yellow | In-memory only (no Redis) |
| Security headers | Green | CSP, X-Frame-Options, etc. |
| Dependencies | Yellow | npm pinned; Python deps not pinned |
| Audit: 23 findings | Green | All 23 remediated |
