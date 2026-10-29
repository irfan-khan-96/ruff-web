# Ruff

Ruff is a Flask app for stashing notes with titles, body text, and a task note.

## Features
- Titles + body stashes with previews
- Task notes (checklists) attached to stashes
- Tags and collections
- Import/export (JSON + text)
- Nearby Share (WebRTC + Socket.IO)
- Email verification and password reset
- Light/dark themes and PWA support
- CSRF protection, rate limiting, health checks

## Quickstart
1. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate
```
2. Install dependencies:
```bash
pip install -r requirements.txt
```
3. Configure environment:
```bash
cp .env.example .env
```
Edit `.env` and set `SECRET_KEY` and `SECURITY_PASSWORD_SALT` (the app refuses to start in production without them). Generate each with:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```
4. Initialize the database:
```bash
alembic upgrade head
```
For a fresh dev-only database without migrations:
```bash
python init_db.py init
```
5. Run the app:
```bash
python run.py
```
6. Open `http://localhost:5000` in the browser.

## Tests
```bash
pip install -r requirements-dev.txt
python -m playwright install chromium
python -m pytest
```
The `test_e2e_*.py` files drive the real app in Chromium (shared fixtures in `conftest.py`):
- `test_e2e_flows.py`: sign-up with email verification, password reset, logout, stash create/search/edit/delete with task notes, collections and bulk actions, export/import, Recess Relay with a guest
- `test_e2e_share.py`: a real Nearby Share transfer between two tabs
- `test_e2e_a11y.py`: an axe-core accessibility audit of every page in light and dark themes

They need network access (Socket.IO client and axe-core load from CDNs) and are skipped if Playwright isn't installed. GitHub Actions runs everything on each push.

## Configuration
Key environment variables in `.env`:
- `FLASK_ENV`: `development`, `testing`, or `production`
- `DATABASE_URL`: defaults to `sqlite:///./ruff.db`
- `SECRET_KEY`: session signing key
- `SECURITY_PASSWORD_SALT`: token signing salt
- `REQUIRE_EMAIL_VERIFICATION`: require email verification before login
- `RATELIMIT_STORAGE_URL`: rate limiting backend (default `memory://`; use `redis://...` when running more than one process)
- `PROXY_FIX_COUNT`: number of reverse proxies in front of the app (default `0`; `1` on Heroku/Render or behind nginx) so rate limits see real client IPs
- `MAX_CONTENT_LENGTH`: largest accepted request body in bytes (default 16 MB)
- `SOCKETIO_CORS_ORIGINS`: extra origins allowed to use Nearby Share's Socket.IO (default: same origin only)
- `RELAY_RETENTION_DAYS`: days before Recess Relay sessions and their lines are deleted (default `30`). Expired relays are removed whenever a new relay starts; to clean up on a schedule run `flask --app "app:create_app()" purge-relays`

Run a single gunicorn worker with threads (see `Procfile`): Socket.IO needs every request from a client to reach the same process.
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`
- `SMTP_USE_TLS`, `SMTP_USE_SSL`

## Database
SQLite is used by default. For PostgreSQL:
1. Install the driver:
```bash
pip install psycopg2-binary
```
2. Set `DATABASE_URL`:
```
DATABASE_URL=postgresql://user:password@localhost/ruff
```
3. Run migrations:
```bash
alembic upgrade head
```

## Stop and Clean
1. Stop the dev server: press `Ctrl+C` in the terminal running `python run.py`.
2. If the port is still busy:
```bash
lsof -i tcp:5000
kill <PID>
```
3. Clean local artifacts and reset data:
```bash
rm -f logs/ruff.log
find . -name "__pycache__" -type d -prune -exec rm -rf {} +
rm -f ruff.db instance/ruff.db
```
4. Recreate the schema:
```bash
alembic upgrade head
```

## Production Notes
- Set strong `SECRET_KEY` and `SECURITY_PASSWORD_SALT` values.
- Configure SMTP if email verification/reset is enabled.
- Use a production WSGI server (example: `gunicorn`).
- Run migrations during deploy: `alembic upgrade head`. The `Procfile` does this in its `release` step; the Docker image does it on start (set `RUN_MIGRATIONS=0` to skip).
- `/readyz` returns 503 until the database is reachable and migrated.

### Docker
```bash
docker build -t ruff .
docker run -p 8000:8000 -v ruff-data:/app/data \
  -e SECRET_KEY=... -e SECURITY_PASSWORD_SALT=... ruff
```
The container runs as an unprivileged user, keeps the SQLite database on the `/app/data` volume, and has a health check on `/readyz`. Without HTTPS in front of it, also pass `-e SESSION_COOKIE_SECURE=0` or logins won't stick.

## License
MIT
