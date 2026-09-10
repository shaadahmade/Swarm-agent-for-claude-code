"""Write a static HTML snapshot of a swarm run.

Invoked by graph.sh with the run directory as the working directory. For a live
view that updates while the swarm runs, use watch.sh instead.

Usage: python3 graph.py <run-label> <output-path>
"""

import sys

import swarm_render

label, out = sys.argv[1], sys.argv[2]
body = swarm_render.render(swarm_render.scan())
open(out, "w", encoding="utf-8").write(swarm_render.shell(label, body))
print(out)
