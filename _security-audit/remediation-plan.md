# Security Remediation Plan

**Date:** 2026-03-05

---

## Priority 1 -- Fix Today (HIGH)

- [ ] **H-1** Fix `shell=True` command injection in `lib/gws.py` `run_gws()` -- use list-based subprocess
- [ ] **H-2** Add HTTP security headers to `dashboard/next.config.ts`
- [ ] **H-3** Add `ALLOWED_LOCAL_DIRS` to `exports/deal-analyzer/deal_analyzer.py` `_read_local_file()`
- [ ] **H-4** Add SSRF protection to `exports/deal-analyzer/deal_analyzer.py` `fetch_deck_content()`
- [ ] **H-5** Pin `next-auth` to exact version in `dashboard/package.json`
- [ ] **H-6** Create unprivileged user for `services/linkedin-browser.service` (manual server task)
- [ ] **H-7** Add `--remote-debugging-address=127.0.0.1` to `services/linkedin-browser.service`

## Priority 2 -- Fix This Week (MEDIUM)

- [ ] **M-1** Add explicit `auth()` checks in `dashboard/app/api/chat/route.ts` and `services/route.ts`
- [ ] **M-2** Fix `shell=True` in `lib/gws.py` `_gws_send_simple()` -- use `shlex.quote()`
- [ ] **M-3** Add input validation (type, length) on `/api/chat` route
- [ ] **M-4** Add rate limiting to dashboard API endpoints
- [ ] **M-5** Add request body size limits
- [ ] **M-6** Pin DNS resolution in `lib/safe_url.py` to prevent TOCTOU rebinding
- [ ] **M-7** Pin security-critical npm dependencies to exact versions
- [ ] **M-8** Fix root `.gitignore` to use `/package-lock.json` (root-only)
- [ ] **M-9** Replace hardcoded email in `lib/gws.py:385` with `config.assistant_email`

## Priority 3 -- Fix This Sprint (LOW)

- [ ] **L-1** Evaluate JWT session expiry (currently 30 days default)
- [ ] **L-2** Fix `execSync` in `lib/config.js` to use `execFileSync`
- [ ] **L-3** Add CSRF custom header check for defense-in-depth
- [ ] **L-4** Create sanitized logging utility for Python scripts
- [ ] **L-5** Add `mode=0o700` to data directory `makedirs` calls in 3 skills
- [ ] **L-6** Add explicit cookie security options in NextAuth config
- [ ] **L-7** Move HubSpot stage ID from hardcoded to config.yaml
- [ ] **L-8** Truncate user message before echoing in chat API
- [ ] **L-9** Improve output filename sanitization in `exports/deal-analyzer/example.py`

## Priority 4 -- Backlog (INFO)

- [ ] Document deployment process for dashboard (reverse proxy, TLS)
- [ ] Add `requirements.txt` with pinned versions for each Python skill
- [ ] Consider switching from nip.io to a real domain with TLS
