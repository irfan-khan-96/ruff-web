# Security

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub's **Security → Report a vulnerability** on this repository rather than in a public issue.

## OWASP Top 10:2025 self-assessment

Last reviewed: 2026-10-29. This is a self-assessment against the [OWASP Top 10:2025](https://owasp.org/Top10/) categories, not a third-party audit or certification. Most controls below are backed by automated tests (`test_owasp.py` is organised by category; see also `test_security.py` and the `test_e2e_*.py` browser tests); configuration-level items (CI pinning, Dependabot, Docker user) were verified by hand.

### A01 Broken Access Control
- Every stash, tag, export and share action is filtered by the logged-in user; another user's stash returns 404, and saving over it is refused (tested for every route).
- Relay sessions can only be closed by their owner.
- Nearby Share (Socket.IO): logged-in users only, same-origin only, a share room holds at most two peers, only room members can send signalling messages, and join attempts are throttled (10/minute per connection) to stop share-code guessing.
- CSRF tokens on every form and JSON request; logout is a CSRF-protected POST.

### A02 Security Misconfiguration
- Production refuses to start with missing, default or short (< 32 character) `SECRET_KEY` / `SECURITY_PASSWORD_SALT`.
- Debug mode is off in production; errors show generic pages.
- Headers: Content-Security-Policy with per-request script nonces, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `Permissions-Policy`, HSTS when served over HTTPS.
- Session cookies are `HttpOnly`, `SameSite=Lax`, and `Secure` by default in production.
- Docker image: base pinned by digest, multi-stage build, non-root user, read-only root filesystem supported, application code not writable, `.dockerignore` keeps secrets, databases and `.git` out.

### A03 Software Supply Chain Failures
- Direct dependencies are pinned in `requirements.txt` and every transitive one in `requirements.lock`; the image and CI install from the lock. CI runs `pip-audit` on the lock and fails on known vulnerabilities.
- Dependabot opens weekly update PRs for Python packages, GitHub Actions and the Docker base image.
- GitHub Actions are pinned to full commit SHAs.
- The only third-party resource is the Socket.IO client on the Pass page, loaded from cdnjs with Subresource Integrity. Fonts are self-hosted.

### A04 Cryptographic Failures
- No passwords are stored or accepted. Sign-in links are HMAC-signed, expire after 15 minutes, and are single-use (a per-account nonce, rotated on every request and on use).
- Folded notes are encrypted in the sender's browser (AES-GCM, 256-bit). The key travels only in the link's `#fragment`, which browsers never send to servers, so the server stores and serves ciphertext it cannot read. The note is deleted in the same statement that hands it over.
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
- Passwordless sign-in removes password guessing, reuse, stuffing and reset attacks.
- Requesting a link gives the same answer whether or not the address has an account (no enumeration). Links are limited to 5 a minute per IP and 10 an hour per address.
- Opening a link only shows a confirmation button; signing in is a separate POST, so email scanners that pre-open links can't use them up.
- Sessions are renewed on sign-in (no fixation); "Sign out everywhere" invalidates every session at once.

### A08 Software or Data Integrity Failures
- Subresource Integrity on the CDN script; SHA-pinned CI actions.
- JSON imports are parsed as plain data and validated (types, lengths); nothing is deserialised into code.
- The service worker caches only same-origin static files, never pages with user data.

### A09 Security Logging and Alerting Failures
- Security events are logged to the `ruff.security` logger: sign-in link requests, unusable (expired, reused or forged) links, sign-ins, sign-outs everywhere, folded notes opened, and rate-limit hits.
- Logs go to stdout as JSON, one event per line with its request ID; nothing is written to local files.
- Email bodies (which contain sign-in links) are never logged in production; `MAIL_TO_LOG` exists only for local stacks without SMTP.
- Unhandled errors are reported to Sentry when `SENTRY_DSN` is set (no personal data sent).

### A10 Mishandling of Exceptional Conditions
- Error handlers never turn HTTP errors into misleading responses (a missing or foreign stash is a 404, an oversized request a 413, too many requests a 429).
- Failures fail closed: database or rate-limit storage errors produce an error response, not access.
- `/readyz` reports not-ready until the database is reachable and migrated.

## Known limitations and accepted risks

| Area | Status |
|---|---|
| Old database file in git history | **Action required:** commits before `8681958` contain a SQLite database with two accounts' emails and password hashes. Remove it from history (`git filter-repo`, then force-push). Passwords are no longer used here, so the hashes can't sign anyone in, but those two people should change that password anywhere else they reused it. |
| Deployment settings | **Action required:** set strong `SECRET_KEY` / `SECURITY_PASSWORD_SALT`, serve over HTTPS (or set `SESSION_COOKIE_SECURE=0`), and `PROXY_FIX_COUNT` when behind a proxy. |
| Multi-factor authentication | Not implemented; sign-in strength equals the email account's. Passkeys would be the next step. |
| `style-src 'unsafe-inline'` in the CSP | Accepted: templates use inline styles; scripts remain strictly nonce-based. |
| Rate-limit and share-join counters | Kept per process; with more than one process or host, set `RATELIMIT_STORAGE_URL=redis://...` (share-join throttling stays per process). |
| Backups | SQLite on the Docker volume is not backed up automatically; back up `/app/data` or use Postgres. |
| Account self-service | Changing email or deleting an account isn't available yet. |
| Recess Relay | By design, anyone with a relay code can read it and add lines (rate-limited); don't put private information in a relay. |
| Notes on the device | Local-first: notes are stored in the browser (IndexedDB) and readable by anyone using that browser profile. Signing out syncs, then clears them from the device. |
| Folded notes | Anyone holding the full link can open the note once; share links privately. Unopened notes expire after `FOLD_TTL_DAYS` (default 7). |
| Email account | Whoever controls your inbox can sign in; that's the trade-off of passwordless links. |
