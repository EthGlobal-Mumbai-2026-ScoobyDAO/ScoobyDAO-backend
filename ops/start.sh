#!/bin/sh
# Container entrypoint: optional report seed, optional in-container worker, then the API.
# SCOOBY_SEED_ARCHIVE unset -> no seed. SCOOBY_EMBEDDED_WORKER unset -> no worker (Compose runs its own worker service).
cd /app
python /app/ops/seed_on_start.py || echo "seed: continuing without it"
# SCOOBY_DISPLAY_ONLY=true never starts a worker, whatever SCOOBY_EMBEDDED_WORKER says.
case "$(echo "${SCOOBY_DISPLAY_ONLY:-}" | tr '[:upper:]' '[:lower:]')" in
  1|true|yes|on) [ -n "${SCOOBY_EMBEDDED_WORKER:-}" ] && echo "worker: not started (SCOOBY_DISPLAY_ONLY)"; SCOOBY_EMBEDDED_WORKER= ;;
esac
case "$(echo "${SCOOBY_EMBEDDED_WORKER:-}" | tr '[:upper:]' '[:lower:]')" in
  1|true|yes|on)
    echo "worker: starting in this container"
    python -m huey.bin.huey_consumer worker.huey -w 1 &
    ;;
esac
exec python -m uvicorn app:app --host 0.0.0.0 --port "${PORT:-8000}"
