#!/usr/bin/env sh
set -eu

mkdir -p /memory

python scripts/init_db.py >/dev/null 2>&1 || true

python -m agents.researcher.main &
RES_PID=$!
uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8000}" &
API_PID=$!

cleanup() {
  kill "$RES_PID" "$API_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

while :; do
  for pid in "$RES_PID" "$API_PID"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "Process exited unexpectedly: $pid"
      cleanup
      exit 1
    fi
  done
  sleep 5
done
