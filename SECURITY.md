# Security

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub's **Security → Report a vulnerability** on this repository rather than in a public issue.

## OWASP Top 10:2025 self-assessment

Last reviewed: 2026-10-29. This is a self-assessment against the [OWASP Top 10:2025](https://owasp.org/Top10/) categories, not a third-party audit or certification. Most controls below are backed by automated tests (`test_owasp.py` is organised by category; see also `test_security.py` and the `test_e2e_*.py` browser tests); configuration-level items (CI pinning, Dependabot, Docker user) were verified by hand.

### A01 Broken Access Control
- Every stash, collection, tag, export, share and bulk action is filtered by the logged-in user; another user's stash returns 404 (tested for every route).
- Relay sessions can only be closed by their owner.
- Nearby Share (Socket.IO): logged-in users only, same-origin only, a share room holds at most two peers, only room members can send signalling messages, and join attempts are throttled (10/minute per connection) to stop share-code guessing.
- CSRF tokens on every form and JSON request; logout is a CSRF-protected POST.

### A02 Security Misconfiguration
- Production refuses to start with missing, default or short (< 32 character) `SECRET_KEY` / `SECURITY_PASSWORD_SALT`.
- Debug mode is off in production; errors show generic pages.
- Headers: Content-Security-Policy with per-request script nonces, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `Permissions-Policy`, HSTS when served over HTTPS.
- Session cookies are `HttpOnly`, `SameSite=Lax`, and `Secure` by default in production.
- Docker image: non-root user, application code not writable, `.dockerignore` keeps secrets, databases and `.git` out.
- `init_db.py` (which can drop all tables) refuses to run outside development and is excluded from the image.

### A03 Software Supply Chain Failures
- All direct dependencies are pinned; CI runs `pip-audit` on direct and transitive dependencies and fails on known vulnerabilities.
- Dependabot opens weekly update PRs for Python packages, GitHub Actions and the Docker base image.
- GitHub Actions are pinned to full commit SHAs.
- The only third-party script in the app (Socket.IO client) loads from cdnjs with Subresource Integrity.

### A04 Cryptographic Failures
- Passwords are hashed with scrypt (Werkzeug).
- Email verification and password reset links are HMAC-signed, time-limited (24 h / 1 h) and become invalid when the password changes; they carry a keyed fingerprint of the password hash, never the hash itself.
- Random values (relay codes, share codes, CSP nonces) come from cryptographically secure generators.

### A05 Injection
- All database access goes through SQLAlchemy with bound parameters.
- Templates auto-escape; no `|safe` or `innerHTML` with user data; the CSP blocks inline scripts without the request's nonce and all inline event handlers.
- Download filenames derived from user content are reduced to safe characters (no header injection).

### A06 Insecure Design
- Rate limits: login 10/minute per IP and 20/hour per account (across IPs), sign-up and email endpoints 5/minute, plus global defaults.
- Request size capped (`MAX_CONTENT_LENGTH`, default 16 MB); stash body, title and tag limits enforced on every import path.
- Expired Recess Relay sessions are deleted after `RELAY_RETENTION_DAYS`.

### A07 Authentication Failures
- Password policy: 8–128 characters for new passwords.
- Login, password reset, resend-verification and sign-up responses don't reveal whether an account or email exists; sign-up with a registered email tells the real owner by email instead. Unknown usernames take as long as wrong passwords (no timing leak).
- Sessions are renewed on login (no fixation) and invalidated everywhere when the password changes.
- Email verification required before login (configurable).

### A08 Software or Data Integrity Failures
- Subresource Integrity on the CDN script; SHA-pinned CI actions.
- JSON imports are parsed as plain data and validated (types, lengths); nothing is deserialised into code.
- The service worker caches only same-origin static files, never pages with user data.

### A09 Security Logging and Alerting Failures
- Security events are logged to the `ruff.security` logger: failed logins (username and IP, never passwords), rate-limit hits, password reset requests, invalid reset links, completed resets.
- Logs are JSON with a request ID per line.
- Email bodies (which contain account tokens) are never logged in production.
- Unhandled errors are reported to Sentry when `SENTRY_DSN` is set (no personal data sent).

### A10 Mishandling of Exceptional Conditions
- Error handlers never turn HTTP errors into misleading responses (a missing or foreign stash is a 404, an oversized request a 413, too many requests a 429).
- Failures fail closed: database or rate-limit storage errors produce an error response, not access.
- `/readyz` reports not-ready until the database is reachable and migrated.

## Known limitations and accepted risks

| Area | Status |
|---|---|
| Old database file in git history | **Action required:** commits before `8681958` contain a SQLite database with two accounts' emails and password hashes. Remove it from history (`git filter-repo`, then force-push) and have those accounts change their passwords. |
| Deployment settings | **Action required:** set strong `SECRET_KEY` / `SECURITY_PASSWORD_SALT`, serve over HTTPS (or set `SESSION_COOKIE_SECURE=0`), and `PROXY_FIX_COUNT` when behind a proxy. |
| Username enumeration at sign-up | Accepted: "username already exists" is shown, as usernames are already visible in Recess Relay. |
| Multi-factor authentication | Not implemented. |
| `style-src 'unsafe-inline'` in the CSP | Accepted: templates use inline styles; scripts remain strictly nonce-based. |
| Google Fonts stylesheet | Loaded without SRI (its CSS varies by browser); self-host the fonts to remove the dependency. |
| Rate-limit and share-join counters | Kept per process; with more than one process or host, set `RATELIMIT_STORAGE_URL=redis://...` (share-join throttling stays per process). |
| Backups | SQLite on the Docker volume is not backed up automatically; back up `/app/data` or use Postgres. |
| Account self-service | Changing email or deleting an account isn't available yet. |
| Recess Relay | By design, anyone with a relay code can read it and add lines (rate-limited); don't put private information in a relay. |
