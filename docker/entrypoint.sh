#!/bin/sh
# Runs from WORKDIR=/usr/src/app/ellington_web (alongside manage.py).
# Performs Django startup then exec's CMD (daphne in production).

set -e

# Skip makemigrations in production — migrations are committed to the
# repo and only ever applied here, never authored. `makemigrations` at
# runtime is a footgun (it'd write into the read-only image FS anyway).
python3 manage.py ensure_paths || true   # GST-provided; create runtime dirs
python3 manage.py migrate --noinput
python3 manage.py collectstatic --no-input

exec "$@"
