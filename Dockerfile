# Ruff production image.
# Base pinned by digest for reproducible builds (Dependabot proposes updates).
ARG PYTHON_IMAGE=docker.io/library/python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159

# --- Build stage: dependencies into a virtualenv (pip and its cache stay here)
FROM ${PYTHON_IMAGE} AS build
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
COPY requirements.txt requirements.lock ./
# Every package, direct and transitive, at the version in requirements.lock
RUN /opt/venv/bin/pip install --root-user-action=ignore -r requirements.txt -c requirements.lock

# --- Runtime stage
FROM ${PYTHON_IMAGE}
ARG VERSION=dev
LABEL org.opencontainers.image.title="Ruff" \
      org.opencontainers.image.description="A pocket notebook: write, stash, and pass notes." \
      org.opencontainers.image.source="https://github.com/irfan-khan-96/ruff-web" \
      org.opencontainers.image.version="${VERSION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    PORT=8000 \
    DATABASE_URL=sqlite:////app/data/ruff.db

# Unprivileged user; the code is root-owned and read-only to it. The only
# writable path is /app/data (SQLite, when no external DATABASE_URL is set).
RUN useradd --uid 10001 --home-dir /app --no-create-home --shell /usr/sbin/nologin ruff
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY . .
RUN mkdir -p /app/data && chown ruff:ruff /app/data && chmod 0755 /app/docker-entrypoint.sh
USER 10001:10001

VOLUME ["/app/data"]
EXPOSE 8000

# Readiness: the database is reachable and migrated
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/readyz' % os.environ.get('PORT', '8000'), timeout=4)"]

# gunicorn (PID 1 via exec in the entrypoint) shuts down gracefully on SIGTERM
STOPSIGNAL SIGTERM
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:create_app()"]
