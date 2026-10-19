"""SLO math: SLIs, error budget, burn rate, and the multi-window alert decision.

Definitions (from the Google SRE Workbook):
  SLI          = good events / valid events
  error budget = 1 - SLO              (99.9% gives a 0.1% budget)
  burn rate    = observed error rate / error budget
                 1.0  -> the budget runs out exactly at the end of the period
                 14.4 -> a 30-day budget is gone in about 2 days
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import SLO, BurnRateRule
from .window import Counts


def bad_and_valid(slo: SLO, c: Counts) -> tuple[int, int]:
    """Return (bad events, valid events) for an SLO.

    availability: every probe is valid; a failed probe is bad.
    latency:      only successful probes are valid (a timeout is already
                  counted against availability, so don't double-penalize);
                  a slow success is bad.
    """
    if slo.kind == "availability":
        return c.failed, c.total
    return c.slow, c.succeeded


def error_rate(slo: SLO, c: Counts) -> float | None:
    bad, valid = bad_and_valid(slo, c)
    if valid == 0:
        return None
    return bad / valid


def burn_rate(slo: SLO, c: Counts) -> float | None:
    rate = error_rate(slo, c)
    return None if rate is None else rate / slo.error_budget


def budget_remaining(slo: SLO, c: Counts) -> float:
    """Fraction of the period's error budget left. Can go negative (overspent)."""
    bad, valid = bad_and_valid(slo, c)
    if valid == 0:
        return 1.0
    allowed_bad = slo.error_budget * valid
    return 1.0 - bad / allowed_bad


@dataclass(frozen=True)
class RuleResult:
    rule: BurnRateRule
    long_burn: float | None
    short_burn: float | None
    firing: bool


def evaluate_rule(slo: SLO, rule: BurnRateRule, long_c: Counts, short_c: Counts,
                  min_samples: int) -> RuleResult:
    lb, sb = burn_rate(slo, long_c), burn_rate(slo, short_c)
    _, short_valid = bad_and_valid(slo, short_c)
    firing = (
        lb is not None and sb is not None
        and short_valid >= min_samples          # too little data to be confident
        and lb >= rule.burn_rate
        and sb >= rule.burn_rate
    )
    return RuleResult(rule, lb, sb, firing)
