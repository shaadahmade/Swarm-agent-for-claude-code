# Child task.md template

Copy this structure when writing any child's `task.md`. A child sees ONLY this file plus the node protocol — no conversation history, no sibling knowledge. Everything it needs must be here.

```markdown
# Goal
<One clear paragraph. Self-contained. What must be accomplished and why it matters to the larger goal (one sentence of context max).>

# Deliverable
<Exactly what to produce and WHERE. e.g. "Write the API server to src/server.py"
or "Write your findings as markdown in result.md under a '## Findings' heading.">

# Success criteria
- <verifiable criterion 1>
- <verifiable criterion 2>

# Context
- <paths, formats, constraints, naming conventions, ports, style rules>
- <facts the parent knows that the child will need>

# Hints (optional)
- <suggested decomposition if you expect the child to spawn its own children>
```

Anti-patterns to avoid:
- Vague goals ("help with the frontend") — children can't ask you questions.
- Overlapping children (two children both told to "handle utils") — they will collide.
- Forgetting output paths — the child will invent one and you won't find it.
- Passing relative paths without an anchor — always state paths relative to the repo root or the run dir explicitly.
