#!/usr/bin/env bash
# init_swarm.sh <run-name> [config-json]
# Creates swarm/<run-id>/ with config, budget counter, and the root node.
#
# The master agent sizes the swarm itself by passing a JSON object as the second
# argument, e.g.:
#   init_swarm.sh research '{"max_agents":8,"max_depth":2,"rationale":"..."}'
# Any key omitted falls back to the default below. There are no ceilings: the
# master agent owns every one of these decisions. A run is bounded only by
# max_agents, which the master also chooses.
set -euo pipefail

NAME="${1:-run}"
OVERRIDES="${2:-{\}}"
RUN_ID="$(date +%Y%m%d-%H%M%S)-${NAME}"
RUN_DIR="swarm/${RUN_ID}"

mkdir -p "${RUN_DIR}/nodes/root/children"

OVERRIDES="${OVERRIDES}" python3 - "${RUN_DIR}" <<'EOF'
import json, os, sys

run_dir = sys.argv[1]

# Fallbacks only. The master agent is expected to choose every one of these from
# the shape of the goal; these values apply when it passes nothing at all.
# max_parallel 0 means no parallelism gate: every spawn runs immediately.
DEFAULTS = {
    "max_depth": 3,
    "max_children": 4,
    "max_agents": 15,
    "max_parallel": 0,
    "model": "",
    "leaf_model": "",
    "allowed_tools": "Bash Read Write Edit Glob Grep",
    "rationale": "",
}

# Values that must be whole numbers. There are no ceilings: the master owns
# these decisions, and a run is bounded by max_agents, which it also chooses.
NUMERIC = ("max_depth", "max_children", "max_agents", "max_parallel")

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

cfg = dict(DEFAULTS)
for k, v in chosen.items():
    if k in NUMERIC:
        try:
            v = int(v)
        except (TypeError, ValueError):
            sys.exit(f"init_swarm.sh: {k} must be an integer, got {v!r}")
        if v < 0:
            sys.exit(f"init_swarm.sh: {k} cannot be negative, got {v}")
    cfg[k] = v

if cfg["max_agents"] < 1:
    sys.exit("init_swarm.sh: max_agents must be at least 1")

json.dump(cfg, open(os.path.join(run_dir, "config.json"), "w"), indent=2)
EOF

echo 0 > "${RUN_DIR}/budget.count"
touch "${RUN_DIR}/nodes/root/task.md"

echo "${RUN_DIR}"
