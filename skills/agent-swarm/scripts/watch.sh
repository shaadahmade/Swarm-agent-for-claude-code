#!/usr/bin/env bash
# watch.sh <run-dir> [port]
# Serves a live view of a swarm run at http://127.0.0.1:<port>/ and keeps
# running until you stop it with Ctrl+C. The page polls for updates, so you can
# watch agents start, queue on the parallelism gate, and finish, in real time.
# Open it before or while the swarm runs; a run that has not started yet simply
# shows an empty tree until it does.
set -euo pipefail

RUN_DIR="$1"
PORT="${2:-8787}"
POLL_MS=1500
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -f "${RUN_DIR}/config.json" ]; then
  echo "watch.sh: ERROR: ${RUN_DIR} does not look like a swarm run (no config.json)" >&2
  exit 2
fi

LABEL="$(basename "${RUN_DIR}")"

# Serve from inside the run directory so the renderer only uses relative paths.
# RUN_DIR may be an MSYS path like /c/Users/... that bash can cd into but a
# native Windows python cannot open.
cd "${RUN_DIR}"
echo "watch.sh: serving ${LABEL} -- open the URL below, Ctrl+C to stop" >&2
exec python3 "${SCRIPT_DIR}/serve.py" "${LABEL}" "${PORT}" "${POLL_MS}"
