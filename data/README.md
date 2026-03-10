# data/ — Persistent State

All runtime state files (SQLite databases, JSON state, tracking files).

## Convention

- SQLite databases: `<skill-name>.db`
- JSON state: `<skill-name>-state.json`
- All files in this directory should be in .gitignore

## What belongs here

- SQLite databases: founder-scout.db, keep-on-radar.db, meeting-reminders.db, founder-briefs.db
- JSON state: content-writer-state.json, deal-analyzer-state.json, meeting-brief-optin.json
- Meeting metadata: meeting-meta/ subdirectory
- Health alerts: health-alerts/ subdirectory
- Bot tracking: bot-joined-meetings.json
- Any persistent data that survives restarts

## What does NOT belong here

- Config files (goes in project root or config/)
- Temporary files (use /tmp)
- Log files (use system logging)
