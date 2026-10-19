# Postmortem: <title>

> **Blameless.** We look for the systemic causes that let a reasonable person's action cause an outage, not for someone to blame.

| | |
|---|---|
| **Date** | YYYY-MM-DD |
| **Duration** | detection → mitigation → resolution |
| **Severity** | SEV1 / SEV2 / SEV3 |
| **Impact** | who was affected, and how (e.g. "2.1% of checkout requests returned 503 for 38 min") |
| **Error budget consumed** | e.g. "41% of the 30-day availability budget" |
| **Detected by** | alert name / customer report / engineer noticed |

## Summary
Two or three sentences a non-engineer can understand.

## Timeline (UTC)
| Time | Event |
|---|---|
| 14:02 | Deploy v2.3.1 begins |
| 14:09 | `SLOBurnRate` page fires (long 18x, short 22x) |
| 14:12 | On-call acknowledges, starts triage |
| 14:20 | Rollback started |
| 14:40 | Burn rate back under 1x; alert resolves |

## Root cause
What actually broke, and why the system allowed it.

## What went well
## What went poorly
## Where we got lucky

## Action items
| Action | Type (prevent / detect / mitigate) | Owner | Ticket |
|---|---|---|---|
| | | | |
