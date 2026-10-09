"""Five randomized drills with isolated raw logs, actual RTO and sample SD."""
import json
import os
import pathlib
import random
import statistics
import subprocess
import time

from drill_windows import PY, chaos, launch, service, signal_process, wait_alive
from dr import failover, health_checker, runbook
from tools.measure_rto import measure


def main():
    base = pathlib.Path("reports/bonus-chaos")
    base.mkdir(exist_ok=True)
    results = []
    rng = random.Random(23)
    for index in range(1, 6):
        delay = rng.uniform(7, 12)
        mode = rng.choice(["stop", "netblock"])
        if os.environ.get("BONUS_RUN") and index != int(os.environ["BONUS_RUN"]):
            continue
        folder = base / f"run-{index}"
        folder.mkdir(exist_ok=True)
        chaos.EVENTS = folder / "chaos.jsonl"
        failover.LOG = folder / "failover.jsonl"
        runbook.LOG = folder / "runbook.jsonl"
        runbook.CHAOS_LOG = chaos.EVENTS
        health = folder / "health.jsonl"
        for path in folder.glob("*.jsonl"):
            if path.exists():
                raise RuntimeError(f"Preserve existing run: {path}")
        # Each run begins with warm standby; wait until serving observes it.
        pathlib.Path("state/region-b/pool_state").write_text("warm")
        pathlib.Path("edge/active_region").write_text("a")
        a, b = service("a"), service("b")
        edge = launch(["-m", "uvicorn", "edge.proxy:app", "--host", "127.0.0.1",
                       "--port", "8080", "--log-level", "warning"], "bonus-edge")
        try:
            time.sleep(2)
            if any(p.poll() is not None for p in [a, b, edge]):
                raise RuntimeError("service startup failed")
            wait_alive("a")
            wait_alive("b")
            from state import snapshot
            snapshot.put("a", "fs")
            load = launch(["loadgen/traffic.py", "--duration", "52", "--rps", "2",
                           "--out", str(folder / "traffic.jsonl")], f"bonus-load-{index}")
            checker = launch(["dr/health_checker.py", "--duration", "52", "--interval", "5",
                              "--threshold", "3", "--out", str(health)], f"bonus-health-{index}")
            time.sleep(delay)
            killed = chaos.kill("a", mode, "bare", False, True)
            deadline = time.time() + 35
            while time.time() < deadline:
                events = [json.loads(l) for l in health.read_text().splitlines()] if health.exists() else []
                if any(e.get("region") == "a" and e.get("to") == "UNHEALTHY"
                       and e["ts"] > killed["ts"] for e in events):
                    break
                time.sleep(.25)
            else:
                raise RuntimeError("no alert")
            result = runbook.run("a", "b", "fs", True)
            if not result["ok"]:
                raise RuntimeError(result)
            load.wait(timeout=60)
            checker.wait(timeout=15)
            result = measure(folder / "traffic.jsonl", chaos.EVENTS, health, failover.LOG, 300)
            result.update(run=index, kill_delay_s=delay, random_seed=23)
            (folder / "measure.json").write_text(json.dumps(result, indent=2))
            results.append(result)
            print("BONUS", index, result["rto_measured_s"], mode, flush=True)
        finally:
            if a.poll() is None:
                signal_process(a.pid, 1002)
            for process in [a, b, edge]:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=10)
            time.sleep(1)
    results = [json.loads((base / f"run-{i}" / "measure.json").read_text()) for i in range(1, 6)]
    values = [r["rto_measured_s"] for r in results]
    (base / "summary.json").write_text(json.dumps(dict(
        runs=results, mean_rto_s=statistics.mean(values),
        sample_stddev_s=statistics.stdev(values), random_seed=23), indent=2))


if __name__ == "__main__":
    main()
