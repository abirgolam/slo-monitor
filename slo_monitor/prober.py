"""Black-box HTTP prober: hit the endpoint like a user would and time it."""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import __version__
from .config import Target


@dataclass(frozen=True)
class ProbeResult:
    target: str
    ts: float
    ok: bool
    status: int | None
    latency_ms: float
    error: str | None = None


def probe(target: Target, clock=time.time) -> ProbeResult:
    req = urllib.request.Request(target.url, headers={"User-Agent": f"slo-monitor/{__version__}"})
    started = time.perf_counter()
    ts = clock()
    status, error = None, None
    try:
        with urllib.request.urlopen(req, timeout=target.timeout_s) as resp:
            resp.read()
            status = resp.status
    except urllib.error.HTTPError as e:      # 4xx/5xx: we still got a response
        status = e.code
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        error = type(getattr(e, "reason", e)).__name__
    latency_ms = (time.perf_counter() - started) * 1000
    ok = status in target.expected_status
    if not ok and error is None:
        error = f"HTTP {status}"
    return ProbeResult(target.name, ts, ok, status, latency_ms, error)
