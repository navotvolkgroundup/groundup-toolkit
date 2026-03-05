# Security Fixes Applied

**Date:** 2026-03-05

## Fix 1: Command Injection — `lib/gws.py` `run_gws()` [H-1]
- Replaced `shell=True` + f-string interpolation with list-based `subprocess.run`
- `run_gws()`: `cmd = ['gws-auth'] + resource.split()` with `--params`/`--json` as separate args
- `_gws_send_simple()`: Reads body file content directly, passes all args as list

## Fix 2: HTTP Security Headers — `dashboard/next.config.ts` [H-2]
- Added `headers()` function returning security headers on all routes:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `Permissions-Policy: camera=(), microphone=(), geolocation=()`

## Fix 3: Path Traversal — `exports/deal-analyzer/deal_analyzer.py` [H-3]
- Added `_ALLOWED_LOCAL_DIRS` allowlist (`~/decks`, `/tmp`, `~/.groundup-toolkit/state`)
- `_read_local_file()` now resolves real path via `os.path.realpath()` and validates against allowlist
- Blocks any file read outside allowed directories

## Fix 4: SSRF Protection — `exports/deal-analyzer/deal_analyzer.py` [H-4]
- Added domain allowlist in `fetch_deck_content()`: docsend.com, docs.google.com, drive.google.com, dropbox.com, papermark.com, pitch.com, slides.com, canva.com
- Blocks requests to non-allowed domains (prevents cloud metadata exfiltration)

## Fix 5: Pin next-auth Version — `dashboard/package.json` [H-5]
- Changed `"next-auth": "^5.0.0-beta.30"` to `"next-auth": "5.0.0-beta.30"` (exact pin, no caret)

## Fix 6: CDP Localhost Binding — `services/linkedin-browser.service` [H-7]
- Added `--remote-debugging-address=127.0.0.1` to Chrome flags
- Ensures DevTools Protocol port is explicitly bound to localhost only

## Fix 7: Explicit Auth in API Routes — `dashboard/app/api/chat/route.ts`, `services/route.ts` [M-1]
- Added `const session = await auth()` check at the top of every handler
- Returns 401 Unauthorized if no session (defense-in-depth beyond middleware)

## Fix 8: Input Validation — `dashboard/app/api/chat/route.ts`, `services/route.ts` [M-3]
- Chat: validates `message` is string, enforces 10,000 char max, catches malformed JSON
- Services: validates `serviceId` is string and `enabled` is boolean
- Both routes return 400 Bad Request on invalid input

## Fix 9: User Input Reflection — `dashboard/app/api/chat/route.ts` [L-8]
- Removed raw user message echoing from fallback response
- Generic help text returned instead of reflecting user input

## Fix 10: Shell Injection in config.js — `lib/config.js` [L-2]
- Replaced `execSync` with `execFileSync` for YAML config parsing
- Config path passed as argument instead of shell-interpolated string

## Fix 11: `.gitignore` Lock File — `.gitignore` [M-8]
- Changed `package-lock.json` to `/package-lock.json` (root-only)
- Dashboard's lock file is now always tracked in git

## Fix 12: Data Directory Permissions — 3 skills [L-5]
- Added `mode=0o700` to `os.makedirs()` in:
  - `skills/founder-scout/scout.py`
  - `skills/keep-on-radar/radar.py`
  - `skills/meeting-reminders/reminders.py`
- Data directories now created with owner-only access
