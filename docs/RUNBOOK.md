# Runbook: slo-monitor alerts

Every alert links here. The goal is that an on-call engineer at 3am can act **without** needing to understand the codebase.

General first steps for any alert:
1. Check `http://<monitor>:9105/status` for the current SLI, burn rates, and remaining budget for each SLO.
2. Check what changed: recent deploys, config changes, feature flags, or upstream provider status pages.
3. **Mitigate first, root-cause second.** Rolling back is usually faster than debugging forward.

---

## SLOBurnRate (page)

**Meaning:** the service is consuming error budget at ≥14.4x the sustainable rate in *both* the long and short windows. At this pace a 30-day budget lasts about 2 days. This alert uses real user-facing impact, not a CPU threshold.

**Triage**
1. Is it availability or latency? (The `slo` label tells you.)
2. Did it start right after a deploy? If so, **roll back** first and investigate afterwards.
3. Is it every request or a subset? Check by endpoint, region, or instance if you have that data.
4. Is a dependency down (database, auth, DNS, cloud provider)?

**Mitigation options:** roll back, shift traffic away from the bad region or instance, scale out, disable the offending feature flag, or shed non-critical load.

**Escalate** if the cause isn't identified within 30 minutes, or if customer data or security could be involved.

## SLOBurnRate (ticket)

**Meaning:** a slow, sustained burn (≥6x). Not an emergency, but the budget will be gone before the period ends if nothing changes. Handle during business hours: open a ticket, find the trend, and fix it.

## ErrorBudgetExhausted

**Meaning:** the service has missed its SLO for this period.
**Policy:** freeze risky feature launches for this service, and prioritize reliability work until the budget recovers. This is the agreement that makes SLOs useful: it turns "reliability vs. velocity" from an argument into a rule.

## SLOMonitorDown

**Meaning:** the monitor itself is down or stuck, so **all SLO alerting is blind** right now.
1. `docker compose ps` / `kubectl get pods`: is it running? Is it crash-looping?
2. Check the logs. An `invalid config` message means a bad config was deployed; revert it (the process exits with code 2 on purpose).
3. Restart it. While it's down, check the protected services manually.
