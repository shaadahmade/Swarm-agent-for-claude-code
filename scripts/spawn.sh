#!/usr/bin/env bash
# spawn.sh <run-dir> <node-rel-path>
# Spawns a headless Claude Code agent for the node at <run-dir>/<node-rel-path>.
# The node's task.md must already exist. Enforces global agent budget and a
# parallelism cap. Blocks until the agent finishes; guarantees status.json exists.
set -uo pipefail

RUN_DIR="$1"
NODE_REL="$2"
NODE_DIR="${RUN_DIR}/${NODE_REL}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -f "${NODE_DIR}/task.md" ]; then
  echo "spawn.sh: ERROR: ${NODE_DIR}/task.md does not exist" >&2
  exit 2
fi

cfg() { python3 -c "import json,sys;print(json.load(open('${RUN_DIR}/config.json')).get(sys.argv[1],sys.argv[2]))" "$1" "$2"; }
MAX_AGENTS=$(cfg max_agents 15)
MAX_PARALLEL=$(cfg max_parallel 3)
MODEL=$(cfg model "")
LEAF_MODEL=$(cfg leaf_model "")
MAX_DEPTH=$(cfg max_depth 3)
# Tools each spawned agent may use without a permission prompt. Headless agents
# cannot answer prompts, so anything omitted here silently blocks the agent --
# including the Bash call it needs to spawn its own children.
ALLOWED_TOOLS=$(cfg allowed_tools "Bash Read Write Edit Glob Grep")

# ---- global budget check (atomic via mkdir lock) ----
LOCK="${RUN_DIR}/.budget.lock"
acquired=0
for _ in $(seq 1 300); do
  if mkdir "${LOCK}" 2>/dev/null; then acquired=1; break; fi
  sleep 0.2
done
if [ "${acquired}" -ne 1 ]; then
  echo "spawn.sh: ERROR: could not acquire budget lock" >&2; exit 3
fi
COUNT=$(cat "${RUN_DIR}/budget.count")
if [ "${COUNT}" -ge "${MAX_AGENTS}" ]; then
  rmdir "${LOCK}"
  echo "spawn.sh: BUDGET EXHAUSTED (${COUNT}/${MAX_AGENTS}). Not spawning ${NODE_REL}. Parent must execute this task itself." >&2
  cat > "${NODE_DIR}/status.json" <<EOF
{"status": "failed", "summary": "Not spawned: global agent budget exhausted. Parent should do this task itself."}
EOF
  exit 4
fi
echo $((COUNT + 1)) > "${RUN_DIR}/budget.count"
rmdir "${LOCK}"

# ---- parallelism gate (slot files) ----
SLOTS_DIR="${RUN_DIR}/.slots"
mkdir -p "${SLOTS_DIR}"
SLOT=""
while [ -z "${SLOT}" ]; do
  for i in $(seq 1 "${MAX_PARALLEL}"); do
    if mkdir "${SLOTS_DIR}/${i}" 2>/dev/null; then SLOT="${SLOTS_DIR}/${i}"; break; fi
  done
  [ -z "${SLOT}" ] && sleep 1
done
release_slot() { rmdir "${SLOT}" 2>/dev/null || true; }
trap release_slot EXIT

# ---- compute this node's depth from its path (root=0) ----
DEPTH=$(echo "${NODE_REL}" | grep -o "children/" | wc -l | tr -d ' ')

# ---- leaf nodes may run a cheaper model ----
# Nodes at max depth must EXECUTE rather than decompose, so they do no planning
# and can often run on a smaller model. Falls back to MODEL when unset.
if [ -n "${LEAF_MODEL}" ] && [ "${DEPTH}" -ge "${MAX_DEPTH}" ]; then
  MODEL="${LEAF_MODEL}"
fi

# ---- absolute paths: an agent that cd's must still find its own node ----
NODE_ABS="$(cd "${NODE_DIR}" && pwd)"
RUN_ABS="$(cd "${RUN_DIR}" && pwd)"

# ---- build the prompt ----
PROMPT_FILE="${NODE_DIR}/.prompt.txt"
{
  echo "You are one agent node inside a recursive agent swarm."
  echo "Your node directory (ABSOLUTE): ${NODE_ABS}"
  echo "Run directory (ABSOLUTE): ${RUN_ABS}"
  echo "Your depth: ${DEPTH}   |   Max depth: ${MAX_DEPTH}"
  echo ""
  echo "Always write result.md and status.json to the ABSOLUTE node path above."
  echo "Never write them to a path relative to your current directory: if you cd"
  echo "anywhere during your work, a relative path silently lands in the wrong"
  echo "tree, your parent sees no results, and you are recorded as dead."
  echo "Spawn script for children: ${SCRIPT_DIR}/spawn.sh"
  echo ""
  echo "IMPORTANT -- how to run the spawn script: it is a bash script and the path"
  echo "above is a POSIX/MSYS path. Invoke it with your Bash tool, never PowerShell."
  echo "If your Bash tool is unavailable or the command is refused, you MUST report"
  echo "that failure per the protocol below -- never fabricate a child's results."
  echo ""
  echo "CRITICAL -- you are a headless process and are TERMINATED the moment your turn"
  echo "ends. If you spawn children, the spawns and the \`wait\` must be in ONE single"
  echo "blocking Bash call. Never end your turn with children still running, and never"
  echo "use a scheduled wakeup or deferred check to come back later -- there is no later."
  echo ""
  echo "=== YOUR TASK (from your parent) ==="
  cat "${NODE_DIR}/task.md"
  echo ""
  echo "=== SWARM NODE PROTOCOL (mandatory) ==="
  cat "${SCRIPT_DIR}/../references/node-protocol.md"
} > "${PROMPT_FILE}"

# ---- run headless claude from the repo root so paths stay consistent ----
EXTRA_ARGS=()
[ -n "${MODEL}" ] && EXTRA_ARGS+=(--model "${MODEL}")
# shellcheck disable=SC2206
[ -n "${ALLOWED_TOOLS}" ] && EXTRA_ARGS+=(--allowedTools ${ALLOWED_TOOLS})

claude -p "$(cat "${PROMPT_FILE}")" \
  --permission-mode acceptEdits \
  "${EXTRA_ARGS[@]}" \
  > "${NODE_DIR}/.agent.log" 2>&1
RC=$?

# ---- guarantee a status.json for the parent's backtrace ----
if [ ! -f "${NODE_DIR}/status.json" ]; then
  cat > "${NODE_DIR}/status.json" <<EOF
{"status": "failed", "summary": "Agent exited (code ${RC}) without writing status.json. See .agent.log."}
EOF
fi
if [ ! -f "${NODE_DIR}/result.md" ]; then
  echo "(no result.md produced -- see .agent.log)" > "${NODE_DIR}/result.md"
fi

exit 0
