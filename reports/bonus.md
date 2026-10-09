# Stretch goals and understanding the drill

## Scope
The rubric's 100 points concern the main drill. GUIDE lists six optional stretch goals, without bonus point weights. This report distinguishes executed experiments from drafts and unexecuted extensions.

## Randomized chaos — five runs completed
Seed 23 chooses kill timing between 7 and 12 seconds after traffic starts and mode stop/netblock. Each run uses 52 seconds of real traffic, interval 5s, threshold 3, warm standby, six-second compute warm-up and the existing readiness-gated failover. Raw chaos/health/failover/runbook/traffic JSONL is retained in each run directory. Data is fixed and freshly snapshotted before each attack; RPO 0 is expected here. The separate main drill exercises continuous ingest and nonzero RPO.

| Run | Kill delay | Mode | Measured RTO | Evidence |
|---|---|---|---|---|
| 1 | 11.624s | netblock | 34.9s | reports/bonus-chaos/run-1/measure.json |
| 2 | 11.462s | stop | 34.7s | reports/bonus-chaos/run-2/measure.json |
| 3 | 7.085s | netblock | 35.0s | reports/bonus-chaos/run-3/measure.json |
| 4 | 9.119s | netblock | 32.7s | reports/bonus-chaos/run-4/measure.json |
| 5 | 7.652s | stop | 34.5s | reports/bonus-chaos/run-5/measure.json |

All five measurement results have valid=true, no warnings, PASS and recovery served by B. Arithmetic mean of the tool-rounded RTO values is 34.36s; sample standard deviation (n-1 denominator) is 0.948s. Sources: `reports/bonus-chaos/summary.json:179` and `reports/bonus-chaos/summary.json:180`. This small sample does not establish a tail-latency guarantee or a statistically supported difference between failure modes.

Run 4 detects after 13.1s, illustrating why interval × threshold is a nominal lab budget rather than a universal lower bound: outage phase relative to scheduled probes matters. No log or test was changed to hide this. The rubric's strict detection-budget gate applies to the main drill, whose observed 15.3s detection passes it.

The original run 1 overlapped a unit test that changed B's pool to full, invalidating comparison of its warm-up. That attempt was archived under reports/previous-attempts/bonus-run-1-test-interference and replaced by a clean run with the same seed-derived delay/mode. The summary contains only the clean five runs. To repeat on Windows, archive the existing bonus-chaos directory first and run python dr/bonus_chaos.py after freeing the three lab ports; do not run pool-mutating unit tests during drills.

## Terraform — write-only draft completed
See dr/bonus_s3.tf. Both existing buckets get versioning and the source gets an S3 replication rule for all three snapshot artifacts. IAM role and two bucket names/regions are supplied variables. No cloud deployment, terraform plan or provider validation was run; terraform fmt / fmt -check parsed and formatted the HCL successfully.

Mapping: snapshot.put writes vectors.sqlite, model.bin and MANIFEST.json; S3 replication carries their object versions to another region; snapshot.get consumes the replica. Lab embedding version identifies index compatibility, while S3 object version IDs identify exact artifact revisions. These are different kinds of versioning. A manifest should reference immutable snapshot keys, exact object versions and checksums: independently replicating mutable keys is not an atomic multi-object snapshot. Publish a commit manifest after artifacts and verify all referenced objects before restore.

Reference: [HashiCorp resource documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_replication_configuration). This is a draft for existing same-account, non-KMS buckets and an existing appropriately authorized replication role, not a complete production infrastructure module.

## DR maturity self-assessment
Working assessment: approximately Level 2, meaning a tested recovery procedure with backups, independent process monitoring and human-approved automation. The slide deck defining the official Level 0–4 scale is absent from this repository, so this label is provisional rather than a verified match to the slide taxonomy.

Evidence: measured main RTO 35.3s, non-null RPO 12.01s / 6 docs, ready-before-cutover, a seven-step runbook, and postmortem with ownership. Local regions and replica still share one host; a whole-host outage defeats the lab. No durable multi-host control plane, fully exercised failback, long-running SLO check or automatic circuit breaker exists.

Next improvement: deploy monitor and durable versioned replicas in independent failure domains, test reconciliation and approved failback, then schedule repeated game days and prove both RTO and RPO across realistic failures. Automation alone does not establish higher maturity without repeated evidence and common-mode failure protection.

## Extensions not executed
Real MinIO: docker CLI exists, but docker info could not connect to dockerDesktopLinuxEngine because the daemon is not running. No fs-versus-MinIO latency comparison is claimed.

Postgres PITR: no metadata store, pg_basebackup, WAL archive or point-in-time restore experiment was provisioned. No PITR RTO is claimed.

Active-active: production serving/edge files are intentionally unchanged in accordance with the core assignment. No 50/50 concurrent serving experiment is claimed. A design would need globally unique document IDs, idempotent ingest, a defined write owner or conflict rule, replication-lag monitoring and embedding-version compatibility before splitting traffic. Scaling B to full alone is insufficient evidence of active-active correctness.

## Main insights
Liveness does not imply readiness: baseline B is alive but lacks data/weights. Backup is not the same operation as restore. Ready-before-cutover protects users from sending traffic to a second unusable region. RTO ends at the first observed successful user request, later than the routing change. RPO concerns missing state at restore and must include both time and document count. In this simulator ingest continues despite the API outage, so a restore-time count is not a guarantee about permanently lost production writes.

No screenshots are required by GUIDE or RUBRIC; raw JSONL and report references are the evidence.
