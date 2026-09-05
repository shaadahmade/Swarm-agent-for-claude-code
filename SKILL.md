---
name: agent-swarm
description: Decompose a large goal into a recursive hierarchy of agents (a "swarm" or "civilization") where a master agent spawns sub-agents, sub-agents can spawn their own sub-agents, and all results backtrace up the tree to the master for final synthesis. Use this skill whenever the user asks to "swarm" a task, build an "agent civilization", run a "hierarchy of agents", "recursive agents", "agents that spawn agents", parallelize a big multi-part goal across many workers, or whenever a task is clearly too large for one agent and would benefit from tree-structured decomposition (e.g., "build a whole app", "research 20 topics and merge", "process every file in this repo differently"). Do NOT use for small single-step tasks.
---

# Agent Swarm (Recursive Agent Civilization)

Turn one big goal into a **tree of agents**. You (the current Claude Code session) become the **Master Agent**. You spawn child agents; children may spawn grandchildren; and so on. Every agent writes its result to disk, parents **aggregate child results upward**, and the chain backtraces to you, the master, who synthesizes the final answer against the original goal.

## Why `claude -p` instead of the Task tool

Task-tool subagents **cannot spawn their own subagents** — recursion is impossible with them. This skill instead spawns each agent as a headless Claude Code process (`claude -p`) via Bash. Every agent is a full Claude Code instance, so any level can recurse deeper. The filesystem is the swarm's shared memory and message bus.

## The Node Protocol (every agent follows this)

The swarm lives in `./swarm/<run-id>/`. Every agent owns exactly one **node directory**:

```
swarm/<run-id>/
├── config.json              # depth limit, child limit, budget, model
├── budget.count             # global spawn counter (one line, an integer)
└── nodes/
    └── root/                # the master (you)
        ├── task.md          # what this node must accomplish
        ├── plan.md          # DECOMPOSE or EXECUTE decision + reasoning
        ├── result.md        # the node's final deliverable (backtraced upward)
        ├── status.json      # {"status": "success|partial|failed", "summary": "..."}
        └── children/
            ├── 1/           # child node — same structure, recursively
            │   └── children/
            │       └── 1/   # grandchild — and so on
            └── 2/
```

Node identity = its path. `nodes/root/children/2/children/1` is grandchild 1 of child 2. This path **is** the backtrace route: results flow leaf → parent → ... → root.

### The decision every agent makes: EXECUTE or DECOMPOSE

Read `task.md`, then decide:

- **EXECUTE** — the task fits comfortably in one agent's context and skill. Do the work directly, write the deliverable to `result.md`, write `status.json`. Done.
- **DECOMPOSE** — the task has 2+ separable subgoals. Write `plan.md` listing the subtasks, spawn one child per subtask (see below), wait, aggregate.

Hard rules that keep the civilization from collapsing:
1. **Depth limit** (`config.json → max_depth`, default 3). At max depth an agent MUST execute, never decompose.
2. **Child limit** (`max_children`, default 4). Prefer fewer, bigger children over many tiny ones.
3. **Global budget** (`max_agents`, default 15 total spawns). `scripts/spawn.sh` enforces it atomically and refuses to spawn past it — if refused, execute the task yourself.
4. **Never decompose into 1 child.** That's just yourself with extra steps.
5. A subtask given to a child must be **self-contained**: a child sees only its own `task.md`, not the conversation.

## Master Agent workflow (you, step by step)

1. **Init the run:**
   ```bash
   bash <skill-dir>/scripts/init_swarm.sh "<short-run-name>"
   ```
   This creates `swarm/<run-id>/`, `config.json` (edit limits if the user asked for them), and `nodes/root/`. Write the user's goal into `nodes/root/task.md`.

2. **Plan the decomposition.** Write `nodes/root/plan.md`: list 2–4 subtasks, each with a clear deliverable and success criterion. Tell the user the plan briefly before spawning.

3. **Spawn children in parallel:**
   ```bash
   bash <skill-dir>/scripts/spawn.sh <run-dir> nodes/root/children/1 &
   bash <skill-dir>/scripts/spawn.sh <run-dir> nodes/root/children/2 &
   wait
   ```
   Before spawning, write each child's `task.md` (use the template in `references/child-task-template.md` — it embeds the node protocol so children know how to recurse and backtrace).

4. **Backtrace / aggregate.** After `wait`, read every child's `status.json` and `result.md`:
   - All success → synthesize child results into `nodes/root/result.md`, the final deliverable for the user.
   - A child **failed or is partial** → read its `result.md` for the failure reason. Retry it **once** with a corrected `task.md` (mention what went wrong). If it fails again, work around it: do that piece yourself or report the gap honestly in the final result.
   - A child produced files (code, docs): children write real files into their own node dir or a path you specify in their task.md — collect/merge them.

5. **Report.** Show the user the final result, plus a one-line civilization census: how many agents ran, tree shape, any casualties (failed nodes). `bash <skill-dir>/scripts/tree.sh <run-dir>` prints the tree with statuses.

## What children do (encoded in their task.md automatically)

Each spawned child receives instructions to: read its `task.md`, make the EXECUTE/DECOMPOSE decision under the same rules (its depth is derived from its path), spawn its own children with the same `spawn.sh` if decomposing, and **always** finish by writing `result.md` + `status.json` — even on failure (a failed node writes *why* it failed, so the parent can adapt). A node that exits without `status.json` is treated by its parent as failed.

## Practical notes

- `spawn.sh` runs children with `--permission-mode acceptEdits` and passes `--model` from `config.json` (default: haiku for leaves is a good cost saver — set `"model": "claude-haiku-4-5"` if the user wants cheap workers; omit to inherit default).
- Parallel spawns are capped by `max_parallel` in config (default 3) to avoid rate limits; `spawn.sh` handles queuing via a simple lock loop.
- Long waits: poll `tree.sh` occasionally and narrate progress to the user instead of going silent.
- If `claude` CLI is not on PATH, stop and tell the user this skill needs Claude Code's CLI available inside Bash.
- Read `references/child-task-template.md` before writing any child task.md. For deeper protocol details or debugging a stuck swarm, read `references/architecture.md`.
