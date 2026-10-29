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

## Testing
```bash
pytest -q
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
- Run migrations during deploy: `alembic upgrade head`.

## License
MIT
