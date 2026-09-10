# Swarm Architecture & Debugging

## Why this design

| Choice | Reason |
|---|---|
| `claude -p` per node instead of Task tool | Task subagents can't spawn subagents; headless CLI instances can, enabling unlimited recursion. |
| Filesystem as message bus | Processes share no memory. Files (`task.md` down, `result.md`/`status.json` up) are the only channel — inspectable, resumable, crash-tolerant. |
| Node path = identity | `nodes/root/children/2/children/1` encodes lineage; the backtrace route is literally the directory path upward. |
| Global budget counter with mkdir lock | mkdir is atomic on POSIX — a portable mutex with zero dependencies, preventing fork-bomb civilizations. |
| Slot-based parallelism gate | Caps concurrent `claude` processes across the WHOLE tree (not per parent), avoiding API rate limits. |
| Parent-side guarantees in spawn.sh | Even if a child crashes, the parent always finds status.json/result.md — no hung aggregation. |

## Lifecycle of one node

1. Parent writes `children/<i>/task.md`
2. Parent runs `spawn.sh <run-dir> <path>` (backgrounded)
3. spawn.sh: budget check → parallel slot wait → assemble prompt (task.md + node-protocol.md + depth info) → run `claude -p`
4. Child decides EXECUTE/DECOMPOSE, possibly recursing via the same spawn.sh
5. Child writes result.md + status.json; spawn.sh backfills them if missing
6. Parent's `wait` returns; parent reads children bottom-up and synthesizes

## Failure semantics

- `status: failed` + reason in result.md → parent retries once with corrected task.md, then absorbs the work or records the gap.
- Budget exhausted → spawn.sh writes a failed status explaining it; parent must self-execute.
- Agent crash / timeout → spawn.sh backfills failed status pointing at `.agent.log`.
- The whole run is resumable: state is on disk. To resume, re-spawn only failed leaf nodes.

## Debugging a stuck swarm

- `bash scripts/tree.sh <run-dir>` — live census. `[..]` = still running.
- `cat <node>/.agent.log` — full stdout of that agent.
- `cat <run-dir>/budget.count` vs `max_agents` — did you hit the ceiling?
- `ls <run-dir>/.slots` — how many slots are held right now.
- Orphaned slots after a crash: `rmdir <run-dir>/.slots/*` to free them.
- Runaway swarm: `pkill -f "claude -p"` kills all workers; state on disk survives.

## Tuning config.json

- **Cheap wide swarms**: `"model": "claude-haiku-4-5"`, max_parallel 5, max_agents 25 — good for many small independent tasks (per-file processing, breadth research).
- **Deep quality swarms**: default model, max_depth 4, max_parallel 2 — good for building software where children must be smart.
- Cost scales roughly linearly with max_agents. Warn the user before launching swarms > 20 agents.
