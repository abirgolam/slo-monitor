"""End to end: run the flaky service, inject chaos, and check that the alert fires and then resolves.

Uses a fake clock, so the test runs in about a second without real sleeping.
"""

import socket
import sys
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "demo"))
import flaky_service  # noqa: E402

from slo_monitor.alerts import AlertManager  # noqa: E402
from slo_monitor.config import parse  # noqa: E402
from slo_monitor.monitor import Monitor  # noqa: E402


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeClock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


class TestEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.server = ThreadingHTTPServer(("127.0.0.1", cls.port), flaky_service.Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def chaos(self, error_rate):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/chaos?error_rate={error_rate}&latency_ms=0", method="POST")
        urllib.request.urlopen(req).read()

    def test_alert_fires_and_resolves(self):
        cfg = parse({
            "global": {"probe_interval_s": 1, "slo_period_s": 600, "bucket_s": 1, "min_samples": 5},
            "targets": [{"name": "svc", "url": f"http://127.0.0.1:{self.port}/",
                         "slos": [{"name": "availability", "kind": "availability", "objective": 0.99}]}],
            "alert_rules": [{"severity": "page", "long_window_s": 60, "short_window_s": 10, "burn_rate": 14.4}],
        })
        sent = []
        clock = FakeClock()
        mon = Monitor(cfg, clock=clock, alerts=AlertManager("http://hook", sender=lambda u, p: sent.append(p)))

        def run(seconds):
            for _ in range(seconds):
                mon.tick()
                clock.t += 1

        self.chaos(0)
        run(30)
        self.assertEqual(mon.alerts.active, {})

        self.chaos(1.0)                       # total outage
        run(15)
        self.assertIn(("svc", "availability", "page"), mon.alerts.active)
        self.assertEqual(sent[-1]["event"]["state"], "FIRING")

        self.chaos(0)                         # recover: the short window clears within ~10s
        run(15)
        self.assertEqual(mon.alerts.active, {})
        self.assertEqual(sent[-1]["event"]["state"], "RESOLVED")
        self.assertEqual(len(sent), 2)        # exactly one FIRING and one RESOLVED, no spam

        metrics = mon.registry.render()
        self.assertIn('slo_alert_firing{severity="page",slo="availability",target="svc"} 0', metrics)
        self.assertIn("slo_error_budget_remaining_ratio", metrics)


if __name__ == "__main__":
    unittest.main()
