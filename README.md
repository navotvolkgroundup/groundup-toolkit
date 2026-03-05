# GroundUp Toolkit v1.0

An open-source automation toolkit for venture capital teams, built on [OpenClaw](https://openclaw.ai). Automates deal flow, meeting management, founder research, CRM updates, and team communication through a customizable AI assistant connected via WhatsApp and a web dashboard.

Built and battle-tested by [GroundUp Ventures](https://groundup.vc). Ships with a default assistant persona ("Christina") that you can rename and customize to fit your firm.

## Skills

| Skill | Trigger | Description |
|-------|---------|-------------|
| **Meeting Reminders** | Every 5 min (cron) | WhatsApp alerts 10 min before meetings with attendee context from HubSpot, LinkedIn, and Crunchbase |
| **Meeting Bot** | Every 2–3 min (cron) | Auto-joins Google Meet calls, records audio, transcribes, extracts action items with Claude, emails summaries |
| **Email-to-Deal Logger** | Every 2 hrs (cron) | Monitors Gmail for founder intros and deal emails, auto-creates HubSpot companies and deals with extracted context |
| **Deck Analyzer** | WhatsApp command | Extracts structured data from pitch decks (DocSend, Google Drive, Dropbox) using Camofox browser |
| **Deal Analyzer** | WhatsApp / standalone | Full investment memo — 12-section AI analysis, market sizing, team eval, competitive landscape |
| **Founder Scout** | Daily + weekly (cron) | Scans LinkedIn for pre-founding signals (stealth updates, vesting cliffs, new company registrations) |
| **Keep on Radar** | Monthly + replies (cron) | Reviews HubSpot watchlist deals, researches updates, sends digest emails, handles pass/keep/note actions |
| **Content Writer** | WhatsApp command | Drafts LinkedIn posts, emails, and memos using customizable voice profiles |
| **VC Automation** | WhatsApp command | Processes meeting notes into CRM updates, researches founders on LinkedIn and Crunchbase |
| **Ping Teammate** | WhatsApp command | Calls a teammate's phone via Twilio when you need them urgently |
| **Google Workspace** | WhatsApp command | Calendar queries, Gmail search, Google Docs operations via gws-auth CLI |
| **LinkedIn Research** | WhatsApp command | Profile and company research using headless Chromium browser |
| **Deal Logger** | WhatsApp command | Tracks deal discussions and notes from WhatsApp conversations |

## Dashboard

A Next.js web dashboard for the team at `http://<server>:3000`:

- Google OAuth login restricted to your team's email domain (configurable in `dashboard/lib/auth.ts`)
- Real-time service status for all 13 skills
- Chat interface with your AI assistant (name configurable in `config.yaml`)
- Service help section with trigger info and commands
- Dark/light theme

## Systemd Services

| Service | Port | Description |
|---------|------|-------------|
| `christina-dashboard` | 3000 | Next.js dashboard (production build) |
| `linkedin-browser` | 18801 | Headless Chromium with LinkedIn session (CDP, localhost-only) |
| `openclaw-gateway` | 18789 | WhatsApp gateway (OpenClaw) |

## Cron Schedule

| Schedule | Job | Log |
|----------|-----|-----|
| `*/3 * * *` | Meeting auto-join (detect & join Google Meet) | meeting-auto-join.log |
| `*/5 * * *` | Meeting reminders (WhatsApp alerts) | meeting-reminders.log |
| `*/5 * * *` | WhatsApp watchdog (connection health) | whatsapp-watchdog.log |
| `*/15 * * *` | OpenClaw health check (gateway + system) | openclaw-health.log |
| `0 */2 * * *` | Meeting bot (process recordings & notes) | meeting-bot.log |
| `0 */2 * * *` | Christina processor (scheduling + deal logging) | christina.log |
| `0 */2 * * *` | Keep on Radar — check email replies | keep-on-radar.log |
| `30 8-22/2 * * 0-4` | Email-to-Deal pipeline (Sun–Thu, 8am–10pm) | deal-automation.log |
| `30 8-18/2 * * 5` | Email-to-Deal pipeline (Fri, stops before Shabbat) | deal-automation.log |
| `0 7 * * *` | Founder Scout — daily LinkedIn scan | founder-scout.log |
| `0 8 * * 0` | Founder Scout — weekly briefing | founder-scout.log |
| `0 14 * * 3,6` | Founder Scout — watchlist re-scan | founder-scout.log |
| `0 10 15 * *` | Keep on Radar — monthly review | keep-on-radar.log |
| `0 4 * * *` | Daily maintenance + OpenClaw auto-update | daily-maintenance.log |

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   WhatsApp   │◄───►│   OpenClaw   │◄───►│   Skills &   │
│  (Team Chat) │     │   Gateway    │     │   Scripts    │
└──────────────┘     └──────────────┘     └──────┬───────┘
                                                  │
       ┌──────────────┐    ┌──────────────────────┤
       │  Dashboard   │    │         │            │
       │  (Next.js)   │    │         │            │
       └──────────────┘    │         │            │
                     ┌─────▼───┐ ┌───▼───┐ ┌─────▼──────┐
                     │ Google  │ │HubSpot│ │  Claude AI  │
                     │Workspace│ │  CRM  │ │ (Anthropic) │
                     └─────────┘ └───────┘ └────────────┘
```

## Standalone Exports

The **Deal Analyzer** is available as a standalone Python package:

```bash
cd exports/deal-analyzer
pip install -r requirements.txt
export ANTHROPIC_API_KEY="sk-..."
python example.py https://docsend.com/view/abc123
```

Generates a 12-section investment memo (markdown + HTML) with market sizing, team evaluation, competitive analysis, and a TL;DR.

## Requirements

- **Server**: Ubuntu 22.04+ (arm64 or amd64), 2GB RAM, 20GB disk
- **Node.js**: 18+
- **Python**: 3.10+
- **OpenClaw**: v0.24+

## Quick Start

```bash
# Clone and configure
git clone https://github.com/navotvolkgroundup/groundup-toolkit.git
cd groundup-toolkit
cp config.example.yaml config.yaml
cp .env.example .env
# Edit both files with your API keys and team settings

# Install
sudo bash install.sh

# Connect Google + WhatsApp
gog auth login
openclaw channels login   # Scan QR code

# Start gateway
systemctl enable --now openclaw-gateway

# Deploy dashboard
cd dashboard && npm install && npm run build
systemctl enable --now christina-dashboard

# Install cron jobs
crontab cron/crontab.example
```

## Configuration

| File | Purpose |
|------|---------|
| `config.yaml` | Team members, assistant name, service settings, scheduling (Shabbat-aware) |
| `.env` | API keys: Anthropic, Brave Search, Twilio, HubSpot (Maton) |
| `dashboard/.env` | Dashboard: NEXTAUTH_SECRET, Google OAuth credentials |
| `dashboard/lib/auth.ts` | Allowed email domain for login (change `@groundup.vc` to your domain) |

Required integrations:

| Service | Purpose |
|---------|---------|
| [OpenClaw](https://openclaw.ai) | WhatsApp gateway |
| [Anthropic](https://console.anthropic.com) | Claude AI (analysis, memos, content) |
| [Google Workspace](https://workspace.google.com) | Calendar, Gmail, Drive |
| [Maton](https://maton.ai) | HubSpot API gateway |
| [Twilio](https://twilio.com) | Phone call alerts |
| [Brave Search](https://brave.com/search/api) | Web research |

## Project Structure

```
groundup-toolkit/
├── dashboard/                  # Next.js web dashboard
│   ├── app/                    # Pages and API routes
│   ├── components/             # React components (chat, services, layout)
│   └── lib/                    # Auth, stores, types, utilities
├── skills/                     # OpenClaw WhatsApp skills
│   ├── meeting-reminders/      # Pre-meeting WhatsApp alerts
│   ├── meeting-bot/            # Auto-join, record, transcribe meetings
│   ├── deal-analyzer/          # Full investment memo generation
│   ├── deck-analyzer/          # Pitch deck extraction (DocSend, etc.)
│   ├── founder-scout/          # LinkedIn pre-founding signal scanner
│   ├── keep-on-radar/          # Monthly watchlist review + digest
│   ├── content-writer/         # AI-powered content drafting
│   ├── vc-automation/          # Meeting notes → CRM, founder research
│   ├── deal-logger/            # WhatsApp deal conversation tracking
│   ├── ping-teammate/          # Twilio phone call pinger
│   ├── google-workspace/       # Calendar, Gmail, Docs commands
│   └── linkedin/               # Profile research via headless browser
├── exports/                    # Standalone packages
│   └── deal-analyzer/          # Pip-installable deal analysis library
├── scripts/                    # Operational scripts
│   ├── email-to-deal-automation.py
│   ├── daily-maintenance.sh
│   └── run-scheduled.sh        # Shabbat-aware scheduler
├── services/                   # Systemd unit files
│   └── linkedin-browser.service
├── lib/                        # Shared libraries
│   ├── config.py / config.js   # Config loaders
│   ├── gws.py                  # Google Workspace operations
│   ├── safe_url.py             # SSRF protection
│   └── safe_log.py             # Sanitized error logging
├── config.example.yaml
├── .env.example
└── install.sh
```

## Security

The toolkit includes security hardening (see `_security-audit/`):
- API route auth + rate limiting
- SSRF protection with domain allowlists and DNS pinning
- Input validation on all endpoints
- HTTP security headers
- Dedicated unprivileged user for browser service
- No shell injection (list-based subprocess everywhere)
- Sanitized error logging (no credential leaks)

## License

MIT — see [LICENSE](LICENSE).

## Contributing

Contributions welcome. This toolkit was built for VC workflows but the patterns (WhatsApp automation, meeting management, CRM integration) apply broadly. Open an issue or PR.

---

Built with [OpenClaw](https://openclaw.ai) and [Claude](https://anthropic.com).
