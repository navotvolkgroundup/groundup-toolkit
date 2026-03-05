# Quick Wins (< 30 minutes each)

## 1. Add Security Headers (~10 min)
Add `headers()` to `dashboard/next.config.ts` with X-Frame-Options, X-Content-Type-Options, Referrer-Policy, etc.

## 2. Pin next-auth Version (~2 min)
Change `"next-auth": "^5.0.0-beta.30"` to `"next-auth": "5.0.0-beta.30"` in `dashboard/package.json`.

## 3. Add Explicit Auth to API Routes (~10 min)
Add `const session = await auth()` check at the top of `/api/chat` and `/api/services` handlers.

## 4. Add Input Validation to Chat API (~10 min)
Wrap `req.json()` in try/catch, validate `typeof message === 'string'`, enforce `message.length <= 10000`.

## 5. Fix Data Directory Permissions (~5 min)
Add `mode=0o700` to `os.makedirs()` in `skills/founder-scout/scout.py`, `skills/meeting-reminders/reminders.py`, `skills/keep-on-radar/radar.py`.

## 6. Fix `.gitignore` Lock File Rule (~2 min)
Change `package-lock.json` to `/package-lock.json` in root `.gitignore` so dashboard lock file stays tracked.

## 7. Add `--remote-debugging-address=127.0.0.1` to Browser Service (~2 min)
Explicit localhost binding in `services/linkedin-browser.service`.

## 8. Replace Hardcoded Email in gws.py (~5 min)
Change `'christina@groundup.vc'` to `config.assistant_email` on line 385.

## 9. Fix `configPath` Shell Injection (~5 min)
Replace `execSync` with `execFileSync` in `lib/config.js`.
