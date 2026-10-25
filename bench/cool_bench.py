"""Reproducible benchmark of the NadiSaathi OpenCV 5 workload on one host.

Same frames, same pipeline, same config on every host:
  A  COOL AMI (OpenCV 5 + KleidiCV) on Graviton4 (c8g)
  B  stock opencv-python-headless 5.0.0.93 wheel on the same c8g
  C  stock wheel on x86 (c7i)

    PYTHONPATH=backend/src python bench/cool_bench.py --label A-cool-c8g --out bench/results/A.json

What it records:
  * proof of the build: cv2.__version__, cv2.__file__, KleidiCV lines from
    cv2.getBuildInformation(), CPU model, and EC2 instance-id / type / AMI id
    from IMDSv2 (when on EC2)
  * per-stage latency (quality, registration, E1/E2/E3, DIS flow, YuNet
    redaction, overlay) p50/p95 over repeated runs of the full measurement
  * thread scaling of one camera (cv2.setNumThreads 1..N)
  * throughput with one single-threaded worker process per vCPU
    (frames/s and cameras per instance at a 10 s cadence)
  * micro-benchmarks of the heavy OpenCV 5 pieces: ALIKED+LightGlue
    registration, DIS optical flow, YuNet, GrabCut
  * an output-equivalence hash: stage readings rounded to 1 mm, so hosts can
    be compared for identical results
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from jalrekha.vision import synth  # noqa: E402
from jalrekha.vision.pipeline import MeasureOptions, measure  # noqa: E402

SEEDS = list(range(100, 112))
FRACS = [0.25, 0.5, 0.8]
CONDITIONS = {"clean": {}, "rain": {"rain": 0.6}, "night": {"night": 0.75}, "shake": {"shake_px": 10}}


def _imds(path: str) -> str | None:
    try:
        req = urllib.request.Request("http://169.254.169.254/latest/api/token", method="PUT",
                                     headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"})
        token = urllib.request.urlopen(req, timeout=0.5).read().decode()
        req = urllib.request.Request(f"http://169.254.169.254/latest/meta-data/{path}", headers={"X-aws-ec2-metadata-token": token})
        return urllib.request.urlopen(req, timeout=0.5).read().decode()
    except Exception:
        return None


def host_info() -> dict:
    build = cv2.getBuildInformation()
    kleidi = [ln.strip() for ln in build.splitlines() if "kleidi" in ln.lower()]
    cpu = platform.processor() or ""
    try:
        lscpu = subprocess.run(["lscpu"], capture_output=True, text=True, timeout=5).stdout
        for ln in lscpu.splitlines():
            if ln.lower().startswith("model name"):
                cpu = ln.split(":", 1)[1].strip()
    except Exception:
        pass
    return {
        "opencv_version": cv2.__version__, "cv2_file": cv2.__file__, "kleidicv_build_lines": kleidi,
        "kleidicv_present": bool(kleidi), "build_info_sha256": hashlib.sha256(build.encode()).hexdigest(),
        "machine": platform.machine(), "cpu_model": cpu, "cpu_count": os.cpu_count(), "python": sys.version.split()[0],
        "numpy": np.__version__, "ec2_instance_id": _imds("instance-id"), "ec2_instance_type": _imds("instance-type"),
        "ec2_ami_id": _imds("ami-id"), "ec2_region": (_imds("placement/region") or None),
        "cv_num_threads_default": cv2.getNumThreads(), "use_optimized": cv2.useOptimized(),
    }


def workload() -> list[tuple[str, list[np.ndarray], np.ndarray, object, float]]:
    items = []
    for seed in SEEDS:
        site = synth.make_site(seed)
        calib = site.calibration(click_err_px=1.0)
        ref = synth.reference_frame(site)
        for cname, deg in CONDITIONS.items():
            for frac in FRACS:
                stage = round(site.gauge_len_m * frac, 3)
                frames = synth.render_burst(site, stage, n=5, deg=synth.Degradation(**deg), rng=np.random.default_rng(seed * 100 + int(frac * 100)))
                items.append((f"{seed}-{cname}-{frac}", frames, ref, calib, stage))
    return items


def run_once(items, opts: MeasureOptions) -> tuple[list[dict], list[float]]:
    per_stage, outs = [], []
    for key, frames, ref, calib, truth in items:
        m = measure(frames, calib, ref, opts)
        per_stage.append(m.timings_ms)
        outs.append(None if m.reading.stage_m is None else round(m.reading.stage_m, 3))
    return per_stage, outs


def pct(vals: list[float], q: float) -> float:
    return float(np.percentile(np.array(vals), q)) if vals else float("nan")


def _worker(args):
    seed, n = args
    cv2.setNumThreads(1)
    site = synth.make_site(seed)
    calib = site.calibration(click_err_px=1.0)
    ref = synth.reference_frame(site)
    frames = synth.render_burst(site, site.gauge_len_m * 0.5, n=5)
    opts = MeasureOptions(allow_heavy_registration=False)
    measure(frames, calib, ref, opts)  # warm-up
    t0 = time.perf_counter()
    for _ in range(n):
        measure(frames, calib, ref, opts)
    return n, time.perf_counter() - t0


def throughput(procs: int, per_proc: int) -> dict:
    t0 = time.perf_counter()
    import multiprocessing as mp

    with ProcessPoolExecutor(max_workers=procs, mp_context=mp.get_context("spawn")) as ex:
        res = list(ex.map(_worker, [(100 + i % 12, per_proc) for i in range(procs)]))
    wall = time.perf_counter() - t0
    bursts = sum(r[0] for r in res)
    busy = max(r[1] for r in res)
    return {"processes": procs, "bursts": bursts, "wall_s": round(wall, 2),
            "bursts_per_s": round(bursts / busy, 2), "frames_per_s": round(bursts * 5 / busy, 1),
            "cameras_at_10s_cadence": int(bursts / busy * 10)}


def micro() -> dict:
    out: dict = {}
    site = synth.make_site(105)
    ref = synth.reference_frame(site)
    cur = synth.render_burst(site, site.gauge_len_m * 0.6, n=2, deg=synth.Degradation(shake_px=20))
    from jalrekha.vision import register, privacy, relief

    def timeit(fn, n=5):
        fn()
        ts = []
        for _ in range(n):
            t = time.perf_counter()
            fn()
            ts.append((time.perf_counter() - t) * 1000)
        return {"ms_p50": round(statistics.median(ts), 2), "ms_min": round(min(ts), 2), "n": n}

    out["orb_registration"] = timeit(lambda: register.register(cur[-1], ref, allow_heavy=False))
    if register.aliked_available():
        out["aliked_lightglue_registration"] = timeit(lambda: register.register(cur[-1], ref, force_heavy=True), n=3)
    else:
        out["aliked_lightglue_registration"] = "models not present (run python -m jalrekha.vision.models)"
    dis = cv2.DISOpticalFlow.create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    g0, g1 = (cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in cur)
    out["dis_flow_960x540"] = timeit(lambda: dis.calc(g0, g1, None))
    out["yunet_redact_960x540"] = timeit(lambda: privacy.redact(cur[-1]))
    out["grabcut_photo_check"] = timeit(lambda: relief.water_mask(cur[-1]), n=3)
    big = cv2.resize(cur[-1], (1920, 1080))
    out["resize_gaussian_canny_1080p"] = timeit(lambda: cv2.Canny(cv2.GaussianBlur(cv2.resize(big, (960, 540)), (5, 5), 0), 50, 150), n=20)
    return out


def price_per_hour(instance_type: str | None, override: float | None) -> dict:
    if override is not None:
        return {"usd_per_hour": override, "source": "command-line --price"}
    if not instance_type:
        return {"usd_per_hour": None, "source": "unknown (not on EC2; pass --price)"}
    try:
        import boto3

        pr = boto3.client("pricing", region_name="us-east-1")
        resp = pr.get_products(ServiceCode="AmazonEC2", Filters=[
            {"Type": "TERM_MATCH", "Field": "instanceType", "Value": instance_type},
            {"Type": "TERM_MATCH", "Field": "location", "Value": "US East (N. Virginia)"},
            {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": "Linux"},
            {"Type": "TERM_MATCH", "Field": "tenancy", "Value": "Shared"},
            {"Type": "TERM_MATCH", "Field": "preInstalledSw", "Value": "NA"},
            {"Type": "TERM_MATCH", "Field": "capacitystatus", "Value": "Used"}], MaxResults=5)
        for raw in resp["PriceList"]:
            item = json.loads(raw)
            for term in item["terms"]["OnDemand"].values():
                for dim in term["priceDimensions"].values():
                    usd = float(dim["pricePerUnit"]["USD"])
                    if usd > 0:
                        return {"usd_per_hour": usd, "source": f"AWS Price List API, on-demand Linux us-east-1, {datetime.now(timezone.utc).date()}"}
    except Exception as exc:
        return {"usd_per_hour": None, "source": f"price lookup failed: {type(exc).__name__}"}
    return {"usd_per_hour": None, "source": "not found"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--threads", default="1,2,4,8")
    ap.add_argument("--per-proc", type=int, default=20)
    ap.add_argument("--price", type=float, default=None, help="USD/hour override (instance + any AMI software fee)")
    ap.add_argument("--software-fee", type=float, default=0.0, help="Marketplace software USD/hour added to the instance price")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--child-threads", type=int, default=None, help=argparse.SUPPRESS)
    ap.add_argument("--child-items", type=int, default=12, help=argparse.SUPPRESS)
    a = ap.parse_args()

    if a.child_threads is not None:
        cv2.setNumThreads(a.child_threads)
        items = workload()[: a.child_items]
        opts = MeasureOptions(allow_heavy_registration=False)
        run_once(items[:2], opts)
        t0 = time.perf_counter()
        run_once(items, opts)
        print(json.dumps({"threads": a.child_threads, "ms_per_burst": (time.perf_counter() - t0) / len(items) * 1000}))
        return 0

    info = host_info()
    items = workload()
    if a.quick:
        items = items[:12]
    opts = MeasureOptions(allow_heavy_registration=False)
    print(f"[{a.label}] OpenCV {info['opencv_version']} KleidiCV={info['kleidicv_present']} items={len(items)}", flush=True)

    run_once(items[:3], opts)  # warm-up
    cv2.setNumThreads(0 if info["cpu_count"] is None else info["cpu_count"])
    totals, stage_ms, outputs = [], {}, None
    for r in range(a.repeats):
        t0 = time.perf_counter()
        per, outs = run_once(items, opts)
        totals.append((time.perf_counter() - t0) / len(items) * 1000)
        for d in per:
            for k, v in d.items():
                stage_ms.setdefault(k, []).append(v)
        outputs = outs if outputs is None else outputs
        print(f"  repeat {r + 1}: {totals[-1]:.1f} ms/burst", flush=True)
    scaling = []
    n_scale = max(12, len(items) // 4)
    for t in [int(x) for x in a.threads.split(",") if int(x) <= (info["cpu_count"] or 1)]:
        # Fresh interpreter per thread count: clean measurement, no thread-pool state carried over.
        proc = subprocess.run([sys.executable, __file__, "--label", "child", "--out", "-", "--child-threads", str(t),
                               "--child-items", str(n_scale)], capture_output=True, text=True, timeout=900)
        try:
            ms = json.loads(proc.stdout.strip().splitlines()[-1])["ms_per_burst"]
        except Exception:
            print(proc.stderr[-500:], flush=True)
            continue
        scaling.append({"threads": t, "ms_per_burst": round(ms, 2)})
        print(f"  threads={t}: {ms:.1f} ms/burst", flush=True)
    cv2.setNumThreads(info["cpu_count"] or 1)
    tp = throughput(info["cpu_count"] or 1, 4 if a.quick else a.per_proc)
    print(f"  throughput: {tp}", flush=True)
    mic = micro()
    price = price_per_hour(info["ec2_instance_type"], a.price)
    usd_h = None if price["usd_per_hour"] is None else price["usd_per_hour"] + a.software_fee
    per_million = None if usd_h is None else round(usd_h / (tp["frames_per_s"] * 3600) * 1e6, 4)
    out_hash = hashlib.sha256(json.dumps(outputs).encode()).hexdigest()
    result = {
        "schema": "nadisaathi-cool-bench-v1", "label": a.label, "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": "bench/cool_bench.py", "host": info,
        "workload": {"bursts": len(items), "frames_per_burst": 5, "resolution": [synth.W, synth.H], "seeds": SEEDS,
                     "conditions": list(CONDITIONS), "stage_fracs": FRACS, "heavy_registration": False,
                     "label": "SYNTHETIC staff-gauge bursts (identical on every host)"},
        "latency": {"ms_per_burst_mean_of_repeats": round(statistics.mean(totals), 2),
                    "ms_per_burst_stdev": round(statistics.pstdev(totals), 2), "repeats": totals,
                    "per_stage_ms": {k: {"p50": round(pct(v, 50), 3), "p95": round(pct(v, 95), 3)} for k, v in sorted(stage_ms.items())}},
        "thread_scaling": scaling, "throughput": tp, "micro_ms": mic,
        "cost": {**price, "software_fee_usd_per_hour": a.software_fee, "usd_per_hour_total": usd_h,
                 "usd_per_million_frames": per_million,
                 "note": "frames = 5-frame bursts x 5; cost uses the multi-process throughput"},
        "equivalence": {"outputs_mm_sha256": out_hash, "stage_m": outputs},
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(result, indent=1))
    print(f"wrote {a.out}: {result['latency']['ms_per_burst_mean_of_repeats']} ms/burst, {tp['frames_per_s']} fps, ${per_million}/1M frames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
