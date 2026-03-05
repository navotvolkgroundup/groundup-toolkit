# Security Scorecard

**Date:** 2026-03-05

| Category | Score | Notes |
|---|---|---|
| Secrets & Credentials | :green_circle: | No hardcoded secrets in git. `.env` gitignored. Clean git history. Google cookies properly permissioned (0o600). |
| Authentication | :yellow_circle: | Google OAuth with domain restriction is solid. JWT sessions lack revocation. API routes rely solely on middleware (no handler-level checks). NextAuth beta version. |
| Authorization | :green_circle: | Binary access model (authenticated @groundup.vc or not). No IDOR risk — dashboard serves same data to all users. |
| Input Validation | :yellow_circle: | SQL queries parameterized (good). No XSS vectors. But API routes lack type/length validation. `shell=True` with string interpolation in gws.py. |
| API Security | :yellow_circle: | No security headers. No rate limiting. No body size limits. CORS defaults are secure. CSRF covered by SameSite cookies. |
| Data Protection | :green_circle: | No sensitive data in client responses. Error messages are generic. No console.log in dashboard. Minor risk in Python error logging. |
| Dependencies | :yellow_circle: | next-auth beta is a risk. Floating version ranges. Lock file committed but gitignore conflict. Python deps mostly unpinned. |
| Infrastructure | :red_circle: | Browser runs as root without sandbox. CDP port exposure risk. No reverse proxy/TLS. Dashboard port directly exposed. |
| **Overall** | :yellow_circle: | **Good fundamentals, needs hardening.** Secret management is strong. Auth flow is sound. Main gaps: infrastructure hardening, security headers, input validation, and shell injection in gws.py. |
