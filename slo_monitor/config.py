"""Load and validate the TOML config into typed dataclasses.

The goal is to fail fast at startup with a clear error message instead of
failing at 3am with a KeyError.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class SLO:
    name: str
    kind: str                  # "availability" or "latency"
    objective: float           # e.g. 0.999 means 99.9% of events must be good
    threshold_ms: float | None = None   # latency SLOs only

    @property
    def error_budget(self) -> float:
        """Fraction of events allowed to be bad. A 99.9% SLO has a 0.1% budget."""
        return 1.0 - self.objective


@dataclass(frozen=True)
class Target:
    name: str
    url: str
    timeout_s: float = 2.0
    expected_status: tuple[int, ...] = (200,)
    slos: tuple[SLO, ...] = ()


@dataclass(frozen=True)
class BurnRateRule:
    """One row of the multi-window, multi-burn-rate alert policy.

    The rule fires only when BOTH windows burn faster than `burn_rate`:
      * the long window proves the problem is significant
      * the short window proves it is still happening (fast reset)
    """
    severity: str          # "page" or "ticket"
    long_window_s: int
    short_window_s: int
    burn_rate: float


@dataclass(frozen=True)
class Config:
    probe_interval_s: float
    slo_period_s: int                  # error-budget period (30d in prod)
    bucket_s: int                      # aggregation granularity (bounds memory)
    min_samples: int                   # don't alert on 1 failure out of 2 probes
    listen_port: int
    webhook_url: str | None
    targets: tuple[Target, ...]
    rules: tuple[BurnRateRule, ...] = field(default_factory=tuple)


def _require(d: dict, key: str, ctx: str):
    if key not in d:
        raise ConfigError(f"{ctx}: missing required key '{key}'")
    return d[key]


def _parse_slo(raw: dict, ctx: str) -> SLO:
    kind = _require(raw, "kind", ctx)
    if kind not in ("availability", "latency"):
        raise ConfigError(f"{ctx}: kind must be 'availability' or 'latency', got {kind!r}")
    objective = float(_require(raw, "objective", ctx))
    if not 0.0 < objective < 1.0:
        raise ConfigError(f"{ctx}: objective must be between 0 and 1 (e.g. 0.999), got {objective}")
    threshold = raw.get("threshold_ms")
    if kind == "latency" and threshold is None:
        raise ConfigError(f"{ctx}: latency SLOs need threshold_ms")
    return SLO(name=_require(raw, "name", ctx), kind=kind,
               objective=objective, threshold_ms=threshold)


def parse(raw: dict) -> Config:
    g = raw.get("global", {})
    targets = []
    for i, t in enumerate(_require(raw, "targets", "config")):
        ctx = f"targets[{i}]"
        slos = tuple(_parse_slo(s, f"{ctx}.slos[{j}]") for j, s in enumerate(t.get("slos", [])))
        if not slos:
            raise ConfigError(f"{ctx}: at least one SLO is required")
        targets.append(Target(
            name=_require(t, "name", ctx),
            url=_require(t, "url", ctx),
            timeout_s=float(t.get("timeout_s", 2.0)),
            expected_status=tuple(t.get("expected_status", [200])),
            slos=slos,
        ))

    rules = []
    for i, r in enumerate(raw.get("alert_rules", [])):
        ctx = f"alert_rules[{i}]"
        rule = BurnRateRule(
            severity=_require(r, "severity", ctx),
            long_window_s=int(_require(r, "long_window_s", ctx)),
            short_window_s=int(_require(r, "short_window_s", ctx)),
            burn_rate=float(_require(r, "burn_rate", ctx)),
        )
        if rule.short_window_s >= rule.long_window_s:
            raise ConfigError(f"{ctx}: short_window_s must be smaller than long_window_s")
        rules.append(rule)

    return Config(
        probe_interval_s=float(g.get("probe_interval_s", 10)),
        slo_period_s=int(g.get("slo_period_s", 30 * 24 * 3600)),
        bucket_s=int(g.get("bucket_s", 10)),
        min_samples=int(g.get("min_samples", 10)),
        listen_port=int(g.get("listen_port", 9105)),
        webhook_url=g.get("webhook_url") or None,
        targets=tuple(targets),
        rules=tuple(rules),
    )


def load(path: str | Path) -> Config:
    with open(path, "rb") as f:
        return parse(tomllib.load(f))
