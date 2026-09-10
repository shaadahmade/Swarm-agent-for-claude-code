#!/usr/bin/env bash
# graph.sh <run-dir> [output.html]
# Renders a swarm run as a self-contained HTML page: the node-link tree, a
# timeline showing which agents ran at the same time, and the census audit.
# Defaults to writing <run-dir>/graph.html. Prints the path it wrote.
set -euo pipefail

RUN_DIR="$1"
OUT="${2:-${RUN_DIR}/graph.html}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -f "${RUN_DIR}/config.json" ]; then
  echo "graph.sh: ERROR: ${RUN_DIR} does not look like a swarm run (no config.json)" >&2
  exit 2
fi

LABEL="$(basename "${RUN_DIR}")"
mkdir -p "$(dirname "${OUT}")"
OUT_ABS="$(cd "$(dirname "${OUT}")" && pwd)/$(basename "${OUT}")"

# Run python from inside the run directory so it only ever uses relative paths.
# RUN_DIR may be an MSYS path like /c/Users/... which bash can cd into but a
# native Windows python cannot open.
cd "${RUN_DIR}"
PYTHONIOENCODING=utf-8 python3 "${SCRIPT_DIR}/graph.py" "${LABEL}" "${OUT_ABS}"
