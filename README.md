# Ruff

A pocket notebook: jot things down, stash them, and pass notes like it's recess.

## Features
- **Write:** one autosaved sheet. The first line is the title; `[ ]` lines are to-dos, shown as the Recess Roster. Lists continue on Enter. Anyone can write; drafts stay on the device until you stash them.
- **Stash:** one tap (or `Ctrl/⌘+S`) to keep a sheet; search and tag chips to find it again.
- **Pass:** Recess Relay (a story written one line each) and Nearby Share (send a stash device to device over WebRTC).
- **Teachers Lounge:** notebook / chalkboard / device theme, backup and restore, account.
- Fast and phone-first: self-hosted fonts, no third-party requests, compressed and long-cached assets, bottom tab bar on phones, two-pane layout on tablets.
- Email verification, password reset, CSRF protection, rate limiting, health checks (see [SECURITY.md](SECURITY.md)).

The product name lives in one setting (`APP_NAME`).

## Quickstart (local development)
```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt -c requirements.lock
cp .env.example .env              # set FLASK_ENV=development; dev secrets can stay empty
alembic upgrade head              # create or update the database (same as production)
python run.py                     # http://127.0.0.1:5000 (PORT/HOST to change)
```

### The full stack, as in production
```bash
cp .env.example .env              # set SECRET_KEY and SECURITY_PASSWORD_SALT
docker compose up --build         # app + PostgreSQL + Redis, http://localhost:8000
```
`compose.yaml` runs migrations once in a `release` service, then the web container read-only. Admin tasks run as one-off containers from the same image:
```bash
docker compose run --rm web flask --app "app:create_app()" purge-relays
```

## Tests
```bash
pip install -r requirements-dev.txt -c requirements.lock
python -m playwright install chromium
python -m pytest
```
The `test_e2e_*.py` files drive the real app in Chromium (shared fixtures in `conftest.py`):
- `test_e2e_flows.py`: sign-up with email verification, password reset, logout, writing before sign-up, the sheet (lists, Recess Roster, stash shortcut, autosave), search and tags, tossing, backup and restore, Recess Relay with a guest
- `test_e2e_share.py`: a real Nearby Share transfer between two tabs
- `test_e2e_visual.py`: contrast on gradient controls, and layout on phones, tablets and desktop (no sideways scrolling, 44px tap targets)
- `test_e2e_a11y.py`: an axe-core accessibility audit of every page in light and dark themes

They need network access (Socket.IO client and axe-core load from CDNs) and are skipped if Playwright isn't installed. `test_twelve_factor.py` checks config, logging and process settings.

GitHub Actions runs all of it on Python 3.12 and 3.14, applies the migrations to PostgreSQL (up, down and up again), runs the production image read-only and checks its health check and graceful shutdown, and audits every locked dependency for known vulnerabilities.

## Configuration
Everything is configured through environment variables; [.env.example](.env.example) lists and explains each one. Only `SECRET_KEY` and `SECURITY_PASSWORD_SALT` are required in production. The app refuses to start without strong values.

## Dependencies
`requirements.txt` lists the direct dependencies, pinned. `requirements.lock` pins every package, direct and indirect, as resolved in the production base image. Install with `-c requirements.lock` everywhere (the Dockerfile and CI do). After changing `requirements.txt`, regenerate the lock with `sh scripts/lock.sh` (needs Docker or Podman).

## Deploying
**Container (any platform):** build the `Dockerfile` and run it with `SECRET_KEY`, `SECURITY_PASSWORD_SALT` and `DATABASE_URL` (PostgreSQL recommended). The image:
- listens on `$PORT` (default 8000) and runs as an unprivileged user (uid 10001) on a read-only filesystem; only `/app/data` (for SQLite) and `/tmp` need to be writable
- applies migrations on start (`RUN_MIGRATIONS=0` to leave that to a release step)
- has a health check on `/readyz` (503 until the database is reachable and migrated) and shuts down gracefully on `SIGTERM`
- logs to stdout only (JSON lines; `LOG_FORMAT=console` for readable text)

**Heroku-style platforms:** the `Procfile` runs migrations in the `release` phase and the web process with `gunicorn.conf.py`. Use the platform's Postgres (`postgres://` URLs work as-is).

**More than one container:** set `RATELIMIT_STORAGE_URL` and `SOCKETIO_MESSAGE_QUEUE` to Redis, use PostgreSQL, and enable sticky sessions on the load balancer (Socket.IO needs it). Run one web worker per container (`WEB_CONCURRENCY=1`) and add containers to scale.

Also: set `PROXY_FIX_COUNT=1` behind a proxy, serve over HTTPS (or `SESSION_COOKIE_SECURE=0`), and configure SMTP if email verification is on.

## Twelve-factor
| Factor | How |
|---|---|
| I. Codebase | One repository, deployed to every environment |
| II. Dependencies | Pinned in `requirements.txt`, fully locked in `requirements.lock`, installed into an isolated virtualenv |
| III. Config | Environment variables only; nothing environment-specific in code |
| IV. Backing services | Database, Redis, SMTP and Sentry attached by URL or credentials in env; swap without code changes |
| V. Build, release, run | Image build; migrations as a release step (`Procfile` `release`, compose `release`); immutable image runs |
| VI. Processes | Stateless: sessions are signed cookies, data lives in the database, nothing kept on local disk (except optional SQLite on a volume) |
| VII. Port binding | Self-contained gunicorn server bound to `$PORT` |
| VIII. Concurrency | Scale out by adding containers; shared state in Redis (rate limits, Socket.IO) |
| IX. Disposability | Starts in about a second; graceful shutdown on `SIGTERM` |
| X. Dev/prod parity | Same migrations everywhere; `compose.yaml` runs the production image with PostgreSQL and Redis |
| XI. Logs | Event stream to stdout (JSON), no log files |
| XII. Admin processes | One-off commands in the same image and config (`alembic`, `flask purge-relays`) |

**Container practice:** single process per container, base image pinned by digest, multi-stage build, no secrets in the image (`.dockerignore`), non-root user, read-only root filesystem, health check, `EXPOSE` and OCI labels, graceful stop.

## Security
See [SECURITY.md](SECURITY.md) for the OWASP Top 10 self-assessment, known limitations, and how to report a vulnerability.

## License
MIT
