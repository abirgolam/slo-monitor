"""Time-bucketed event counters for answering "what happened in the last N seconds?"

Instead of storing every probe result (30 days at 1 probe/sec is 2.6M rows per
target), events are rolled up into fixed-width buckets. Memory is bounded by
slo_period / bucket_s, no matter the probe rate. This is the same tradeoff
that Prometheus and other time-series databases make.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass
class Bucket:
    start: float
    total: int = 0      # probes sent
    failed: int = 0     # error, timeout, or unexpected status
    slow: int = 0       # succeeded, but slower than the latency threshold


@dataclass(frozen=True)
class Counts:
    total: int
    failed: int
    slow: int

    @property
    def succeeded(self) -> int:
        return self.total - self.failed


class RollingCounter:
    def __init__(self, bucket_s: int, retention_s: int):
        self.bucket_s = bucket_s
        self.retention_s = retention_s
        self._buckets: deque[Bucket] = deque()

    def record(self, ts: float, ok: bool, slow: bool) -> None:
        start = ts - (ts % self.bucket_s)
        if not self._buckets or self._buckets[-1].start != start:
            self._buckets.append(Bucket(start))
        b = self._buckets[-1]
        b.total += 1
        if not ok:
            b.failed += 1
        elif slow:
            b.slow += 1
        self._evict(ts)

    def _evict(self, now: float) -> None:
        cutoff = now - self.retention_s
        while self._buckets and self._buckets[0].start + self.bucket_s <= cutoff:
            self._buckets.popleft()

    def counts(self, now: float, window_s: float) -> Counts:
        cutoff = now - window_s
        total = failed = slow = 0
        # Walk from newest to oldest and stop as soon as we leave the window.
        for b in reversed(self._buckets):
            if b.start + self.bucket_s <= cutoff:
                break
            total += b.total
            failed += b.failed
            slow += b.slow
        return Counts(total, failed, slow)

    def __len__(self) -> int:
        return len(self._buckets)
