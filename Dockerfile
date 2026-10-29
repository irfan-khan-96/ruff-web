# Minimal production-grade image for Ruff
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (add build-essential if native deps appear later)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as an unprivileged user; it owns only what the app writes:
# /app/data (SQLite database) and /app/logs
RUN useradd --create-home --uid 10001 ruff \
    && mkdir -p /app/data /app/logs \
    && chown ruff:ruff /app/data /app/logs \
    && chmod +x /app/docker-entrypoint.sh
USER ruff

# SQLite lives on a volume so data survives container restarts.
# Point DATABASE_URL at Postgres instead for anything beyond a single host.
ENV DATABASE_URL=sqlite:////app/data/ruff.db
VOLUME ["/app/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD curl -fsS http://127.0.0.1:8000/readyz || exit 1

# The entrypoint applies migrations before starting the app.
ENTRYPOINT ["/app/docker-entrypoint.sh"]

# Socket.IO (Nearby Share) needs every request of a client to reach the same
# process, so run ONE worker with many threads. To scale out, run more
# containers behind a sticky-session load balancer with a Socket.IO message
# queue, and set RATELIMIT_STORAGE_URL=redis://... so limits are shared.
ENV PORT=8000
EXPOSE 8000
CMD ["gunicorn", "app:create_app()", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "100", "--access-logfile", "-", "--error-logfile", "-"]
