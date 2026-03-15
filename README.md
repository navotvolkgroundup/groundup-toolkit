# GroundUp Toolkit

[![CI](https://github.com/navotvolkgroundup/groundup-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/navotvolkgroundup/groundup-toolkit/actions/workflows/ci.yml)

AI-powered automation platform for venture capital teams -- deal sourcing, meeting management, portfolio monitoring, and content creation via WhatsApp, email, and a web dashboard.

Built on [OpenClaw](https://openclaw.ai) and [Claude](https://anthropic.com). Battle-tested by [GroundUp Ventures](https://groundup.vc).

## Architecture Overview

The system has four layers:

- **OpenClaw Gateway** -- WhatsApp messaging gateway with 6 configurable agents. Receives commands from the team and dispatches them to skills.
- **Skills (Python)** -- 13 automation modules for deal sourcing, meetings, portfolio tracking, and content. Run on cron schedules or triggered via WhatsApp.
- **Dashboard (Next.js)** -- Web UI with pipeline views, signal feeds, portfolio monitoring, chat, and service controls. Authenticated via Google OAuth.
- **Shared Libraries** -- Python and Node.js wrappers for Claude API, HubSpot (via Maton), Google Workspace, Brave Search, WhatsApp, and Twilio.

External dependencies: Claude API (Anthropic), HubSpot CRM (via Maton), Google Workspace (OAuth2 via gws-auth), Brave Search, Twilio, and a headless Chromium session for LinkedIn.

```
WhatsApp <---> OpenClaw Gateway <---> Skills & Scripts
                                          |
              Dashboard (Next.js)         |
                                    ------+------
                                    |     |     |
                                 Google HubSpot Claude
                                Workspace  CRM    API
```

## Directory Structure

```
groundup-toolkit/
  dashboard/          Next.js web dashboard (React 19, TypeScript, Tailwind, shadcn/ui)
    app/              Pages (/, /portfolio, /settings, /login) and 22 API routes
    components/       45 React components (widgets, chat, layout, services)
    lib/              Auth, stores, types, utilities
  skills/             13 OpenClaw skill directories (Python)
  scripts/            Operational scripts (email-to-deal pipeline, health checks, maintenance)
  lib/                Shared Python/JS libraries (config, hubspot, gws, claude, whatsapp, etc.)
  services/           Systemd unit files
  exports/            Standalone packages (deal-analyzer library)
  data/               SQLite databases and state files (gitignored)
  config.example.yaml Team members, assistant name, service settings
  .env.example        API keys (Anthropic, Brave, Twilio, HubSpot/Maton)
  install.sh          Server setup script
```

## Skills

### Deal Sourcing

| Skill | Trigger | What it does |
|-------|---------|--------------|
| **Founder Scout** | Cron daily/weekly | Scans LinkedIn for pre-founding signals (stealth mode, vesting cliffs, new registrations) using 11 intelligence modules, pushes leads to HubSpot |
| **Deal Analyzer** | WhatsApp / email | Generates 12-section investment memos from pitch decks with market sizing, team eval, and competitive analysis |
| **Email-to-Deal** | Cron every 2h | Monitors Gmail for founder intros, auto-creates HubSpot companies and deals, asks sender when uncertain |
| **Deck Analyzer** | Deprecated | Replaced by Deal Analyzer |

### Meetings

| Skill | Trigger | What it does |
|-------|---------|--------------|
| **Meeting Reminders** | Cron every 5 min | WhatsApp alerts 10 min before meetings with attendee context from HubSpot, LinkedIn, and Crunchbase |
| **Meeting Bot** | Cron every 3 min | Auto-joins Google Meet, records, transcribes, extracts action items, emails summaries |
| **Ping Teammate** | WhatsApp command | Calls a teammate's phone via Twilio |

### Portfolio and Content

| Skill | Trigger | What it does |
|-------|---------|--------------|
| **Keep on Radar** | Cron monthly + reply polling | Reviews HubSpot watchlist deals, researches updates, sends digest emails |
| **Content Writer** | WhatsApp command | Drafts LinkedIn posts, emails, and memos using customizable voice profiles |

### Utilities

| Skill | Trigger | What it does |
|-------|---------|--------------|
| **VC Automation** | WhatsApp command | Processes meeting notes into CRM updates, founder research |
| **Google Workspace** | WhatsApp command | Calendar queries, Gmail search, Google Docs operations |
| **LinkedIn Research** | Internal | Profile and company research via headless Chromium browser |
| **Deal Logger** | Placeholder | Not yet implemented |

## Dashboard

Next.js 16 app at `http://<server>:3000`. Google OAuth login restricted to your team's email domain.

Key features:
- Pipeline funnel, deal flow charts, team heatmap, signal feed
- Portfolio monitoring with tear sheets and news
- Chat interface with your AI assistant
- Service status grid with toggle controls
- 22 API routes pulling from HubSpot, SQLite, and log files

Stack: React 19 + TypeScript + Tailwind + shadcn/ui + Zustand + TanStack Query + Recharts.

## Setup

**Requirements:** Ubuntu 22.04+ (arm64 or amd64), Python 3.10+, Node.js 18+, OpenClaw v0.24+.

```bash
git clone https://github.com/navotvolkgroundup/groundup-toolkit.git
cd groundup-toolkit

# Configure
cp config.example.yaml config.yaml    # Team members, assistant name, settings
cp .env.example .env                   # API keys
cp dashboard/.env.example dashboard/.env  # Dashboard OAuth config

# Python dependencies
pip install -r requirements.txt

# Dashboard
cd dashboard && npm install && npm run build && cd ..

# Connect services
gws-auth auth login       # Google Workspace OAuth
openclaw channels login   # WhatsApp QR code

# Install
sudo bash install.sh
```

Edit `dashboard/lib/auth.ts` to set your team's allowed email domain.

See `config.example.yaml` and `.env.example` for all configuration options.

## Deployment

Runs on an Ubuntu server, deployed via SSH. Three systemd services:

| Service | Port | Purpose |
|---------|------|---------|
| `openclaw-gateway` | 18789 | WhatsApp gateway |
| `christina-dashboard` | 3000 | Next.js dashboard |
| `linkedin-browser` | 18801 | Headless Chromium with LinkedIn session |

Cron jobs handle scheduled tasks (~26 jobs from every 3 minutes to monthly). See `cron/crontab.example` for the full schedule. The scheduler (`scripts/run-scheduled.sh`) is Shabbat-aware.

## Standalone Export

The Deal Analyzer is available as a standalone Python package in `exports/deal-analyzer/`.

## License

MIT -- see [LICENSE](LICENSE).
