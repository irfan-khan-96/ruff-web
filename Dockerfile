# Minimal production-grade image for Ruff
FROM python:3.10-slim

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

# Default to gunicorn entrypoint; override via CMD if needed.
# Socket.IO (Nearby Share) needs every request of a client to reach the same
# process, so run ONE worker with many threads. To scale out, run more
# containers behind a sticky-session load balancer with a Socket.IO message
# queue, and set RATELIMIT_STORAGE_URL=redis://... so limits are shared.
ENV PORT=8000
CMD ["gunicorn", "app:create_app()", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "100", "--access-logfile", "-", "--error-logfile", "-"]
