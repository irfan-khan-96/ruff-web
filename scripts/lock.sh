#!/bin/sh
# Regenerate requirements.lock: every runtime dependency (direct and transitive)
# pinned, resolved inside the same base image the Dockerfile uses, so the lock
# matches the container's platform. Run after changing requirements.txt:
#   sh scripts/lock.sh            (needs docker or podman)
set -e
ENGINE=$(command -v docker || command -v podman)
IMAGE=$(sed -n 's/^ARG PYTHON_IMAGE=//p' Dockerfile)
"$ENGINE" run --rm -v "$PWD":/src -w /src "$IMAGE" sh -c '
    pip install --quiet --root-user-action=ignore pip-tools==7.6.2 &&
    pip-compile --quiet --strip-extras --no-header --resolver=backtracking \
        --output-file=requirements.lock requirements.txt'
echo "requirements.lock updated"
