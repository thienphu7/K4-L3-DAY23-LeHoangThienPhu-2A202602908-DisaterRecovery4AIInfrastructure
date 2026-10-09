# Blameless Postmortem — Lab 23

## Timeline
All times below are UTC on 2026-10-09; Bangkok time is UTC + 7.
| Time | Event | Evidence |
|---|---|---|
| 04:37:33.150 | Outage begins (11:37:33.150 Bangkok) | `chaos/chaos-events.jsonl:3` |
| 04:37:33.614 | First failed user request starts | `reports/drill-2-withdr.jsonl:25` |
| 04:37:48.474 | Threshold alert | `reports/health-events.jsonl:2` |
| 04:37:57.976 | Operator automation confirms incident | `reports/runbook-run.jsonl:2` |
| 04:37:58.031 | Restore complete | `reports/failover-events.jsonl:2` |
| 04:38:04.271 | B ready | `reports/failover-events.jsonl:4` |
| 04:38:04.299 | Cutover | `reports/failover-events.jsonl:5` |
| 04:38:08.494 | First successful request from B starts | `reports/drill-2-withdr.jsonl:42` |

## RTO/RPO gap analysis
RTO target 300s, measured 35.3s, signed gap (measured minus target) -264.7s.
RPO target 300s, measured 12.01s / 6 docs missing, signed gap -287.99s.
Evidence: `reports/measure-drill-2.json`, `reports/failover-events.jsonl:2`.

Largest component: detection 15.324s. Confirmation/verification adds 9.533s, GPU readiness 6.240s, and cache/sample delay 4.196s. Restore is only 0.024s because local weights are tiny. These timings cannot predict multi-GB model transfer. Golden signals p95 31 ms, errors 0/10 (`reports/runbook-run.jsonl:6`) validate only a short sample.

## Root cause — five whys
1. Requests fail because edge keeps routing to unavailable A (traffic line 25).
2. B cannot immediately serve because its pool is warm, weights absent, vectors empty (failover line 1).
3. Snapshot storage alone does not make B ready: restore, compute scale and readiness checks are separate steps (failover lines 2–4).
4. Recovery lags readiness because edge caches its selected upstream and traffic sampling is discrete (traffic line 42).
5. A real whole-machine failure still defeats the local lab: monitor, replica and both regions share one host. Production needs independent failure domains and a tested durable control plane.

Deployment and recovery process explain the exposure; blaming the person running chaos explains nothing. A real outage might expose missing/incompatible backup, lost incident tooling or failed operator authorization. The readiness gate prevents premature cutover but does not prove all production failure cases.

## Action items — proposals, not measured savings
| Action | Owner role | Deadline (Bangkok) | Expected benefit |
|---|---|---|---|
| Reuse fresh threshold alert in confirmation, retain human approval | DR maintainer | 2026-10-12 | Up to about 9s less duplicate confirmation; remeasure |
| Keep B full during high-risk releases | Serving on-call | 2026-10-13 | About 6s warm-up saving, higher compute cost |
| Trial replication every 10s and coherent versioned snapshots | Data platform maintainer | 2026-10-14 | Smaller data exposure; exact doc savings unknown |
| Separate monitor/replica/serving failure domains; add failback circuit breaker | Infrastructure owner | 2026-10-16 | Reduce common-host risk; no supported seconds estimate |

## Required answers and reflection
1. interval × threshold = 5 × 3 = 15s, 42.5% of measured RTO. Observed detection is 15.324s; probe phase and timeout matter.
2. Interval 1s gives nominal budget 3s, 12s less. Actual saving must be measured because 2s timeouts can exceed the interval; probes increase roughly fivefold and correlated transient errors can trigger faster failover. Keeping B full reduces warm-up without altering alert sensitivity but costs compute.
3. If A is permanently lost for six hours, the 6 docs absent at restore may represent missing tickets or retrieval knowledge. They are not permanently destroyed in this local exercise because A's disk remains. Six hours does not multiply this count; later acknowledged writes need separate accounting.
4. Health checker runs separately and imports no serving implementation. A monitor inside the failed process would be silent; production also needs separate monitoring infrastructure.
5. To substantiate the five-minute claim, read measure-drill-2.json, then trace recovery to traffic line 42 and outage to chaos line 3.
