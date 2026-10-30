"""
Gunicorn settings, all from the environment (twelve-factor III, VII, IX).
Used by both the Dockerfile and the Procfile: `gunicorn -c gunicorn.conf.py`.
"""

import os

# VII Port binding: the platform says where to listen
bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"

# VIII Concurrency: processes x threads. The app is stateless, so add workers
# or containers freely; with more than one process, point RATELIMIT_STORAGE_URL
# at Redis so rate limits are shared.
workers = int(os.getenv("WEB_CONCURRENCY", "1"))
threads = int(os.getenv("GUNICORN_THREADS", "16"))

# IX Disposability: finish in-flight requests on SIGTERM, then exit
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", "20"))
timeout = int(os.getenv("GUNICORN_TIMEOUT", "60"))

# XI Logs: access and error logs to stdout/stderr
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info").lower()

# Heartbeat files in memory, so the container can run with a read-only root filesystem
worker_tmp_dir = "/dev/shm" if os.path.isdir("/dev/shm") else None

# Trust X-Forwarded-* only as configured in the app (PROXY_FIX_COUNT)
forwarded_allow_ips = os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1")
