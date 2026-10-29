#!/bin/sh
# Apply database migrations, then start the app (the image's CMD).
# Set RUN_MIGRATIONS=0 to skip, e.g. when a separate release step runs them.
set -e

if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
    alembic upgrade head
fi

exec "$@"
