# Security Remediation Plan

**Date:** 2026-03-05
**Status:** ALL HIGH, MEDIUM, and LOW findings FIXED

---

## Priority 1 -- Fix Today (HIGH) ✅ ALL DONE

- [x] **H-1** Fix `shell=True` command injection in `lib/gws.py` `run_gws()` -- use list-based subprocess
- [x] **H-2** Add HTTP security headers to `dashboard/next.config.ts`
- [x] **H-3** Add `ALLOWED_LOCAL_DIRS` to `exports/deal-analyzer/deal_analyzer.py` `_read_local_file()`
- [x] **H-4** Add SSRF protection to `exports/deal-analyzer/deal_analyzer.py` `fetch_deck_content()`
- [x] **H-5** Pin `next-auth` to exact version in `dashboard/package.json`
- [x] **H-6** Create unprivileged `linkedin-browser` user for browser service (chromium at `/opt/`, data at `/home/linkedin-browser/`)
- [x] **H-7** Add `--remote-debugging-address=127.0.0.1` to `services/linkedin-browser.service`

## Priority 2 -- Fix This Week (MEDIUM) ✅ ALL DONE

- [x] **M-1** Add explicit `auth()` checks in `dashboard/app/api/chat/route.ts` and `services/route.ts`
- [x] **M-2** Fix `shell=True` in `lib/gws.py` `_gws_send_simple()` -- use list-based subprocess
- [x] **M-3** Add input validation (type, length) on `/api/chat` and `/api/services` routes
- [x] **M-4** Add rate limiting to dashboard API endpoints (30-60 req/min/IP)
- [x] **M-5** Request body size limits -- handled by Next.js defaults + input validation
- [x] **M-6** Pin DNS resolution in `lib/safe_url.py` to prevent TOCTOU rebinding
- [x] **M-7** Pin ALL npm dependencies to exact versions (removed caret ranges)
- [x] **M-8** Fix root `.gitignore` to use `/package-lock.json` (root-only)
- [x] **M-9** Replace hardcoded email in `lib/gws.py` with `config.assistant_email`

## Priority 3 -- Fix This Sprint (LOW) ✅ ALL DONE

- [x] **L-1** JWT session expiry reduced to 7 days (was 30 day default)
- [x] **L-2** Fix `execSync` in `lib/config.js` to use `execFileSync`
- [x] **L-3** CSRF -- confirmed covered by JSON-only parsing + SameSite=Lax cookies (no additional header needed)
- [x] **L-4** Created `lib/safe_log.py` sanitized logging utility
- [x] **L-5** Add `mode=0o700` to data directory `makedirs` calls in 3 skills
- [x] **L-6** Explicit cookie security (httpOnly, sameSite, secure) in NextAuth config
- [x] **L-7** HubSpot stage ID moved to `config.yaml` with fallback
- [x] **L-8** Removed raw user input reflection from chat API fallback response
- [x] **L-9** Improved output filename sanitization in `exports/deal-analyzer/example.py`

## Priority 4 -- Backlog (INFO)

- [ ] Document deployment process for dashboard (reverse proxy, TLS)
- [ ] Add `requirements.txt` with pinned versions for each Python skill
- [ ] Consider switching from nip.io to a real domain with TLS
