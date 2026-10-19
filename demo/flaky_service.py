"""A deliberately unreliable HTTP service, used to exercise the monitor (a small chaos-engineering demo).

  GET  /                  the endpoint being monitored
  POST /chaos?error_rate=0.2&latency_ms=600   inject failures and latency
  POST /chaos?error_rate=0&latency_ms=0       recover

Run it with: python demo/flaky_service.py --port 8080
"""

from __future__ import annotations

import argparse
import json
import random
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

STATE = {"error_rate": 0.0, "latency_ms": 0.0}


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if urlparse(self.path).path != "/":
            return self._reply(404, {"error": "not found"})
        if STATE["latency_ms"]:
            # jitter around the injected latency so the latency SLO is probabilistic, not binary
            time.sleep(random.uniform(0.5, 1.5) * STATE["latency_ms"] / 1000)
        if random.random() < STATE["error_rate"]:
            return self._reply(503, {"error": "injected failure"})
        self._reply(200, {"status": "ok"})

    def do_POST(self):
        url = urlparse(self.path)
        if url.path != "/chaos":
            return self._reply(404, {"error": "not found"})
        q = parse_qs(url.query)
        for key in STATE:
            if key in q:
                STATE[key] = float(q[key][0])
        self._reply(200, STATE)

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    port = ap.parse_args().port
    print(f"flaky service on :{port}", flush=True)
    try:
        ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nflaky service stopped")
