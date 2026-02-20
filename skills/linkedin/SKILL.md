---
name: linkedin
description: LinkedIn automation via browser for messaging, profile viewing, search, and network actions.
homepage: https://linkedin.com
metadata: {"clawdbot":{"emoji":"💼"}}
---

# LinkedIn

Use browser automation to interact with LinkedIn - check messages, view profiles, search, and send connection requests.

## Setup

### 1. Install the systemd service
```bash
cp services/linkedin-browser.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now linkedin-browser.service
```

### 2. Create the OpenClaw browser profile
```bash
openclaw browser create-profile --name linkedin --color '#0077B5'
openclaw config set browser.noSandbox true
openclaw config set browser.headless true
```

### 3. Log in to LinkedIn (one-time)
```bash
openclaw browser navigate --browser-profile linkedin https://www.linkedin.com
# Use Google OAuth or email/password to log in via browser tool
# Session cookies persist in /root/.openclaw/browser-data/linkedin/
```

## Common Operations

### Search People
```
browser action=navigate profile=linkedin targetUrl="https://www.linkedin.com/search/results/people/?keywords=QUERY"
browser action=snapshot profile=linkedin
```

### View Profile
```
browser action=navigate profile=linkedin targetUrl="https://www.linkedin.com/in/USERNAME/"
browser action=snapshot profile=linkedin
```

### View Company
```
browser action=navigate profile=linkedin targetUrl="https://www.linkedin.com/company/COMPANY/"
browser action=snapshot profile=linkedin
```

### Check Connection Status
```
browser action=snapshot profile=linkedin targetUrl="https://www.linkedin.com/feed/"
```

### View Messages
```
browser action=navigate profile=linkedin targetUrl="https://www.linkedin.com/messaging/"
browser action=snapshot profile=linkedin
```

### Send Message (confirm with user first!)
1. Navigate to messaging or profile
2. Use `browser action=act` with click/type actions
3. Always confirm message content before sending

## Safety Rules
- **Never send messages without explicit user approval**
- **Never accept/send connection requests without confirmation**
- **Avoid rapid automated actions** - LinkedIn is aggressive about detecting automation
- Rate limit: ~30 actions per hour max recommended

## Tips
- Use `--efficient` flag on snapshots to get clickable ref labels
- Use `--format aria` for full accessibility tree (more detail)
- The browser session survives server restarts (systemd auto-starts Chromium)

## Troubleshooting
- If logged out: Re-authenticate via Google OAuth in the browser
- If rate limited: Wait 24 hours, reduce action frequency
- If CAPTCHA: Complete manually in browser, then resume
- If browser won't start: Check `systemctl --user status linkedin-browser.service`
