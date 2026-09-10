"""Scan a swarm run directory and render it as HTML.

Shared by graph.py (writes a static file) and serve.py (serves a live view that
polls this same renderer), so the drawing code exists in exactly one place.

Every function assumes the current working directory IS the run directory, and
uses relative paths only. Callers cd into the run first. This is deliberate: a
run directory may be an MSYS path like /c/Users/... which bash can cd into but a
native Windows python cannot open.
"""

import html
import json
import os
import time

BOX_W, BOX_H, COL, ROW = 196, 56, 254, 76
STATUS_CLASS = {
    "success": "ok",
    "partial": "warn",
    "failed": "bad",
    "running": "run",
}


def _mtime(path):
    return os.path.getmtime(path) if os.path.exists(path) else None


def scan():
    """Read the run directory into a plain dict."""
    cfg = json.load(open("config.json", encoding="utf-8"))
    budget = open("budget.count").read().strip() if os.path.exists("budget.count") else "?"
    nodes = []

    def walk(node_dir, name, depth, parent):
        status, summary = "pending", ""
        status_path = os.path.join(node_dir, "status.json")
        started = _mtime(os.path.join(node_dir, ".prompt.txt"))
        logged = _mtime(os.path.join(node_dir, ".agent.log"))
        if os.path.exists(status_path):
            try:
                s = json.load(open(status_path, encoding="utf-8"))
                status, summary = s.get("status", "?"), s.get("summary", "")
            except Exception:
                status = "corrupt"
        elif started:
            # Prompt written but no verdict yet: this agent is still going.
            status = "running"
        index = len(nodes)
        nodes.append({
            "name": name,
            "depth": depth,
            "status": status,
            "summary": summary,
            # Real only if spawn.sh actually launched an agent for this node.
            "spawned": os.path.exists(os.path.join(node_dir, ".agent.log")),
            "root": depth == 0,
            "start": started,
            "end": logged if status not in ("running", "pending") else None,
            "live": status == "running",
            "children": [],
        })
        if parent is not None:
            nodes[parent]["children"].append(index)
        child_dir = os.path.join(node_dir, "children")
        if os.path.isdir(child_dir):
            for child in sorted(os.listdir(child_dir)):
                if os.path.isdir(os.path.join(child_dir, child)):
                    walk(os.path.join(child_dir, child), child, depth + 1, index)

    walk(os.path.join("nodes", "root"), "root", 0, None)
    return {"cfg": cfg, "budget": budget, "nodes": nodes, "now": time.time()}


def _layout(nodes):
    row = [0]

    def place(i):
        node = nodes[i]
        if not node["children"]:
            node["y"] = row[0] * ROW
            row[0] += 1
        else:
            for child in node["children"]:
                place(child)
            first, last = node["children"][0], node["children"][-1]
            node["y"] = (nodes[first]["y"] + nodes[last]["y"]) / 2
        node["x"] = node["depth"] * COL

    place(0)


def _fmt(seconds):
    seconds = int(seconds)
    return f"{seconds}s" if seconds < 60 else f"{seconds // 60}m{seconds % 60:02d}s"


def render(data):
    """Render the live portion of the page: stats, tree, timeline, census."""
    cfg, nodes, now = data["cfg"], data["nodes"], data["now"]
    _layout(nodes)

    def span(node):
        """Elapsed time for a node, counting up while it is still running."""
        if not node["start"]:
            return None
        return (node["end"] or now) - node["start"]

    svg = []
    for node in nodes:
        for child in node["children"]:
            kid = nodes[child]
            x1, y1 = node["x"] + BOX_W, node["y"] + BOX_H / 2
            x2, y2 = kid["x"], kid["y"] + BOX_H / 2
            mid = (x1 + x2) / 2
            live = " live" if kid["live"] else ""
            svg.append(f'<path d="M{x1},{y1} C{mid},{y1} {mid},{y2} {x2},{y2}" class="edge{live}"/>')

    for node in nodes:
        cls = STATUS_CLASS.get(node["status"], "idle")
        if not node["spawned"] and not node["root"] and node["status"] != "pending":
            cls += " phantom"
        elapsed = span(node)
        right = _fmt(elapsed) if elapsed else ""
        if node["root"] and not node["spawned"]:
            sub = f'd{node["depth"]} &#183; interactive master'
        else:
            sub = f'd{node["depth"]} &#183; {html.escape(node["status"])}'
        pulse = '<circle class="pulse" cx="176" cy="18" r="4"/>' if node["live"] else ""
        svg.append(
            f'<g transform="translate({node["x"]},{node["y"]})" class="node {cls}">'
            f'<rect class="nodebox" width="{BOX_W}" height="{BOX_H}" rx="8"/>'
            f'<rect class="stripe" x="1.5" y="1.5" width="3" height="{BOX_H - 3}" rx="1.5"/>'
            f'<text class="nm" x="16" y="24">{html.escape(node["name"])}</text>'
            f'<text class="id" x="16" y="42">{sub}</text>'
            f'<text class="dur" x="{BOX_W - 14}" y="42" text-anchor="end">{right}</text>'
            f'{pulse}'
            f'<title>{html.escape(node["summary"] or node["status"])}</title></g>'
        )

    width = max(n["x"] for n in nodes) + BOX_W + 16
    height = max(n["y"] for n in nodes) + BOX_H + 16

    timed = [n for n in nodes if n["start"]]
    if timed:
        t0 = min(n["start"] for n in timed)
        t1 = max((n["end"] or now) for n in timed)
        total = max(t1 - t0, 0.001)
        rows = []
        for node in sorted(timed, key=lambda n: n["start"]):
            left = (node["start"] - t0) / total * 100
            length = max(((node["end"] or now) - node["start"]) / total * 100, 0.7)
            cls = STATUS_CLASS.get(node["status"], "idle")
            if node["children"]:
                cls += " parent"
            rows.append(
                f'<div class="trow"><div class="tlabel"><b>{html.escape(node["name"])}</b>'
                f'<span>d{node["depth"]}</span></div>'
                f'<div class="track"><div class="bar {cls}" '
                f'style="left:{left:.2f}%;width:{length:.2f}%">'
                f'<em>{_fmt((node["end"] or now) - node["start"])}</em></div></div></div>'
            )
        events = sorted([(n["start"], 1) for n in timed] + [((n["end"] or now), -1) for n in timed])
        current = peak = 0
        for _, delta in events:
            current += delta
            peak = max(peak, current)
        note = (f'Elapsed {_fmt(total)} &#183; peak {peak} process(es) alive '
                f'&#183; working cap {cfg["max_parallel"]}')
        if peak > cfg["max_parallel"]:
            note += (' &#183; above the cap because a parent blocked on its children releases '
                     'its slot, so only working agents count against it')
        ticks = "".join(
            f'<span>{_fmt(total * f)}</span>' for f in (0, 0.25, 0.5, 0.75, 1.0)
        )
        timeline = (f'<p class="note">{note}</p><div class="axis">{ticks}</div>' + "".join(rows))
    else:
        timeline = '<p class="note">No agent has been spawned yet.</p>'

    live_count = sum(1 for n in nodes if n["live"])
    done = sum(1 for n in nodes if n["status"] in ("success", "partial", "failed"))
    phantoms = [n["name"] for n in nodes
                if not n["spawned"] and not n["root"] and n["status"] != "pending"]

    warning = ""
    if phantoms:
        warning = (f'<p class="warn-line">{len(phantoms)} phantom node(s): '
                   f'{html.escape(", ".join(phantoms))}. Results exist but no agent ever ran '
                   f'there, so a parent wrote them by hand. Treat them as unverified.</p>')

    running_tile = (f'<div class="tile hot"><b>{live_count}</b><span>running now</span></div>'
                    if live_count else
                    f'<div class="tile"><b>{done}</b><span>finished</span></div>')

    return f"""
<div class="tiles">
  <div class="tile"><b>{data['budget']}</b><span>spawned</span></div>
  <div class="tile"><b>{cfg['max_agents']}</b><span>budget</span></div>
  {running_tile}
  <div class="tile{' clean' if not phantoms else ' alarm'}"><b>{len(phantoms)}</b><span>phantom</span></div>
  <div class="tile"><b>{max(n['depth'] for n in nodes)}</b><span>max depth</span></div>
</div>

<h2>Tree</h2>
<div class="scroll"><svg width="{width}" height="{height}" viewBox="0 0 {width} {height}"
  role="img" aria-label="Swarm tree with one box per agent">{''.join(svg)}</svg></div>
<div class="legend">
  <span class="key"><i class="sw ok"></i>success</span>
  <span class="key"><i class="sw warn"></i>partial</span>
  <span class="key"><i class="sw bad"></i>failed</span>
  <span class="key"><i class="sw run"></i>running</span>
  <span class="key"><i class="sw dash"></i>phantom or not yet spawned</span>
  <span class="key">hover a node for what it reported</span>
</div>

<h2>Timeline</h2>
{timeline}
{warning}
"""


def shell(label, body, live_ms=0):
    """Wrap a rendered body in a complete HTML document.

    live_ms > 0 turns on polling: the page refetches /fragment on that interval
    and swaps it in, so scroll position and hover are preserved.
    """
    poll = ""
    if live_ms:
        poll = f"""
<script>
(function () {{
  var host = document.getElementById('live');
  var dot = document.getElementById('conn');
  function tick() {{
    fetch('fragment', {{cache: 'no-store'}})
      .then(function (r) {{ return r.ok ? r.text() : Promise.reject(r.status); }})
      .then(function (html) {{ host.innerHTML = html; dot.className = 'on'; }})
      .catch(function () {{ dot.className = 'off'; }});
  }}
  setInterval(tick, {live_ms});
  tick();
}})();
</script>"""
    badge = ('<span class="livebadge"><i id="conn" class="on"></i>live</span>'
             if live_ms else "")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Swarm {html.escape(label)}</title>
<style>{CSS}</style></head>
<body><div class="wrap">
<header>
  <div class="eyebrow">Swarm run {badge}</div>
  <h1>{html.escape(label)}</h1>
</header>
<div id="live">{body}</div>
<footer>Times come from file timestamps, so they measure agent processes, not billed tokens.</footer>
</div>{poll}</body></html>"""


CSS = """
:root{
  --ground:#f6f8f9; --card:#fff; --ink:#12171b; --muted:#59646d;
  --line:#dde3e7; --soft:#eaeef1; --accent:#16697a;
  --ok:#2f7a52; --warn:#9a6a12; --bad:#a8392c; --run:#1f6f8b; --idle:#7c868e;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  --sans:ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --ground:#101417; --card:#181d21; --ink:#e6ebee; --muted:#8d979f;
    --line:#262d33; --soft:#1f252a; --accent:#5aa8b8;
    --ok:#5fa47b; --warn:#c39a45; --bad:#cf7365; --run:#5fa8c4; --idle:#79838b;
  }
}
:root[data-theme="dark"]{
  --ground:#101417; --card:#181d21; --ink:#e6ebee; --muted:#8d979f;
  --line:#262d33; --soft:#1f252a; --accent:#5aa8b8;
  --ok:#5fa47b; --warn:#c39a45; --bad:#cf7365; --run:#5fa8c4; --idle:#79838b;
}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--sans);
  font-size:15px;line-height:1.55;padding-block:34px 48px;padding-left:20px;padding-right:20px}
.wrap{max-width:940px;margin:0 auto;display:flex;flex-direction:column;gap:30px}
header{display:flex;flex-direction:column;gap:7px}
.eyebrow{font-family:var(--mono);font-size:11px;letter-spacing:.13em;text-transform:uppercase;
  color:var(--accent);font-weight:600;display:flex;align-items:center;gap:11px}
.livebadge{display:inline-flex;align-items:center;gap:6px;color:var(--muted)}
.livebadge i{width:7px;height:7px;border-radius:50%;background:var(--ok);display:inline-block}
.livebadge i.off{background:var(--bad)}
.livebadge i.on{animation:blink 2s ease-in-out infinite}
@keyframes blink{50%{opacity:.35}}
h1{font-size:27px;line-height:1.15;margin:0;font-weight:600;letter-spacing:-.015em;
  font-family:var(--mono)}
h2{font-family:var(--mono);font-size:11.5px;letter-spacing:.12em;text-transform:uppercase;
  color:var(--muted);margin:30px 0 13px;font-weight:600;padding-bottom:9px;
  border-bottom:1px solid var(--line)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(126px,1fr));gap:1px;
  background:var(--line);border:1px solid var(--line);border-radius:10px;overflow:hidden}
.tile{background:var(--card);padding:14px 16px;display:flex;flex-direction:column;gap:3px}
.tile b{font-family:var(--mono);font-size:24px;font-weight:500;line-height:1;
  font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.tile span{font-family:var(--mono);font-size:10.5px;letter-spacing:.09em;
  text-transform:uppercase;color:var(--muted)}
.tile.clean b{color:var(--ok)}
.tile.alarm b{color:var(--bad)}
.tile.hot b{color:var(--run)}
.scroll{overflow-x:auto;background:var(--card);border:1px solid var(--line);
  border-radius:10px;padding:17px}
svg{display:block;max-width:100%;height:auto}
.edge{fill:none;stroke:var(--line);stroke-width:1.5}
.edge.live{stroke:var(--run);stroke-dasharray:5 4}
.nodebox{fill:var(--card);stroke:var(--idle);stroke-width:1.5}
.stripe{fill:var(--idle)}
.node.ok .nodebox{stroke:var(--ok)} .node.ok .stripe{fill:var(--ok)} .node.ok .dur{fill:var(--ok)}
.node.warn .nodebox{stroke:var(--warn)} .node.warn .stripe{fill:var(--warn)}
.node.bad .nodebox{stroke:var(--bad)} .node.bad .stripe{fill:var(--bad)}
.node.run .nodebox{stroke:var(--run)} .node.run .stripe{fill:var(--run)} .node.run .dur{fill:var(--run)}
.node.idle .nodebox{stroke-dasharray:4 3}
.node.phantom .nodebox{stroke:var(--bad);stroke-dasharray:5 3}
.pulse{fill:var(--run);animation:blink 1.4s ease-in-out infinite}
.nm{font-family:var(--sans);font-size:13.5px;font-weight:600;fill:var(--ink)}
.id{font-family:var(--mono);font-size:10.5px;fill:var(--muted);letter-spacing:.04em}
.dur{font-family:var(--mono);font-size:11px;fill:var(--muted);font-variant-numeric:tabular-nums}
.legend{display:flex;flex-wrap:wrap;gap:7px 18px;font-size:12.5px;color:var(--muted);margin-top:13px}
.key{display:flex;align-items:center;gap:7px}
.sw{width:11px;height:11px;border-radius:3px;border:1.5px solid var(--idle);flex:none}
.sw.ok{border-color:var(--ok)} .sw.warn{border-color:var(--warn)}
.sw.bad{border-color:var(--bad)} .sw.run{border-color:var(--run)}
.sw.dash{border-style:dashed}
.note{color:var(--muted);font-size:13px;margin:0 0 13px;max-width:66ch}
.axis{display:flex;justify-content:space-between;font-family:var(--mono);font-size:10.5px;
  color:var(--muted);font-variant-numeric:tabular-nums;margin-left:150px;padding-bottom:5px;
  border-bottom:1px solid var(--soft);margin-bottom:11px}
.trow{display:flex;align-items:center;gap:13px;margin-bottom:7px}
.tlabel{width:137px;flex:none;display:flex;align-items:baseline;gap:8px}
.tlabel b{font-size:13px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tlabel span{font-family:var(--mono);font-size:10.5px;color:var(--muted)}
.track{position:relative;flex:1;height:25px;min-width:160px;background:var(--soft);border-radius:5px}
.bar{position:absolute;top:0;height:25px;border-radius:5px;background:var(--ok);
  display:flex;align-items:center;justify-content:flex-end;padding-right:8px;
  transition:width .4s ease,left .4s ease}
.bar.parent{background:var(--accent)}
.bar.warn{background:var(--warn)} .bar.bad{background:var(--bad)}
.bar.run{background:var(--run)} .bar.idle{background:var(--idle)}
.bar em{font-family:var(--mono);font-size:10.5px;font-style:normal;color:#fff;
  font-variant-numeric:tabular-nums;white-space:nowrap}
.warn-line{color:var(--bad);font-size:13.5px;background:var(--card);border:1px solid var(--bad);
  border-radius:10px;padding:12px 15px;margin-top:17px;max-width:66ch}
footer{color:var(--muted);font-size:12.5px;border-top:1px solid var(--line);
  padding-top:15px;font-family:var(--mono)}
@media (prefers-reduced-motion: reduce){*{animation:none!important;transition:none!important}}
@media (max-width:620px){
  .axis{margin-left:0}
  .trow{flex-direction:column;align-items:stretch;gap:4px;margin-bottom:13px}
  .tlabel{width:auto}
}
"""
