"""BƯỚC 3c — SINH VIÊN VIẾT. Tự động hoá runbook §4 "Runbook: Region Chính Down".

7 bước trên slide, mỗi bước 1 dòng log có ts. Log này CHÍNH LÀ timeline của postmortem.
  1 xac_nhan_outage          — probe cả 2 region, đừng tin 1 lần fail (dùng nhiều lần
                              hoặc gọi health_checker.probe nếu đã viết xong 3a)
  2 thong_bao_incident       — ts của dòng này là mốc "operator biết tin", LUÔN LUÔN
                              SAU t_outage trong chaos-events (không thể trùng — operator
                              không thể biết ngay giây outage xảy ra). Ghi cả 2 ts vào
                              log để postmortem tính được "độ trễ thông báo".
  3 scale_gpu_pool           — gọi HÀM `failover.failover(...)` MỘT LẦN DUY NHẤT. Hàm
                              đó tự làm đủ 5 bước con (verify/restore/scale/wait/cutover)
                              và tự ghi log riêng vào reports/failover-events.jsonl.
  4 verify_state_replica     — KHÔNG gọi lại failover — chỉ ĐỌC kết quả (vector count +
                              weights ở region phụ) từ dict mà bước 3 trả về, để log vào
                              runbook-run.jsonl cho postmortem đọc 1 chỗ duy nhất.
  5 dns_cutover              — cũng chỉ đọc lại: kết quả cutover có ok hay không.
  6 verify_golden_signals    — 10 request thật vào region phụ: p95 latency + error rate
  7 post_incident            — elapsed_s + lệnh đo RTO

BÁN TỰ ĐỘNG, KHÔNG FULL-AUTO (§4: "failover đầu tiên nên là bán tự động — alert +
1-click confirm — tránh flapping gây failover 2 chiều liên tục"). Mặc định phải hỏi
người vận hành confirm; --auto chỉ dùng trong CI/khi chấm điểm.

Chạy:  python dr/runbook.py --primary a --target b --backend fs
"""
import argparse
import json
import pathlib
import sys
import time

import httpx

sys.path.insert(0, ".")
from dr import failover as fo  # noqa: E402

LOG = pathlib.Path("reports/runbook-run.jsonl")
CHAOS_LOG = pathlib.Path("chaos/chaos-events.jsonl")
URL = {"a": "http://127.0.0.1:8001", "b": "http://127.0.0.1:8002"}


def step(n, name, **kw):
    """TODO: ghi 1 dòng {ts, iso, step, name, ...} vào LOG."""
    rec = dict(ts=time.time(), iso=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               step=n, name=name, **kw)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as log:
        log.write(json.dumps(rec) + "\n")
    print(json.dumps(rec), flush=True)
    return rec


def confirm(auto: bool, msg: str) -> bool:
    """TODO: auto=True -> True; ngược lại hỏi y/N. Đừng bỏ hàm này đi."""
    return auto or input(msg + " [y/N] ").strip().lower() == "y"


def run(primary: str, target: str, backend: str, auto: bool) -> dict:
    """TODO: 7 bước ở trên."""
    from dr.health_checker import probe
    if primary == target:
        return dict(ok=False, reason="primary_equals_target")
    for _ in range(3):
        ready, reason = probe(primary, 2)
        if ready:
            return dict(ok=False, reason="primary_ready")
        try:
            alive = httpx.get(f"{URL[target]}/healthz", timeout=2).status_code == 200
        except httpx.HTTPError:
            alive = False
        if not alive:
            return dict(ok=False, reason="target_not_alive")
        time.sleep(1)
    step(1, "xac_nhan_outage", primary=primary, target=target, consecutive_fails=3)
    if not confirm(auto, f"Confirm failover {primary} -> {target}?"):
        return dict(ok=False, reason="operator_declined")
    kills = [json.loads(line) for line in CHAOS_LOG.read_text().splitlines()
             if line.strip()]
    outage = next(e["ts"] for e in reversed(kills)
                  if e.get("action") == "kill" and e.get("region") == primary)
    started = time.time()
    step(2, "thong_bao_incident", t_outage=outage, notification_delay_s=started-outage, auto=auto)
    result = fo.failover(target, backend, wait=60)
    step(3, "scale_gpu_pool", result=result)
    if not result.get("ok"):
        return result
    step(4, "verify_state_replica", state=result["state"])
    step(5, "dns_cutover", ok=result["ok"], target=target)
    latencies, errors = [], 0
    for _ in range(10):
        tick = time.monotonic()
        try:
            response = httpx.get(f"{URL[target]}/v1/infer", timeout=3)
            errors += int(response.status_code != 200 or response.json().get("region") != target)
        except (httpx.HTTPError, ValueError):
            errors += 1
        latencies.append((time.monotonic()-tick)*1000)
    step(6, "verify_golden_signals", requests=10, p95_ms=round(sorted(latencies)[9], 2),
         error_rate=errors/10, scope="target_direct")
    step(7, "post_incident", elapsed_s=time.time()-outage, operator_elapsed_s=time.time()-started,
         measure_command="python tools/measure_rto.py --loadgen reports/drill-2-withdr.jsonl")
    return dict(**result, golden_errors=errors)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--primary", default="a")
    p.add_argument("--target", default="b")
    p.add_argument("--backend", default="fs", choices=["fs", "minio"])
    p.add_argument("--auto", action="store_true")
    a = p.parse_args()
    print(json.dumps(run(a.primary, a.target, a.backend, a.auto), indent=2))
