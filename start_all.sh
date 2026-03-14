#!/usr/bin/env sh
set -eu

mkdir -p /memory
[ -f /memory/source_proposals.json ] || echo '[]' > /memory/source_proposals.json
[ -f /memory/working_theories.md ] || touch /memory/working_theories.md
[ -f /memory/stream.md ] || touch /memory/stream.md

python scripts/init_db.py >/dev/null 2>&1 || true

python -m agents.orchestrator.main &
ORCH_PID=$!
python -m agents.monitor.main &
MON_PID=$!
python -m agents.researcher.main &
RES_PID=$!
python -m agents.source_monitor.main &
SRC_PID=$!
uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8000}" &
API_PID=$!

cleanup() {
  kill "$ORCH_PID" "$MON_PID" "$RES_PID" "$SRC_PID" "$API_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

while :; do
  for pid in "$ORCH_PID" "$MON_PID" "$RES_PID" "$SRC_PID" "$API_PID"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "Process exited unexpectedly: $pid"
      cleanup
      exit 1
    fi
  done
  sleep 5
done
