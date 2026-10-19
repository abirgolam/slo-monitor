# slo-monitor

[![CI](https://github.com/abirgolam/slo-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/abirgolam/slo-monitor/actions/workflows/ci.yml)

A small, **dependency-free** service-level-objective monitor. It probes HTTP services, measures SLIs, tracks the **error budget**, and alerts using **multi-window, multi-burn-rate** rules from the Google SRE Workbook. It exports Prometheus metrics and ships with a chaos-injection demo service, Docker Compose, CI, a runbook, and a postmortem template.

> **Why build this?** "CPU > 90%" alerts page people for things users never notice, and they miss things users do notice. SLO-based alerting asks one question: *are users getting a good experience, and how fast are we using up our allowance for failure?*

## Core ideas in 60 seconds

| Term | Meaning | Example |
|---|---|---|
| **SLI** | Measured good events ÷ valid events | 99.95% of probes returned 200 |
| **SLO** | The target for the SLI | 99.9% over 30 days |
| **Error budget** | `1 − SLO`: how much failure is allowed | 0.1% ≈ 43 minutes/month |
| **Burn rate** | `observed error rate ÷ error budget` | 1x = on pace to use exactly the budget; 14.4x = a 30-day budget gone in ~2 days |

**Analogy:** the error budget is a monthly data plan. Burn rate is how fast you're streaming. A short spike doesn't matter; a sustained burn at 14x does.

### Why multi-window alerting?

Each alert rule checks **two** windows, and both must exceed the threshold:

- **Long window (e.g. 1h):** proves the problem is *significant* enough to matter, so a 30-second blip won't page anyone.
- **Short window (e.g. 5m):** proves it is *still happening*, so the alert resolves within minutes of a fix rather than an hour later.

| Severity | Long | Short | Burn rate | Budget consumed when it fires |
|---|---|---|---|---|
| page | 1h | 5m | 14.4 | 2% |
| page | 6h | 30m | 6 | 5% |
| ticket | 3d | 6h | 1 | 10% |

## Architecture

```
            ┌──────────────── slo-monitor ─────────────────┐
 HTTP probe │  prober ──► RollingCounter ──► SLO math       │  /metrics ──► Prometheus ──► alerts.yml
 ─────────► │  (urllib)   (time buckets,    (SLI, budget,   │  /status  ──► humans / scripts
  targets   │             bounded memory)   burn rate)      │  /healthz ──► Docker HEALTHCHECK
            │                                  │            │
            │                          AlertManager ────────┼──► log (JSON) + Slack-style webhook
            │                     (FIRING/RESOLVED only)    │
            └──────────────────────────────────────────────┘
```

Design decisions:

- **Standard library only.** No `pip install`, so there's no dependency supply chain to audit, which matters in regulated or air-gapped (e.g. GovCloud) environments. The Prometheus text format is simple enough to implement directly.
- **Time-bucketed counters.** Memory is bounded by `period ÷ bucket_s` (43,200 buckets for 30 days at 60s), not by probe count. The tradeoff: windows round up to whole buckets.
- **The latency SLI only counts successful probes**, so one timeout isn't penalized twice (availability already counts it).
- **`min_samples` guard.** One failure in two probes is a "50% error rate", but it isn't enough evidence to page anyone.
- **Alerts on state change only.** One FIRING and one RESOLVED notification per incident, which avoids alert fatigue.
- **Fail fast.** An invalid config exits with code 2 at startup rather than failing silently later.
- **Monitoring the monitor.** The `SLOMonitorDown` and `SLOMonitorStale` rules catch the case where the alerting itself is broken.

## Quick start

### Option A: Docker Compose (monitor + demo service + Prometheus)

```bash
docker compose up --build
# Prometheus: http://localhost:9090/alerts     Monitor: http://localhost:9105/status
```

### Option B: Plain Python 3.11+

```bash
python demo/flaky_service.py --port 8080 &      # the service under test
python -m slo_monitor --config config.toml      # the monitor
```

### Break something and watch the alert fire

```bash
# Inject a 50% error rate plus ~400ms of latency
curl -X POST "localhost:8080/chaos?error_rate=0.5&latency_ms=400"
watch -n1 'curl -s localhost:9105/status | head -40'

# Recover, and watch the alert RESOLVE within one short window
curl -X POST "localhost:8080/chaos?error_rate=0&latency_ms=0"
```

`config.toml` compresses time (a 10-minute "month", 60s/10s page windows) so the whole cycle takes about a minute. `config.production.example.toml` uses the real 30-day windows.

## Metrics

| Metric | Type | Labels |
|---|---|---|
| `probe_requests_total` | counter | target, outcome |
| `probe_success`, `probe_latency_ms` | gauge | target |
| `slo_sli_ratio`, `slo_objective_ratio` | gauge | target, slo |
| `slo_error_budget_remaining_ratio` | gauge | target, slo |
| `slo_burn_rate` | gauge | target, slo, window |
| `slo_alert_firing` | gauge | target, slo, severity |
| `slo_monitor_last_eval_timestamp_seconds` | gauge | |

## Tests

```bash
python -m unittest discover -s tests -t . -v
```

- **Unit tests:** burn-rate math, budget overspend, the latency SLI denominator, the multi-window rule (fires / doesn't fire on a blip / resets fast after recovery / `min_samples`), and bucket eviction.
- **Integration test:** starts the flaky service, injects a full outage, and asserts exactly one FIRING and one RESOLVED webhook. A fake clock means it runs in under a second.
- **CI (GitHub Actions):** lint (ruff), tests on Python 3.11–3.13, Docker build, and a container smoke test.

## Ops docs

- [`docs/RUNBOOK.md`](docs/RUNBOOK.md): what to do for each alert (every alert links to it)
- [`docs/POSTMORTEM-TEMPLATE.md`](docs/POSTMORTEM-TEMPLATE.md): a blameless postmortem format

## Limitations and next steps

- State is in memory, so a restart resets the windows. Next step: compute burn rates in PromQL from `probe_requests_total` (Prometheus keeps the history) or persist the buckets.
- Black-box probes measure *a* user, not *all* users. In production, pair them with request-based SLIs from load-balancer or service logs.
- Single instance. For HA, run probers in multiple regions and alert on consensus to avoid false positives from network partitions.
- Add a Grafana dashboard and a Kubernetes manifest.

## Project layout

```
slo_monitor/   config · window (buckets) · slo (math) · prober · alerts · metrics · monitor (loop)
demo/          flaky_service.py (chaos-injectable HTTP service)
deploy/        prometheus.yml · alerts.yml · config.docker.toml
docs/          RUNBOOK.md · POSTMORTEM-TEMPLATE.md
tests/         unit + integration
```

## License

MIT © Abir Golam
