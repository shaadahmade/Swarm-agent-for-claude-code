"""Serve a live view of a swarm run.

Invoked by watch.sh with the run directory as the working directory. Serves
three things on localhost only:

  /           the page shell, which polls for updates
  /fragment   the re-rendered tree and timeline
  /favicon.ico  nothing, quietly

Usage: python3 serve.py <run-label> <port> <poll-ms>
"""

import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

import swarm_render

label, port, poll_ms = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])


class Handler(BaseHTTPRequestHandler):
    def _send(self, body, content_type="text/html; charset=utf-8"):
        payload = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        # The whole point is freshness, so never let anything cache.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        try:
            if path == "/fragment":
                self._send(swarm_render.render(swarm_render.scan()))
            elif path == "/":
                body = swarm_render.render(swarm_render.scan())
                self._send(swarm_render.shell(label, body, live_ms=poll_ms))
            else:
                self.send_error(404)
        except FileNotFoundError:
            # The run directory can be mid-write; a later poll will succeed.
            self.send_error(503, "run directory not readable yet")
        except BrokenPipeError:
            pass

    def log_message(self, *args):
        pass  # One line per poll would bury the terminal.


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"http://127.0.0.1:{port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
