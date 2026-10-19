"""The control loop: probe, record, evaluate SLOs, update metrics, and alert."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor

from . import slo as slomath
from .alerts import AlertManager
from .config import Config
from .metrics import Registry
from .prober import ProbeResult, probe
from .window import RollingCounter

log = logging.getLogger("slo_monitor")


class Monitor:
    def __init__(self, cfg: Config, clock=time.time, prober=probe, alerts: AlertManager | None = None):
        self.cfg = cfg
        self.clock = clock
        self.prober = prober
        self.alerts = alerts or AlertManager(cfg.webhook_url)
        self.counters = {t.name: RollingCounter(cfg.bucket_s, cfg.slo_period_s) for t in cfg.targets}
        self.registry = Registry()
        self._last_status: dict = {}
        self._describe_metrics()

    def _describe_metrics(self) -> None:
        r = self.registry
        r.describe("probe_requests_total", "counter", "Probes sent, by outcome")
        r.describe("probe_latency_ms", "gauge", "Latency of the most recent probe in milliseconds")
        r.describe("probe_success", "gauge", "1 if the most recent probe succeeded")
        r.describe("slo_objective_ratio", "gauge", "Configured SLO target")
        r.describe("slo_sli_ratio", "gauge", "Measured SLI over the SLO period")
        r.describe("slo_error_budget_remaining_ratio", "gauge", "Fraction of error budget left in the period")
        r.describe("slo_burn_rate", "gauge", "Error-budget burn rate over a window")
        r.describe("slo_alert_firing", "gauge", "1 if a burn-rate alert is firing")
        r.describe("slo_monitor_last_eval_timestamp_seconds", "gauge", "Unix time of the last evaluation loop")

    # one tick of the loop
    def tick(self) -> None:
        with ThreadPoolExecutor(max_workers=max(1, len(self.cfg.targets))) as pool:
            results = list(pool.map(lambda t: self.prober(t, self.clock), self.cfg.targets))
        for res in results:
            self.record(res)
        self.evaluate()

    def record(self, res: ProbeResult) -> None:
        target = next(t for t in self.cfg.targets if t.name == res.target)
        thresholds = [s.threshold_ms for s in target.slos if s.kind == "latency"]
        slow = bool(thresholds) and res.latency_ms > min(thresholds)
        self.counters[res.target].record(res.ts, res.ok, slow)
        self.registry.inc("probe_requests_total", target=res.target, outcome="success" if res.ok else "failure")
        self.registry.set("probe_latency_ms", round(res.latency_ms, 2), target=res.target)
        self.registry.set("probe_success", 1 if res.ok else 0, target=res.target)
        if not res.ok:
            log.info("probe failed target=%s status=%s error=%s latency_ms=%.0f",
                     res.target, res.status, res.error, res.latency_ms)

    def evaluate(self) -> None:
        now = self.clock()
        status = {"evaluated_at": now, "targets": {}}
        for t in self.cfg.targets:
            counter = self.counters[t.name]
            period = counter.counts(now, self.cfg.slo_period_s)
            tstatus = status["targets"][t.name] = {}
            for s in t.slos:
                rate = slomath.error_rate(s, period)
                remaining = slomath.budget_remaining(s, period)
                labels = {"target": t.name, "slo": s.name}
                self.registry.set("slo_objective_ratio", s.objective, **labels)
                if rate is not None:
                    self.registry.set("slo_sli_ratio", round(1 - rate, 6), **labels)
                self.registry.set("slo_error_budget_remaining_ratio", round(remaining, 6), **labels)

                rules_out = []
                for rule in self.cfg.rules:
                    result = slomath.evaluate_rule(
                        s, rule,
                        counter.counts(now, rule.long_window_s),
                        counter.counts(now, rule.short_window_s),
                        self.cfg.min_samples,
                    )
                    for win, val in ((rule.long_window_s, result.long_burn), (rule.short_window_s, result.short_burn)):
                        if val is not None:
                            self.registry.set("slo_burn_rate", round(val, 3), window=f"{win}s", **labels)
                    self.registry.set("slo_alert_firing", 1 if result.firing else 0, severity=rule.severity, **labels)
                    details = {
                        "objective": s.objective,
                        "long_window_s": rule.long_window_s, "short_window_s": rule.short_window_s,
                        "threshold": rule.burn_rate,
                        "long_burn": None if result.long_burn is None else round(result.long_burn, 2),
                        "short_burn": None if result.short_burn is None else round(result.short_burn, 2),
                        "budget_remaining": round(remaining, 4),
                    }
                    self.alerts.update(t.name, s.name, rule.severity, result.firing, details)
                    rules_out.append({"severity": rule.severity, "firing": result.firing, **details})

                tstatus[s.name] = {
                    "kind": s.kind,
                    "objective": s.objective,
                    "sli": None if rate is None else round(1 - rate, 6),
                    "error_budget_remaining": round(remaining, 4),
                    "events_in_period": slomath.bad_and_valid(s, period)[1],
                    "rules": rules_out,
                }
        self.registry.set("slo_monitor_last_eval_timestamp_seconds", round(now, 3))
        self._last_status = status

    def status(self) -> dict:
        return self._last_status

    def run_forever(self) -> None:
        log.info("monitoring %d target(s) every %.1fs", len(self.cfg.targets), self.cfg.probe_interval_s)
        while True:
            started = time.monotonic()
            try:
                self.tick()
            except Exception:   # one bad loop iteration must not kill the monitor
                log.exception("evaluation loop failed")
            time.sleep(max(0.0, self.cfg.probe_interval_s - (time.monotonic() - started)))
