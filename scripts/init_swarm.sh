#!/usr/bin/env bash
# init_swarm.sh <run-name>
# Creates swarm/<run-id>/ with config, budget counter, and the root node.
set -euo pipefail

NAME="${1:-run}"
RUN_ID="$(date +%Y%m%d-%H%M%S)-${NAME}"
RUN_DIR="swarm/${RUN_ID}"

mkdir -p "${RUN_DIR}/nodes/root/children"

cat > "${RUN_DIR}/config.json" <<'EOF'
{
  "max_depth": 3,
  "max_children": 4,
  "max_agents": 15,
  "max_parallel": 3,
  "model": "",
  "allowed_tools": "Bash Read Write Edit Glob Grep"
}
EOF

echo 0 > "${RUN_DIR}/budget.count"
touch "${RUN_DIR}/nodes/root/task.md"

echo "${RUN_DIR}"
