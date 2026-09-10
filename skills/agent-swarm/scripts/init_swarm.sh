#!/usr/bin/env bash
# init_swarm.sh <run-name> [config-json]
# Creates swarm/<run-id>/ with config, budget counter, and the root node.
#
# The master agent sizes the swarm itself by passing a JSON object as the second
# argument, e.g.:
#   init_swarm.sh research '{"max_agents":8,"max_depth":2,"rationale":"..."}'
# Any key omitted falls back to the default below. Every value is clamped to a
# hard ceiling so an autonomous agent cannot start a runaway swarm.
set -euo pipefail

NAME="${1:-run}"
OVERRIDES="${2:-{\}}"
RUN_ID="$(date +%Y%m%d-%H%M%S)-${NAME}"
RUN_DIR="swarm/${RUN_ID}"

mkdir -p "${RUN_DIR}/nodes/root/children"

OVERRIDES="${OVERRIDES}" python3 - "${RUN_DIR}" <<'EOF'
import json, os, sys

run_dir = sys.argv[1]

DEFAULTS = {
    "max_depth": 3,
    "max_children": 4,
    "max_agents": 15,
    "max_parallel": 3,
    "model": "",
    "leaf_model": "",
    "allowed_tools": "Bash Read Write Edit Glob Grep",
    "rationale": "",
}

# Hard ceilings. These bound autonomous sizing: the master may choose anything
# up to these, never past them. Raise them only deliberately.
CEILINGS = {"max_depth": 5, "max_children": 6, "max_agents": 40, "max_parallel": 8}
FLOORS = {"max_depth": 0, "max_children": 2, "max_agents": 1, "max_parallel": 1}

raw = os.environ.get("OVERRIDES", "").strip() or "{}"
try:
    chosen = json.loads(raw)
except json.JSONDecodeError as e:
    sys.exit(f"init_swarm.sh: config override is not valid JSON: {e}")
if not isinstance(chosen, dict):
    sys.exit("init_swarm.sh: config override must be a JSON object")

unknown = set(chosen) - set(DEFAULTS)
if unknown:
    sys.exit(f"init_swarm.sh: unknown config key(s): {', '.join(sorted(unknown))}")

cfg, notes = dict(DEFAULTS), []
for k, v in chosen.items():
    if k in CEILINGS:
        try:
            v = int(v)
        except (TypeError, ValueError):
            sys.exit(f"init_swarm.sh: {k} must be an integer, got {v!r}")
        lo, hi = FLOORS[k], CEILINGS[k]
        if v > hi:
            notes.append(f"{k} requested {v}, clamped to ceiling {hi}")
            v = hi
        elif v < lo:
            notes.append(f"{k} requested {v}, raised to floor {lo}")
            v = lo
    cfg[k] = v

# A swarm can never spawn more agents than its own budget allows.
if cfg["max_parallel"] > cfg["max_agents"]:
    cfg["max_parallel"] = cfg["max_agents"]

json.dump(cfg, open(os.path.join(run_dir, "config.json"), "w"), indent=2)
for n in notes:
    print(f"init_swarm.sh: {n}", file=sys.stderr)
EOF

echo 0 > "${RUN_DIR}/budget.count"
touch "${RUN_DIR}/nodes/root/task.md"

echo "${RUN_DIR}"
