# Runbook — Primary Region Down
Run from repository root with conda environment labs activated. Before incident: run `python dr/health_checker.py --interval 5 --threshold 3 --duration 300 --out reports/health-events.jsonl` independently. Confirm backup exists with `python state/snapshot.py lag --backend fs`. snapshot get RESTORES target state; use /v1/state to inspect it.

| # | Step | Copy-paste command / operation | Done when | Owner |
|---|---|---|---|---|
| 1 | Confirm outage | `python chaos/kill_region.py status` and `Get-Content reports/health-events.jsonl -Tail 5` | A fails 3 readiness checks, B alive | on-call |
| 2 | Incident and authorization | `python dr/runbook.py --primary a --target b --backend fs`, type y | outage + announcement timestamps recorded; this single invocation executes steps 3–6 | incident commander |
| 3 | Restore snapshot | `Get-Content reports/failover-events.jsonl -Tail 5` | 2_restore_snapshot records RPO, docs_lost, embedding version | data on-call |
| 4 | Scale pool / readiness | `curl.exe http://localhost:8002/readyz` | HTTP 200, ready true; 4_wait_ready exists | serving on-call |
| 5 | Verify cutover | `curl.exe http://localhost:8080/edge/state` | active_region b after TTL, 5_dns_cutover after ready | network on-call |
| 6 | Golden signals | `Get-Content reports/runbook-run.jsonl -Tail 2` and `curl.exe http://localhost:8080/v1/infer` | direct-B p95 <500 ms, errors <1%, plus edge response served by b / 200 | serving on-call |
| 7 | Measure / postmortem | `python tools/measure_rto.py --loadgen reports/drill-2-withdr.jsonl --target-rto 300` | valid true, warnings empty, PASS, RPO/doc count present | incident commander |

Steps 3–5 verify one failover call, not additional cutovers. If restore/readiness fails, inspect abort and keep incident open. Do not overwrite routing to bypass the readiness gate.

Rollback/failback requires incident commander approval. Recover A, reconcile B writes, verify compatible state/embedding version and stable readiness/signals for an agreed observation window (proposed 60s). Create fresh snapshot FROM B: `python state/snapshot.py put --region b --backend fs`. Then approved failback: `python dr/failover.py --target a --backend fs`; verify A and edge golden signals. Never restore stale pre-outage A backup over B's live writes. No automatic A↔B failover; transient probe failure does not authorize failback.

Windows reproduction: `python dr/drill_windows.py`, after stopping the three existing lab uvicorn processes. Runner archives earlier top-level JSONL attempts, records PIDs, performs real Windows suspension/resume, runs baseline/DR and stops its own services. Direct Unix-signal chaos is unsupported on Windows. Linux uses GUIDE bare scripts. --auto is reserved for drills.
