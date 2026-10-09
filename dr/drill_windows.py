"""Run genuine local drills on Windows; adapt only Unix process signals.

Existing chaos, serving, snapshot, loadgen and measurement code are unchanged.
"""
import ctypes
import importlib.util
import json
import os
import pathlib
import random
import statistics
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
PY = sys.executable
kernel = ctypes.WinDLL("kernel32", use_last_error=True)
kernel.OpenProcess.restype = ctypes.c_void_p
kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
kernel.CloseHandle.argtypes = [ctypes.c_void_p]
kernel.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
nt = ctypes.WinDLL("ntdll")
nt.NtSuspendProcess.argtypes = [ctypes.c_void_p]
nt.NtResumeProcess.argtypes = [ctypes.c_void_p]


def signal_process(pid, action):
    handle = kernel.OpenProcess(0x0801, False, pid)
    if not handle:
        raise OSError(ctypes.get_last_error())
    try:
        if action == 1001:
            code = nt.NtSuspendProcess(handle)
        elif action == 1002:
            code = nt.NtResumeProcess(handle)
        elif action == 1003:
            code = 0 if kernel.TerminateProcess(handle, 1) else -1
        else:
            raise ValueError(action)
        if code:
            raise OSError(f"Windows process action failed: {code}")
    finally:
        kernel.CloseHandle(handle)


spec = importlib.util.spec_from_file_location("lab_chaos", ROOT / "chaos/kill_region.py")
chaos = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chaos)
# Local module proxies avoid changing the global os/signal modules.
import types
chaos.os = types.SimpleNamespace(kill=signal_process)
chaos.signal = types.SimpleNamespace(SIGSTOP=1001, SIGCONT=1002, SIGKILL=1003)
chaos.pid_of = lambda r: int(pathlib.Path(f"run/region-{r}.pid").read_text().strip())


def launch(args, name, env=None):
    log = open(f"run/{name}.log", "w", encoding="utf-8")
    process = subprocess.Popen([PY, *args], env=env, stdout=log, stderr=subprocess.STDOUT)
    log.close()
    return process


def service(region):
    env = dict(os.environ, REGION=region, STATE_DIR=f"state/region-{region}", WARMUP_SECONDS="6")
    process = launch(["-m", "uvicorn", "serving.app:app", "--host", "127.0.0.1",
                      "--port", "8001" if region == "a" else "8002", "--log-level", "warning"],
                     f"region-{region}", env)
    pathlib.Path(f"run/region-{region}.pid").write_text(str(process.pid))
    return process


def wait_alive(region):
    for _ in range(40):
        if chaos.is_alive(region):
            return
        time.sleep(.25)
    raise RuntimeError(f"region {region} not alive")


def main():
    from tools.measure_rto import measure
    from dr import runbook
    pathlib.Path("run").mkdir(exist_ok=True)
    # Preserve earlier attempts rather than mixing them into the final evidence.
    archive = pathlib.Path("reports/previous-attempts") / str(int(time.time()))
    archive.mkdir(parents=True)
    for path in [pathlib.Path("chaos/chaos-events.jsonl"),
                 *pathlib.Path("reports").glob("*.jsonl")]:
        if path.exists():
            path.rename(archive / path.name)
    services = []
    workers = []
    try:
        for name in ("region-a", "region-b", "_replica"):
            source = (ROOT / "state" / name).resolve()
            if source.parent != (ROOT / "state").resolve():
                raise RuntimeError("state archive escaped workspace")
            if source.exists():
                source.rename(archive / f"state-{name}")
        for region, docs in [("a", "200"), ("b", "0")]:
            args = [PY, "state/seed_vectors.py", "--region", region, "--docs", docs]
            if region == "b":
                args += ["--weights-mb", "0"]
            subprocess.run(args, check=True)
        pathlib.Path("edge/active_region").write_text("a")
        services = [service("a"), service("b")]
        time.sleep(2)
        if any(p.poll() is not None for p in services):
            raise RuntimeError("Port occupied: stop old region processes before running")
        env = dict(os.environ, EDGE_TTL_SECONDS="5")
        edge = launch(["-m", "uvicorn", "edge.proxy:app", "--host", "127.0.0.1",
                       "--port", "8080", "--log-level", "warning"], "edge", env)
        services.append(edge)
        time.sleep(1)
        if edge.poll() is not None:
            raise RuntimeError("Edge port occupied")
        wait_alive("a")
        wait_alive("b")
        import httpx
        baseline = {r: httpx.get(f"{chaos.URL[r]}/v1/state").json() for r in "ab"}
        pathlib.Path("reports/setup-state.json").write_text(json.dumps(baseline, indent=2))
        time.sleep(2)
        traffic = launch(["loadgen/traffic.py", "--duration", "40", "--rps", "2",
                          "--out", "reports/drill-1-nodr.jsonl"], "baseline")
        workers.append(traffic)
        time.sleep(8)
        chaos.kill("a", "netblock", "bare", False, True)
        traffic.wait(timeout=50)
        result = measure("reports/drill-1-nodr.jsonl", "chaos/chaos-events.jsonl",
                         "reports/health-events.jsonl", "reports/failover-events.jsonl", 300)
        pathlib.Path("reports/measure-drill-1.json").write_text(json.dumps(result, indent=2))
        print("BASELINE", result, flush=True)
        chaos.restore("a", "bare")
        ingest = launch(["state/ingest.py", "--rate", "0.5", "--duration", "150"], "ingest")
        replica = launch(["state/replicate.py", "--every", "30", "--duration", "150",
                          "--backend", "fs"], "replication")
        workers.extend([ingest, replica])
        time.sleep(5)
        traffic = launch(["loadgen/traffic.py", "--duration", "100", "--rps", "2",
                          "--out", "reports/drill-2-withdr.jsonl"], "withdr")
        checker = launch(["dr/health_checker.py", "--interval", "5", "--threshold", "3",
                          "--duration", "100"], "health")
        workers.extend([traffic, checker])
        time.sleep(12)
        kill = chaos.kill("a", "netblock", "bare", False, True)
        deadline = time.time() + 50
        while time.time() < deadline:
            path = pathlib.Path("reports/health-events.jsonl")
            events = [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []
            if any(e.get("region") == "a" and e.get("to") == "UNHEALTHY"
                   and e["ts"] > kill["ts"] for e in events):
                break
            time.sleep(.25)
        else:
            raise RuntimeError("health checker did not detect outage")
        result = runbook.run("a", "b", "fs", True)
        if not result["ok"]:
            raise RuntimeError(result)
        traffic.wait(timeout=110)
        checker.wait(timeout=20)
        ingest.wait(timeout=70)
        replica.wait(timeout=40)
        result = measure("reports/drill-2-withdr.jsonl", "chaos/chaos-events.jsonl",
                         "reports/health-events.jsonl", "reports/failover-events.jsonl", 300)
        pathlib.Path("reports/measure-drill-2.json").write_text(json.dumps(result, indent=2))
        print("WITH_DR", result, flush=True)
        chaos.restore("a", "bare")
    finally:
        try:
            signal_process(services[0].pid, 1002)
        except (OSError, IndexError):
            pass
        for process in workers + services:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
