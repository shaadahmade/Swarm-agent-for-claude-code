"""Render a swarm run directory as a self-contained HTML page.

Invoked by graph.sh, which runs it with the run directory as the working
directory so that relative paths work regardless of how the run directory was
addressed (an MSYS path like /c/Users/... cannot be opened by a native Windows
python, but bash can cd into it).

Usage: python3 graph.py <run-label> <output-path>
"""

import html
import json
import os
import sys

label, out = sys.argv[1], sys.argv[2]

cfg = json.load(open("config.json", encoding="utf-8"))
budget = open("budget.count").read().strip() if os.path.exists("budget.count") else "?"

BOX_W, BOX_H, COL, ROW = 190, 54, 250, 74
COLORS = {"success": "ok", "partial": "warn", "failed": "bad", "running": "idle"}


def mtime(path):
    return os.path.getmtime(path) if os.path.exists(path) else None


nodes, edges = [], []


def walk(node_dir, name, depth, parent):
    status, summary = "running", ""
    status_path = os.path.join(node_dir, "status.json")
    if os.path.exists(status_path):
        try:
            s = json.load(open(status_path, encoding="utf-8"))
            status, summary = s.get("status", "?"), s.get("summary", "")
        except Exception:
            status = "corrupt"
    index = len(nodes)
    nodes.append({
        "name": name,
        "depth": depth,
        "status": status,
        "summary": summary,
        # A node counts as real only if spawn.sh actually launched an agent.
        "spawned": os.path.exists(os.path.join(node_dir, ".agent.log")),
        "root": depth == 0,
        # It starts when its prompt is written and ends when its log is last
        # touched. Both are side effects of spawn.sh, so a node that was never
        # spawned simply has no bar on the timeline.
        "start": mtime(os.path.join(node_dir, ".prompt.txt")),
        "end": mtime(os.path.join(node_dir, ".agent.log")),
        "children": [],
    })
    if parent is not None:
        edges.append((parent, index))
        nodes[parent]["children"].append(index)
    child_dir = os.path.join(node_dir, "children")
    if os.path.isdir(child_dir):
        for child in sorted(os.listdir(child_dir)):
            if os.path.isdir(os.path.join(child_dir, child)):
                walk(os.path.join(child_dir, child), child, depth + 1, index)


walk(os.path.join("nodes", "root"), "root", 0, None)

# Layout: x from depth, y from leaf order, each parent centred on its children.
next_row = [0]


def place(i):
    node = nodes[i]
    if not node["children"]:
        node["y"] = next_row[0] * ROW
        next_row[0] += 1
    else:
        for child in node["children"]:
            place(child)
        node["y"] = (nodes[node["children"][0]]["y"] + nodes[node["children"][-1]]["y"]) / 2
    node["x"] = node["depth"] * COL


place(0)

width = max(n["x"] for n in nodes) + BOX_W + 20
height = max(n["y"] for n in nodes) + BOX_H + 20

svg = []
for a, b in edges:
    x1, y1 = nodes[a]["x"] + BOX_W, nodes[a]["y"] + BOX_H / 2
    x2, y2 = nodes[b]["x"], nodes[b]["y"] + BOX_H / 2
    mid = (x1 + x2) / 2
    svg.append(f'<path d="M{x1},{y1} C{mid},{y1} {mid},{y2} {x2},{y2}" class="edge"/>')

for node in nodes:
    cls = COLORS.get(node["status"], "idle")
    if not node["spawned"] and not node["root"]:
        cls += " phantom"
    duration = ""
    if node["start"] and node["end"] and node["end"] > node["start"]:
        duration = " &#183; %.0fs" % (node["end"] - node["start"])
    tag = "master" if node["root"] and not node["spawned"] else node["status"]
    svg.append(
        f'<g transform="translate({node["x"]},{node["y"]})" class="node {cls}">'
        f'<rect width="{BOX_W}" height="{BOX_H}" rx="8"/>'
        f'<text x="12" y="21" class="nm">{html.escape(node["name"])}</text>'
        f'<text x="12" y="39" class="sub">{html.escape(tag)}{duration}</text>'
        f'<title>{html.escape(node["summary"] or node["status"])}</title></g>'
    )

timed = [n for n in nodes if n["start"] and n["end"]]
timeline = '<p class="note">No timing data yet: no agent has been spawned.</p>'
if timed:
    t0 = min(n["start"] for n in timed)
    t1 = max(n["end"] for n in timed)
    span = max(t1 - t0, 0.001)
    rows = []
    for node in timed:
        left = (node["start"] - t0) / span * 100
        bar = max((node["end"] - node["start"]) / span * 100, 0.8)
        rows.append(
            f'<div class="trow"><div class="tlabel">{html.escape(node["name"])}'
            f'<span class="tdepth">d{node["depth"]}</span></div>'
            f'<div class="track"><div class="bar {COLORS.get(node["status"], "idle")}" '
            f'style="left:{left:.2f}%;width:{bar:.2f}%">'
            f'<span>{node["end"] - node["start"]:.0f}s</span></div></div></div>'
        )
    # Peak processes alive. This can legitimately exceed max_parallel: a parent
    # blocked waiting on its children gives up its slot, so the cap limits
    # agents doing work rather than agents merely existing.
    events = sorted([(n["start"], 1) for n in timed] + [(n["end"], -1) for n in timed])
    current = peak = 0
    for _, delta in events:
        current += delta
        peak = max(peak, current)
    over = peak > cfg["max_parallel"]
    note = (
        f'Wall clock {t1 - t0:.0f}s &#183; peak {peak} process(es) alive '
        f'&#183; working cap {cfg["max_parallel"]}'
    )
    if over:
        note += (' &#183; above the cap because a parent blocked on its children '
                 'releases its slot, so only working agents are counted against it')
    timeline = f'<p class="note">{note}</p>' + "".join(rows)

live = sum(1 for n in nodes if n["spawned"])
phantoms = [n["name"] for n in nodes if not n["spawned"] and not n["root"]]
warning = ""
if phantoms:
    warning = (
        f'<p class="warn-line">WARNING: {len(phantoms)} phantom node(s): '
        f'{html.escape(", ".join(phantoms))}. Results exist but no agent ever ran, '
        f'so a parent wrote them by hand. Treat them as unverified.</p>'
    )

leaf = cfg.get("leaf_model")
rationale = (f'<p class="rat">{html.escape(cfg["rationale"])}</p>') if cfg.get("rationale") else ""

doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Swarm {html.escape(label)}</title>
<style>
:root{{--bg:#fbfaf9;--fg:#1c1b1a;--mut:#6b6764;--line:#dedad6;--card:#fff;
--ok:#3f7d58;--warn:#a8761f;--bad:#a8402f;--idle:#8b8784;}}
@media(prefers-color-scheme:dark){{:root{{--bg:#191817;--fg:#eceae8;--mut:#9c9793;
--line:#332f2c;--card:#211f1e;--ok:#6aa87f;--warn:#d0a04a;--bad:#d47a68;--idle:#7c7773;}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--fg);padding:24px 16px;
font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}}
.wrap{{max-width:1000px;margin:0 auto}}
h1{{font-size:19px;margin:0 0 6px}}
h2{{font-size:13px;text-transform:uppercase;letter-spacing:.07em;color:var(--mut);
margin:32px 0 12px;font-weight:600}}
.meta{{color:var(--mut);font-size:13px;margin:0}}
.rat{{font-style:italic;color:var(--mut);font-size:13px;margin:8px 0 0}}
.stats{{display:flex;flex-wrap:wrap;gap:10px;margin:18px 0 0}}
.stat{{background:var(--card);border:1px solid var(--line);border-radius:9px;
padding:10px 14px;min-width:104px}}
.stat b{{display:block;font-size:20px;font-weight:600}}
.stat span{{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.05em}}
.scroll{{overflow-x:auto;background:var(--card);border:1px solid var(--line);
border-radius:11px;padding:16px}}
.edge{{fill:none;stroke:var(--line);stroke-width:2}}
.node rect{{fill:var(--card);stroke:var(--idle);stroke-width:1.5}}
.node.ok rect{{stroke:var(--ok)}}
.node.warn rect{{stroke:var(--warn)}}
.node.bad rect{{stroke:var(--bad)}}
.node.phantom rect{{stroke:var(--bad);stroke-dasharray:5 3}}
.nm{{font:600 13px ui-sans-serif,system-ui,sans-serif;fill:var(--fg)}}
.sub{{font:11px ui-monospace,SFMono-Regular,Menlo,monospace;fill:var(--mut)}}
.node.ok .sub{{fill:var(--ok)}}
.node.warn .sub{{fill:var(--warn)}}
.node.bad .sub{{fill:var(--bad)}}
.trow{{display:flex;align-items:center;gap:12px;margin-bottom:7px}}
.tlabel{{width:150px;flex:none;font:12px ui-monospace,Menlo,monospace;color:var(--mut);
white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.tdepth{{margin-left:7px;font-size:10px;opacity:.65}}
.track{{position:relative;flex:1;height:22px;background:var(--bg);border-radius:5px;min-width:170px}}
.bar{{position:absolute;top:0;height:22px;border-radius:5px;opacity:.88;display:flex;align-items:center}}
.bar span{{font:10px ui-monospace,Menlo,monospace;color:#fff;padding-left:6px;white-space:nowrap}}
.bar.ok{{background:var(--ok)}}
.bar.warn{{background:var(--warn)}}
.bar.bad{{background:var(--bad)}}
.bar.idle{{background:var(--idle)}}
.note{{color:var(--mut);font-size:12px;margin:0 0 14px}}
.warn-line{{color:var(--bad);font-size:13px;background:var(--card);
border:1px solid var(--bad);border-radius:9px;padding:11px 14px;margin-top:18px}}
.legend{{display:flex;flex-wrap:wrap;gap:16px;color:var(--mut);font-size:12px;margin-top:14px}}
.key{{display:flex;align-items:center;gap:6px}}
.dot{{width:10px;height:10px;border-radius:3px;display:inline-block}}
footer{{margin-top:34px;color:var(--mut);font-size:12px;border-top:1px solid var(--line);
padding-top:14px}}
@media(max-width:520px){{.tlabel{{width:92px}}}}
</style></head><body><div class="wrap">
<h1>Swarm {html.escape(label)}</h1>
<p class="meta">depth &#8804; {cfg['max_depth']} &#183; children &#8804; {cfg['max_children']}
&#183; parallel &#8804; {cfg['max_parallel']} &#183; model
{html.escape(str(cfg.get('model') or 'default'))}{(' &#183; leaf ' + html.escape(str(leaf))) if leaf else ''}</p>
{rationale}
<div class="stats">
<div class="stat"><b>{budget}</b><span>spawned</span></div>
<div class="stat"><b>{cfg['max_agents']}</b><span>budget</span></div>
<div class="stat"><b>{live}</b><span>live agents</span></div>
<div class="stat"><b>{len(phantoms)}</b><span>phantom</span></div>
<div class="stat"><b>{max(n['depth'] for n in nodes)}</b><span>max depth</span></div>
</div>
<h2>Tree</h2>
<div class="scroll"><svg width="{width}" height="{height}"
viewBox="0 0 {width} {height}">{''.join(svg)}</svg></div>
<div class="legend">
<span class="key"><i class="dot" style="background:var(--ok)"></i>success</span>
<span class="key"><i class="dot" style="background:var(--warn)"></i>partial</span>
<span class="key"><i class="dot" style="background:var(--bad)"></i>failed</span>
<span class="key"><i class="dot" style="background:var(--idle)"></i>running or master</span>
<span class="key">dashed = phantom</span>
<span class="key">hover a node for its summary</span>
</div>
<h2>Timeline</h2>
{timeline}
{warning}
<footer>Generated by graph.sh from the run directory. Times come from file
timestamps, so they measure each agent process, not billed tokens.</footer>
</div></body></html>"""

open(out, "w", encoding="utf-8").write(doc)
print(out)
