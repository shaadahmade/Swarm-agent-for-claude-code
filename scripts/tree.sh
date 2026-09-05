#!/usr/bin/env bash
# tree.sh <run-dir>
# Prints the swarm tree with each node's status -- the civilization census.
# Also audits the census: nodes with no spawn evidence are flagged as phantoms.
set -euo pipefail
RUN_DIR="$1"

PYTHONIOENCODING=utf-8 python3 - "$RUN_DIR" <<'EOF'
import json, os, sys
run = sys.argv[1]

real, phantom = [], []

def walk(node_dir, label, indent, is_root=False):
    status, summary = "…running", ""
    sp = os.path.join(node_dir, "status.json")
    if os.path.exists(sp):
        try:
            s = json.load(open(sp, encoding="utf-8"))
            status, summary = s.get("status", "?"), s.get("summary", "")[:80]
        except Exception:
            status = "corrupt-status"
    # A node is "real" only if spawn.sh actually launched an agent for it.
    spawned = os.path.exists(os.path.join(node_dir, ".agent.log"))
    (real if spawned else phantom).append(label)
    tag = "" if spawned else "  <-- PHANTOM: no agent ever ran here"
    mark = {"success": "[ok]", "partial": "[~ ]", "failed": "[XX]"}.get(status, "[..]")
    print(f"{indent}{mark} {label}  {('- ' + summary) if summary else ''}{tag}")
    cdir = os.path.join(node_dir, "children")
    if os.path.isdir(cdir):
        for c in sorted(os.listdir(cdir)):
            if os.path.isdir(os.path.join(cdir, c)):
                walk(os.path.join(cdir, c), c, indent + "    ")

root = os.path.join(run, "nodes", "root")
bp = os.path.join(run, "budget.count")
count = open(bp).read().strip() if os.path.exists(bp) else "?"
cfg = json.load(open(os.path.join(run, "config.json"), encoding="utf-8"))
print(f"Swarm {run} — agents spawned: {count}/{cfg['max_agents']}")
walk(root, "root (master)", "", is_root=True)

# ---- census audit ----
print()
total = len(real) + len(phantom)
print(f"Census: {total} node(s) on disk | {len(real)} with a live agent | {len(phantom)} phantom")
if phantom:
    print(f"WARNING: {len(phantom)} node(s) have results but no agent ever ran: {', '.join(phantom)}")
    print("         Their parent wrote those files by hand. Treat the results as unverified.")
try:
    if int(count) < len(real):
        print(f"WARNING: budget.count ({count}) is lower than nodes with agents ({len(real)}) — counter may be corrupt.")
except ValueError:
    pass
EOF
