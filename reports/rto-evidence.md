# RTO/RPO Evidence — Lab 23
Windows bare-mode, 2026-10-09. The runner maps Unix suspension/resume to Windows NtSuspendProcess/NtResumeProcess. Serving, loadgen, measurement and chaos safety checks remain unchanged. This is a Windows adaptation, not a claim of Linux execution.

## 1. Baseline
| Metric | Value | Evidence |
|---|---|---|
| Outage UTC | 2026-10-09T04:36:43 | `chaos/chaos-events.jsonl:1` |
| First failed request | +0.4s | `reports/drill-1-nodr.jsonl:17` |
| Failed requests after outage | 16 | `reports/measure-drill-1.json` |
| Recovery | NO_RECOVERY within the 40-second experiment | `reports/measure-drill-1.json` |

Baseline has no checker/cutover; missing-event warnings are expected. NO_RECOVERY is bounded by the observed window.

## 2. DR timeline
| Milestone | Seconds from outage | Evidence |
|---|---|---|
| Outage UTC 04:37:33 | 0s | `chaos/chaos-events.jsonl:3` |
| First user error | 0.5s | `reports/drill-2-withdr.jsonl:25` |
| A detected UNHEALTHY | 15.3s | `reports/health-events.jsonl:2` |
| Incident / operator confirmation | 24.8s | `reports/runbook-run.jsonl:2` |
| Restore complete | 24.9s | `reports/failover-events.jsonl:2` |
| B ready | 31.1s | `reports/failover-events.jsonl:4` |
| DNS/LB cutover | 31.1s | `reports/failover-events.jsonl:5` |
| First recovered request from B | 35.3s | `reports/drill-2-withdr.jsonl:42` |

| Metric | Measured | Target | Verdict | Evidence |
|---|---|---|---|---|
| Inference RTO | 35.3s | 300s | PASS | `reports/measure-drill-2.json` |
| Vector DB RPO at restore | 12.01s / 6 docs missing | 300s | PASS | `reports/failover-events.jsonl:2` |
| Validity | true, warnings empty | valid drill | PASS | `reports/measure-drill-2.json` |
| Direct B golden signals | p95 31 ms, 0/10 errors | p95 <500 ms, errors <1% | PASS for this sample | `reports/runbook-run.jsonl:6` |

B restored 215 documents, weights and vi-e5-base@v3 embedding version: `reports/runbook-run.jsonl:4`. Golden signals address B directly; edge recovery is separately proven by traffic line 42.

## 3. RTO composition
| Component | Duration | Evidence / derivation | Improvement |
|---|---|---|---|
| Configured health detect floor | 15.000s | interval 5 × threshold 3; `reports/health-events.jsonl:2` | Faster polling costs more probes and greater sensitivity to transient failures |
| Detection phase/timeout residual | 0.324s | actual detection minus configured budget; `chaos/chaos-events.jsonl:3`, `reports/health-events.jsonl:2` | Parallel, deadline-aware probes |
| Confirmation / incident / target verification | 9.533s | detect to verify; `reports/runbook-run.jsonl:1`, `reports/failover-events.jsonl:1` | Reuse recent alert evidence, keep operator approval |
| Snapshot restore | 0.024s | restore minus verify; `reports/failover-events.jsonl:2` | Incremental snapshots for real large models |
| GPU warm-up and ready polling | 6.240s | ready minus scale; waited_s=6.235; `reports/failover-events.jsonl:4` | Full standby costs compute |
| Ready-to-cutover bookkeeping | 0.028s | cutover minus ready; `reports/failover-events.jsonl:5` | Negligible here |
| DNS/LB cache plus next traffic sample | 4.196s | first recovered request minus cutover; `reports/drill-2-withdr.jsonl:42` | Lower TTL costs control-plane work |
| Total before rounding | 35.345s | sum of disjoint intervals, rounds to 35.3s | Optimize largest contributor first |

The four named components alone omit confirmation overhead. TTL is configured to 5 seconds; remaining cache lifetime depends on phase. Loadgen timestamps request starts, not completions.

GUIDE calls interval × threshold a floor. Precisely, scheduled instantaneous probes may detect after roughly 10–15 seconds depending on phase; timeouts and sequential probing add delay. Observed detection 15.324 seconds satisfies the rubric's configured budget check.

RPO uses latest primary minus latest restored document timestamp and counts missing docs from SQLite at restore. Ingest and replication read the filesystem independently and continue while the serving API is suspended. This simulator does not demonstrate loss of all region storage or a production guarantee for acknowledged writes. Later primary writes are not included in restore-time loss.
