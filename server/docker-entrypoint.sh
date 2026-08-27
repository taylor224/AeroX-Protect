#!/bin/sh
# Backend init: create schema + seed + first admin (idempotent). Gated so the
# Celery worker (same image) does NOT re-run it — only the backend sets AXP_DB_INIT=true.
set -e

if [ "${AXP_DB_INIT:-false}" = "true" ]; then
  echo "[entrypoint] db-upgrade + seed + seed-admin"
  python -m server.command db-upgrade
  python -m server.command seed
  python -m server.command seed-admin
fi

exec "$@"
