#!/bin/sh
# A configured seed failure prevents startup. An embedded worker is supervised.
set -e
cd /app
python /app/ops/seed_on_start.py
case "$(echo "${SCOOBY_EMBEDDED_WORKER:-}" | tr '[:upper:]' '[:lower:]')" in
  1|true|yes|on)
    python -m huey.bin.huey_consumer worker.huey -w 1 &
    worker_pid=$!
    python -m uvicorn app:app --host 0.0.0.0 --port "${PORT:-8000}" &
    api_pid=$!
    trap 'kill "$api_pid" "$worker_pid" 2>/dev/null || true' EXIT INT TERM
    while kill -0 "$api_pid" 2>/dev/null && kill -0 "$worker_pid" 2>/dev/null; do sleep 2; done
    echo "api or embedded worker exited; stopping container" >&2
    exit 1
    ;;
  *) exec python -m uvicorn app:app --host 0.0.0.0 --port "${PORT:-8000}" ;;
esac
