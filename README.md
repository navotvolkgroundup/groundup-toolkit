# GroundUp Toolkit

An open-source automation toolkit for venture capital teams, built on [OpenClaw](https://openclaw.ai). Automates deal flow, meeting management, CRM updates, and team communication through an AI assistant connected via WhatsApp.

Built and battle-tested by [GroundUp Ventures](https://groundup.vc).

## What It Does

| Skill | Description |
|-------|-------------|
| **Meeting Reminders** | WhatsApp alerts 10 min before meetings with attendee context from HubSpot, LinkedIn, and Crunchbase |
| **Meeting Bot** | Auto-joins Google Meet calls, records, extracts action items with Claude AI, emails summaries |
| **Deal Automation** | Monitors Gmail for deal emails, auto-creates HubSpot companies and deals |
| **Deck Analyzer** | Extracts structured data from pitch decks (DocSend, Google Drive, Dropbox) |
| **VC Automation** | Processes meeting notes into CRM updates, researches founders |
| **Ping Teammate** | Call a teammate's phone via WhatsApp command using Twilio |
| **Google Workspace** | Calendar, Gmail, and Docs operations via gog CLI |
| **LinkedIn** | Profile research via MCP bridge |
| **Keep on Radar** | Monthly review of watchlist deals — researches company updates, sends digests, handles pass/keep/note actions |
| **Deal Logger** | Tracks deal discussions from WhatsApp conversations |

Plus operational scripts:
- **Health Check** - Monitors gateway, WhatsApp, disk, memory; auto-recovers and alerts
- **WhatsApp Watchdog** - Tests WhatsApp connection every 5 min, restarts gateway, calls admin if QR re-scan needed
- **Shabbat-Aware Scheduler** - Respects Jewish Shabbat hours for automation timing

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  WhatsApp    │◄───►│   OpenClaw    │◄───►│  Skills &   │
│  (Team Chat) │     │   Gateway     │     │  Scripts    │
└─────────────┘     └──────────────┘     └──────┬──────┘
                                                 │
                    ┌────────────────────────────┤
                    │            │               │
              ┌─────▼─────┐ ┌───▼───┐ ┌────────▼────────┐
              │  Google    │ │HubSpot│ │  Claude AI       │
              │  Workspace │ │  CRM  │ │  (Analysis)      │
              └───────────┘ └───────┘ └─────────────────┘
```

## Requirements

- **Server**: Ubuntu 22.04+ (or Debian-based), 2GB RAM, 20GB disk
- **Node.js**: 18+ (installed automatically by `install.sh`)
- **Python**: 3.10+ (installed automatically by `install.sh`)

## Quick Start

### 1. Clone and configure

```bash
git clone https://github.com/navotvolkgroundup/groundup-toolkit.git
cd groundup-toolkit

# Copy and fill in your config
cp config.example.yaml config.yaml
cp .env.example .env
# Edit both files with your values
```

### 2. Install

```bash
sudo bash install.sh
```

### 3. Connect services

```bash
# Google OAuth
gog auth login

# WhatsApp
openclaw channels login
# Scan QR code from your phone

# Start gateway
nohup openclaw gateway > /var/log/openclaw-gateway.log 2>&1 &
```

### 4. Set up cron jobs

```bash
# Edit crontab.example: set TOOLKIT_DIR to your actual path
nano cron/crontab.example

# Then install (WARNING: this replaces your existing crontab):
crontab cron/crontab.example
```

### 5. Verify

```bash
openclaw channels status
bash scripts/health-check.sh
```

## Configuration

All configuration lives in two files:

### config.yaml
Team members, service settings, scheduling preferences. See [config.example.yaml](config.example.yaml).

### .env
API keys and secrets. See [.env.example](.env.example).

Required services:
| Service | What For | Sign Up |
|---------|----------|---------|
| [OpenClaw](https://openclaw.ai) | WhatsApp gateway | Required |
| [Anthropic](https://console.anthropic.com) | Claude AI for analysis | Required |
| [Maton](https://maton.ai) | HubSpot API gateway | For CRM features |
| [Twilio](https://twilio.com) | Phone call alerts | For ping/alerts |
| [Brave Search](https://brave.com/search/api) | Web search | For research |
| Google Workspace | Calendar, Gmail, Drive | Required |

## Documentation

- [Setup Guide](docs/setup-guide.md) - Detailed installation walkthrough
- [Architecture](docs/architecture.md) - How the system works
- [Skills Reference](docs/skills.md) - Each skill explained
- [Services Setup](docs/services.md) - External service configuration

## Project Structure

```
groundup-toolkit/
├── config.example.yaml        # All settings (team, services, schedule)
├── .env.example               # API keys template
├── install.sh                 # Server setup
├── skills/                    # OpenClaw skills
│   ├── meeting-reminders/     # WhatsApp meeting alerts
│   ├── meeting-bot/           # Auto-join & record meetings
│   ├── deal-automation/       # Email → CRM deals
│   ├── deck-analyzer/         # Pitch deck extraction
│   ├── vc-automation/         # Meeting notes → CRM
│   ├── ping-teammate/         # Phone call pinger
│   ├── google-workspace/      # Calendar/Gmail/Docs
│   ├── keep-on-radar/         # Monthly watchlist review
│   ├── linkedin/              # Profile research
│   └── deal-logger/           # WhatsApp deal tracking
├── scripts/                   # Operational scripts
│   ├── health-check.sh        # System monitoring
│   ├── whatsapp-watchdog.sh   # Connection monitor
│   ├── email-to-deal-automation.py
│   └── run-scheduled.sh       # Shabbat-aware scheduler
├── lib/                       # Shared config loaders
│   ├── config.py              # Python config
│   └── config.js              # Node.js config
├── cron/                      # Cron job templates
└── docs/                      # Documentation
```

## License

MIT - see [LICENSE](LICENSE).

## Contributing

Contributions welcome! This toolkit was built for VC workflows but the patterns (WhatsApp automation, meeting management, CRM integration) apply broadly. Open an issue or PR.

---

Built with [OpenClaw](https://openclaw.ai) and [Claude](https://anthropic.com).
