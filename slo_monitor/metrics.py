"""A minimal Prometheus exposition endpoint (text format 0.0.4), using only the standard library.

Prometheus scrapes GET /metrics. This module also serves:
  GET /status   the current SLO state as JSON, for humans and scripts
  GET /healthz  the monitor's own liveness check (who watches the watchmen?)
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _fmt_labels(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    esc = lambda v: str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")  # noqa: E731
    return "{" + ",".join(f'{k}="{esc(v)}"' for k, v in sorted(labels.items())) + "}"


class Registry:
    """Thread-safe store of metric samples. Gauges are set, counters are incremented."""

    def __init__(self):
        self._lock = threading.Lock()
        self._meta: dict[str, tuple[str, str]] = {}      # name -> (type, help)
        self._values: dict[str, dict[tuple, float]] = {}

    def describe(self, name: str, mtype: str, help_text: str) -> None:
        self._meta[name] = (mtype, help_text)
        self._values.setdefault(name, {})

    def set(self, name: str, value: float, **labels) -> None:
        with self._lock:
            self._values[name][tuple(sorted(labels.items()))] = value

    def inc(self, name: str, amount: float = 1.0, **labels) -> None:
        key = tuple(sorted(labels.items()))
        with self._lock:
            self._values[name][key] = self._values[name].get(key, 0.0) + amount

    def get(self, name: str, **labels) -> float | None:
        return self._values.get(name, {}).get(tuple(sorted(labels.items())))

    def render(self) -> str:
        lines = []
        with self._lock:
            for name, (mtype, help_text) in self._meta.items():
                lines.append(f"# HELP {name} {help_text}")
                lines.append(f"# TYPE {name} {mtype}")
                for key, val in self._values[name].items():
                    lines.append(f"{name}{_fmt_labels(dict(key))} {val:g}")
        return "\n".join(lines) + "\n"


def serve(registry: Registry, status_fn, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/metrics":
                body, ctype = registry.render().encode(), "text/plain; version=0.0.4"
            elif self.path == "/status":
                body, ctype = json.dumps(status_fn(), indent=2).encode(), "application/json"
            elif self.path == "/healthz":
                body, ctype = b"ok\n", "text/plain"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):   # keep scrape traffic out of the logs
            pass

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True, name="metrics-http").start()
    return server
