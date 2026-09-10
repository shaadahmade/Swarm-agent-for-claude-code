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

# Read one key from config.json. Python runs with the run directory as its CWD
# and opens a bare filename, because RUN_DIR may be an MSYS path such as
# /c/Users/... which bash can cd into but a native Windows python cannot open.
cfg() { ( cd "${RUN_DIR}" && python3 -c "import json,sys;print(json.load(open('config.json')).get(sys.argv[1],sys.argv[2]))" "$1" "$2" 2>/dev/null ); }
MAX_AGENTS=$(cfg max_agents 15)
MAX_PARALLEL=$(cfg max_parallel 3)
MODEL=$(cfg model "")
LEAF_MODEL=$(cfg leaf_model "")
MAX_DEPTH=$(cfg max_depth 3)
# Tools each spawned agent may use without a permission prompt. Headless agents
# cannot answer prompts, so anything omitted here silently blocks the agent --
# including the Bash call it needs to spawn its own children.
ALLOWED_TOOLS=$(cfg allowed_tools "Bash Read Write Edit Glob Grep")

# A config that cannot be read yields empty numbers, and an empty max_parallel
# makes the slot loop below spin forever. Fail loudly instead of hanging.
for _v in MAX_AGENTS MAX_PARALLEL MAX_DEPTH; do
  eval "_val=\${${_v}}"
  case "${_val}" in
    ''|*[!0-9]*)
      echo "spawn.sh: ERROR: ${_v} is '${_val}', expected a number." >&2
      echo "spawn.sh: could not read ${RUN_DIR}/config.json" >&2
      exit 5;;
  esac
done

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
SLOT_RELEASED=0
release_slot() {
  [ "${SLOT_RELEASED}" -eq 1 ] && return 0
  rmdir "${SLOT}" 2>/dev/null || true
  SLOT_RELEASED=1
}
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
  > "${NODE_DIR}/.agent.log" 2>&1 &
AGENT_PID=$!

# Once this node has written task files for its own children it is no longer
# working, it is blocked waiting for them. A blocked parent that keeps holding
# a slot deadlocks the swarm: every slot ends up held by a parent waiting on
# children who can never get a slot of their own. So release the slot as soon
# as this node becomes a parent. The cap then limits agents doing actual work
# rather than agents merely existing.
while kill -0 "${AGENT_PID}" 2>/dev/null; do
  if [ "${SLOT_RELEASED}" -eq 0 ] && compgen -G "${NODE_DIR}/children/*/task.md" >/dev/null 2>&1; then
    release_slot
  fi
  sleep 1
done
wait "${AGENT_PID}"
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
