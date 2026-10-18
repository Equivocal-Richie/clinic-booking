#!/usr/bin/env bash
set -euo pipefail

# Apply database migrations before serving. Safe to run on every boot:
# "alembic upgrade head" is a no-op when already at head.
echo "Running database migrations..."
alembic upgrade head

# Optional one-time seed of doctors/working hours. Idempotent.
if [ "${SEED_ON_START:-false}" = "true" ]; then
  echo "Seeding database..."
  python -m scripts.seed
fi

WORKERS="${WEB_CONCURRENCY:-2}"
PORT="${PORT:-8000}"
echo "Starting gunicorn on :${PORT} with ${WORKERS} workers..."
exec gunicorn app.main:app \
  -k uvicorn.workers.UvicornWorker \
  -w "${WORKERS}" \
  -b "0.0.0.0:${PORT}" \
  --access-logfile - \
  --error-logfile -
