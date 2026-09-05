# Agent Swarm

A Claude Code skill that breaks one large goal into a tree of agents. A master
agent splits the work, spawns child agents to handle each part, and those
children can split their own work and spawn children of their own. Results are
written to disk and merged back up the tree until the master returns a single
combined answer.

## Why not built-in subagents

Task-tool subagents cannot spawn subagents of their own, so recursion is
impossible with them. This skill launches every node as a separate headless
Claude Code process (`claude -p`), so any level of the tree can go deeper. The
filesystem is the only channel between agents, which makes every run
inspectable, crash tolerant, and resumable.

## How it works

1. You give the skill a goal. The current session becomes the root node.
2. Each node decides one of two things: EXECUTE the task directly, or DECOMPOSE
   it into two or more separable subtasks.
3. To decompose, a node writes a `task.md` for each child and runs `spawn.sh`,
   which launches a real Claude process for that child.
4. A child sees only its own `task.md` plus the node protocol. It has no
   conversation history and no knowledge of its siblings.
5. Every node finishes by writing `result.md` and `status.json`. A parent reads
   only those two files from each child, merges them, and writes its own.
6. The merge continues upward until the root produces the final answer.

## Installation

Clone into your skills directory. Per project:

```bash
git clone https://github.com/shaadahmade/Swarm-agent-for-claude-code .claude/skills/agent-swarm
```

Or for all projects:

```bash
git clone https://github.com/shaadahmade/Swarm-agent-for-claude-code ~/.claude/skills/agent-swarm
```

Skills are loaded at startup, so restart Claude Code before the skill appears.

## Requirements

- `claude` CLI on PATH
- `bash`
- `python3`

On Windows, run the scripts from Git Bash. The scripts use POSIX paths and are
invoked through the Bash tool, not PowerShell.

## Usage

Invoke the skill with your goal:

```
/agent-swarm Build a REST API with auth, tests, and docs
```

To drive the scripts by hand:

```bash
# create a run, optionally sizing it yourself
RUN=$(bash scripts/init_swarm.sh myrun '{"max_depth":2,"max_agents":13}')

# write the root task, then start the swarm
echo "your goal here" > "$RUN/nodes/root/task.md"
bash scripts/spawn.sh "$RUN" nodes/root

# inspect progress at any time
bash scripts/tree.sh "$RUN"
```

## Run layout

Every run lives in `swarm/<timestamp>-<name>/`. Each node owns one directory:

```
swarm/<run-id>/
  config.json            limits and model for this run
  budget.count           total agents spawned so far
  nodes/
    root/
      task.md            what this node must accomplish
      plan.md            EXECUTE or DECOMPOSE, plus reasoning
      result.md          this node's deliverable, read by its parent
      status.json        {"status": "success|partial|failed", "summary": "..."}
      .agent.log         raw output of the agent process
      children/
        1/               same structure, recursively
        2/
```

A node's path is its identity. `nodes/root/children/2/children/1` is the first
child of the second child of the root.

## Configuration

`config.json` is created by `init_swarm.sh` and can be edited before a run.

| Key | Default | Meaning |
|---|---|---|
| `max_depth` | 3 | How many levels deep the tree may go. Root is depth 0. |
| `max_children` | 4 | Maximum children any single node may spawn. |
| `max_agents` | 15 | Total agents allowed for the whole run. |
| `max_parallel` | 3 | Maximum agents running at once, across the entire tree. |
| `model` | "" | Model for spawned agents. Empty means the default. |
| `leaf_model` | "" | Overrides `model` at max depth only. Empty means leaves inherit `model`. |
| `allowed_tools` | `Bash Read Write Edit Glob Grep` | Tools each agent may use without a permission prompt. |
| `rationale` | "" | Why the swarm was sized this way. Recorded and shown by `tree.sh`. |

### The swarm sizes itself

You do not have to set any of this. The master agent reads the goal, works out
how many separable parts it has and whether those parts subdivide, and passes
its own configuration to `init_swarm.sh` as a JSON object:

```bash
bash scripts/init_swarm.sh research '{"max_depth":2,"max_agents":13,"rationale":"three areas, each splitting into sub-topics"}'
```

The reasoning is stored in `rationale` and printed by `tree.sh`, so the sizing
decision is visible rather than buried. Anything you set by hand is respected,
and any key you leave out falls back to the default in the table above.

Sizing follows the tree it intends to build. A balanced tree of branching factor
b and depth d holds `1 + b + b^2 + ... + b^d` agents, so branching 2 at depth 2
needs 7 and branching 3 at depth 2 needs 13. A budget set below the intended
tree is worse than a small one, because spawns get refused partway through and
parents have to absorb the leftover work.

### Ceilings on autonomous sizing

Because the agent chooses its own limits, `init_swarm.sh` clamps every value it
is given and reports on stderr when it does:

| Key | Floor | Ceiling |
|---|---|---|
| `max_depth` | 0 | 5 |
| `max_children` | 2 | 6 |
| `max_agents` | 1 | 40 |
| `max_parallel` | 1 | 8 |

`max_parallel` is additionally capped at `max_agents`. Invalid JSON and unknown
keys are rejected rather than ignored, so a typo like `max_agent` fails loudly
instead of silently leaving the default in place. To allow larger swarms, raise
the ceilings in `scripts/init_swarm.sh` deliberately.

### A note on allowed_tools

Spawned agents run headless and cannot answer permission prompts, so any tool
left out of this list is silently unavailable to them. `Bash` in particular is
required, because that is how a node spawns its own children. Removing it
collapses the swarm to a single agent. The list is deliberately configurable so
you can narrow it for runs that do not need a full shell, but note that `Bash`
is broad by nature and this is not a sandbox.

## Safety limits

- **Agent budget.** A counter file tracks every spawn. When the budget is spent,
  `spawn.sh` refuses to launch and tells the parent to do the work itself. The
  counter is guarded by an atomic `mkdir` lock, so concurrent spawns cannot
  overshoot the limit.
- **Parallelism gate.** A slot directory caps how many agents run at once across
  the whole tree, which keeps the run within API rate limits. The cap counts
  agents doing work, not agents merely existing: once a node has written task
  files for its own children it is blocked waiting on them, so it gives up its
  slot. Without that release the swarm deadlocks, because every slot ends up
  held by a parent waiting on children who can never get a slot of their own.
- **Parent-side guarantees.** If an agent crashes or exits without writing its
  files, `spawn.sh` backfills a failed `status.json` so the parent is never left
  waiting on a node that will never report.

## Reading the tree

`tree.sh` prints the run as an org chart with each node's status:

```
Swarm swarm/20260906-013536-deeptest - agents spawned: 7/7
Config: depth<=2 children<=2 parallel<=3 model=(default) leaf_model=claude-haiku-4-5-20251001
Sizing: four planets in two natural pairs, one agent per planet at the leaves

[ok] root (master)  - Aggregated all 4 planets from both children
    [ok] 1  - Inner planets section complete
        [ok] 1  - Mercury facts
        [ok] 2  - Venus facts
    [ok] 2  - Outer planets section complete
        [ok] 1  - Jupiter facts
        [ok] 2  - Saturn facts

Census: 7 node(s) on disk | 7 with a live agent | 0 phantom
```

The census line is an integrity check. A node counts as real only if an agent
process actually ran for it. If a parent writes a child's results by hand
instead of spawning it, that node is reported as a phantom and its results are
flagged as unverified. This matters because a collapsed swarm otherwise looks
identical to a healthy one.

## Failure handling

- A failed or partial child is retried once with a corrected `task.md`. If it
  fails again, the parent absorbs the work or records the gap.
- If a spawn is refused, the parent must do the subtask itself and report
  `partial`. Fabricating a child's output is prohibited by the protocol.
- All state is on disk, so a run can be resumed by re-spawning only the failed
  leaf nodes.

## Repository contents

| Path | Purpose |
|---|---|
| `SKILL.md` | Skill definition and trigger description. |
| `scripts/init_swarm.sh` | Creates a run directory, config, and budget counter. |
| `scripts/spawn.sh` | Launches one agent. Enforces budget and parallelism. |
| `scripts/tree.sh` | Prints the tree with statuses and the census audit. |
| `references/node-protocol.md` | The rules handed to every agent. |
| `references/child-task-template.md` | Template for writing a child's task. |
| `references/architecture.md` | Design rationale and debugging notes. |

## When not to use it

This is for goals with genuinely separable parts. A single-step task, or one
where every part depends on the last, runs slower and costs more as a swarm than
as one agent.
