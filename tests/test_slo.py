import unittest

from slo_monitor import slo as m
from slo_monitor.config import SLO, BurnRateRule
from slo_monitor.window import Counts, RollingCounter

AVAIL = SLO("availability", "availability", 0.999)
LAT = SLO("latency", "latency", 0.99, threshold_ms=300)


class TestSloMath(unittest.TestCase):
    def test_error_budget(self):
        self.assertAlmostEqual(AVAIL.error_budget, 0.001)

    def test_burn_rate_of_one_means_exactly_on_budget(self):
        c = Counts(total=10_000, failed=10, slow=0)        # 0.1% errors at a 99.9% SLO
        self.assertAlmostEqual(m.burn_rate(AVAIL, c), 1.0)

    def test_burn_rate_scales_with_errors(self):
        c = Counts(total=1000, failed=20, slow=0)          # 2% errors / 0.1% budget
        self.assertAlmostEqual(m.burn_rate(AVAIL, c), 20.0)

    def test_no_data_is_not_an_outage(self):
        self.assertIsNone(m.burn_rate(AVAIL, Counts(0, 0, 0)))
        self.assertEqual(m.budget_remaining(AVAIL, Counts(0, 0, 0)), 1.0)

    def test_budget_can_go_negative(self):
        c = Counts(total=1000, failed=3, slow=0)           # 3 bad, 1 allowed
        self.assertAlmostEqual(m.budget_remaining(AVAIL, c), -2.0)

    def test_latency_sli_ignores_failed_probes(self):
        # 100 probes: 10 failed (availability's problem), 9 slow out of the 90 that succeeded
        c = Counts(total=100, failed=10, slow=9)
        bad, valid = m.bad_and_valid(LAT, c)
        self.assertEqual((bad, valid), (9, 90))


class TestMultiWindowRule(unittest.TestCase):
    rule = BurnRateRule("page", long_window_s=3600, short_window_s=300, burn_rate=14.4)

    def test_fires_when_both_windows_burn(self):
        r = m.evaluate_rule(AVAIL, self.rule, Counts(1000, 20, 0), Counts(100, 2, 0), min_samples=10)
        self.assertTrue(r.firing)

    def test_does_not_fire_if_problem_already_stopped(self):
        # The long window is still hot, but the last 5 minutes are clean, so the alert resets fast.
        r = m.evaluate_rule(AVAIL, self.rule, Counts(1000, 20, 0), Counts(100, 0, 0), min_samples=10)
        self.assertFalse(r.firing)

    def test_does_not_fire_on_a_short_blip(self):
        # The short window is on fire, but the long window shows it's too small to matter.
        r = m.evaluate_rule(AVAIL, self.rule, Counts(100_000, 2, 0), Counts(100, 2, 0), min_samples=10)
        self.assertFalse(r.firing)

    def test_min_samples_guard(self):
        # 1 failure out of 2 probes is a 50% error rate, but that's too little data to page anyone.
        r = m.evaluate_rule(AVAIL, self.rule, Counts(2, 1, 0), Counts(2, 1, 0), min_samples=10)
        self.assertFalse(r.firing)


class TestRollingCounter(unittest.TestCase):
    def test_window_and_eviction(self):
        rc = RollingCounter(bucket_s=10, retention_s=100)
        for t in range(0, 200):                # one event per second for 200s
            rc.record(float(t), ok=(t % 10 != 0), slow=False)
        now = 199.0
        last_30 = rc.counts(now, 30)
        # Windows are rounded UP to whole buckets: the 30s window includes the partial
        # bucket [160,170), so we see 40 events. That's the precision we trade for bounded memory.
        self.assertEqual(last_30.total, 40)
        self.assertEqual(last_30.failed, 4)
        # With 1s buckets it's exact: [169, 199] inclusive covers 31 one-second samples.
        exact = RollingCounter(bucket_s=1, retention_s=100)
        for t in range(0, 200):
            exact.record(float(t), ok=True, slow=False)
        self.assertEqual(exact.counts(now, 30).total, 31)
        self.assertLessEqual(len(rc), 11)      # old buckets were evicted, so memory is bounded

    def test_slow_only_counted_for_successes(self):
        rc = RollingCounter(bucket_s=1, retention_s=60)
        rc.record(0.0, ok=False, slow=True)
        rc.record(0.5, ok=True, slow=True)
        c = rc.counts(1.0, 60)
        self.assertEqual((c.total, c.failed, c.slow), (2, 1, 1))


if __name__ == "__main__":
    unittest.main()
