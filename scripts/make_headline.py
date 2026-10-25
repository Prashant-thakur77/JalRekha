"""Single source of truth for every number in the docs.

Reads eval/results/*.json and bench/results/*.json, writes
eval/results/headline.json (also served at GET /api/evidence), then renders
docs/templates/*.tpl.md into README.md, docs/REPORT.md, docs/DEVPOST.md,
docs/VIDEO_SCRIPT.md and docs/COOL.md, replacing {{key}} with the value.

    python scripts/make_headline.py           # regenerate
    python scripts/make_headline.py --check   # fail if any rendered doc is stale
                                              # or a template uses an unknown key
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "eval" / "results"
BENCH = ROOT / "bench" / "results"
TEMPLATES = ROOT / "docs" / "templates"
TARGETS = {
    "README.tpl.md": ROOT / "README.md",
    "REPORT.tpl.md": ROOT / "docs" / "REPORT.md",
    "DEVPOST.tpl.md": ROOT / "docs" / "DEVPOST.md",
    "VIDEO_SCRIPT.tpl.md": ROOT / "docs" / "VIDEO_SCRIPT.md",
    "COOL.tpl.md": ROOT / "docs" / "COOL.md",
}


def _load(p: Path) -> dict | None:
    return json.loads(p.read_text()) if p.exists() else None


def pct(x: float | None, nd: int = 0) -> str:
    return "n/a" if x is None else f"{x * 100:.{nd}f}%"


def num(x, nd: int = 1) -> str:
    if x is None:
        return "n/a"
    return f"{x:,.{nd}f}" if isinstance(x, float) else f"{x:,}"


def build() -> tuple[dict[str, str], list[dict], list[str]]:
    k: dict[str, str] = {}
    items: list[dict] = []
    sources: list[str] = []

    def item(key, label, value, unit, baseline=None, dataset="", file=""):
        items.append({"key": key, "label": label, "value": value, "unit": unit, "baseline": baseline, "dataset": dataset, "file": file})

    # ---- synthetic held-out stage accuracy
    s = _load(RES / "stage_synth_test.json")
    if s:
        sources.append("eval/results/stage_synth_test.json")
        sm = s["summary"]
        for m, key in [("full", "synth_full"), ("B0r_base_repo_border_fixed", "synth_b0r"), ("B1_naive_max_edge", "synth_b1"),
                       ("E1_only", "synth_e1"), ("E2_only", "synth_e2"), ("E3_only", "synth_e3"), ("full_no_registration", "synth_noreg")]:
            o = sm[m]["overall"]
            k[f"{key}_mae_cm"] = num(o["mae_cm"])
            k[f"{key}_within5"] = pct(o.get("within_5cm"))
        k["synth_b0_coverage"] = pct(sm["B0_base_repo_firewall"]["overall"]["coverage"], 1)
        k["synth_full_ci"] = f"{sm['full']['overall']['mae_ci95_cm'][0]:.1f}–{sm['full']['overall']['mae_ci95_cm'][1]:.1f}"
        k["synth_full_median_cm"] = num(sm["full"]["overall"]["median_abs_cm"])
        k["synth_frames"] = num(sm["full"]["overall"]["n"])
        k["synth_full_ms"] = num(sm["full"]["overall"]["ms_p50"])
        bc = sm["full"]["by_condition"]
        k["synth_full_glare_mae_cm"] = num(bc["glare"]["mae_cm"])
        k["synth_full_clean_mae_cm"] = num(bc["clean"]["mae_cm"])
        k["synth_full_night_mae_cm"] = num(bc["night"]["mae_cm"])
        k["synth_e2_still_mae_cm"] = num(sm["E2_only"]["by_condition"]["still_water"]["mae_cm"])
        k["synth_e2_still_cov"] = pct(sm["E2_only"]["by_condition"]["still_water"]["coverage"])
        item("synth_full_mae", "Stage error, held-out synthetic scenes (9 conditions)", sm["full"]["overall"]["mae_cm"], "cm",
             {"name": "original PIL heuristic (border-fixed)", "value": sm["B0r_base_repo_border_fixed"]["overall"]["mae_cm"]},
             "SYNTHETIC test seeds 100-129", "eval/results/stage_synth_test.json")

    # ---- real cameras, physical calibration
    r = _load(RES / "stage_real_physical.json")
    if r:
        sources.append("eval/results/stage_real_physical.json")
        p = r["pooled_in_range"]
        k["real_n"] = num(p["full"]["n"])
        k["real_full_mae_cm"] = num(p["full"]["mae_cm"])
        k["real_full_ci"] = f"{p['full']['mae_ci95_cm'][0]:.1f}–{p['full']['mae_ci95_cm'][1]:.1f}"
        k["real_full_median_cm"] = num(p["full"]["median_abs_cm"])
        k["real_full_within10"] = pct(p["full"]["within_10cm"])
        k["real_noreg_mae_cm"] = num(p["full_no_registration"]["mae_cm"])
        k["real_noreg_within10"] = pct(p["full_no_registration"]["within_10cm"])
        k["real_e1_mae_cm"] = num(p["E1_only"]["mae_cm"])
        k["real_b0_mae_cm"] = num(p["B0_base_repo_firewall"]["mae_cm"])
        k["real_b0_coverage"] = pct(p["B0_base_repo_firewall"]["coverage"])
        k["real_b1_mae_cm"] = num(p["B1_naive_max_edge"]["mae_cm"])
        # Same-frames comparison with B0 (it answers only some frames).
        pairs = []
        for site in r["sites"].values():
            if not site.get("in_scope"):
                continue
            lo, hi = site["gauge_span_m"]
            for f in site["frames"]:
                if lo - 0.05 <= f["truth_m"] <= hi + 0.05 and f.get("B0_base_repo_firewall") is not None and f.get("full") is not None:
                    pairs.append((abs(f["full"] - f["truth_m"]), abs(f["B0_base_repo_firewall"] - f["truth_m"])))
        if pairs:
            k["real_b0_subset_n"] = num(len(pairs))
            k["real_full_on_b0_subset_cm"] = num(sum(a for a, _ in pairs) / len(pairs) * 100)
            k["real_b0_on_subset_cm"] = num(sum(b for _, b in pairs) / len(pairs) * 100)
        sites = {sid: v for sid, v in r["sites"].items() if v.get("in_scope")}
        for sid, v in sites.items():
            short = "hancock" if "Hancock" in sid else "moravia"
            k[f"real_{short}_mae_cm"] = num(v["methods"]["full"]["mae_cm"])
            k[f"real_{short}_median_cm"] = num(v["methods"]["full"]["median_abs_cm"])
            k[f"real_{short}_within10"] = pct(v["methods"]["full"]["within_10cm"])
            k[f"real_{short}_frames"] = num(v["methods"]["full"]["in_range_frames"])
            k[f"real_{short}_noreg_within10"] = pct(v["methods"]["full_no_registration"]["within_10cm"])
            k[f"real_{short}_out"] = num(v["methods"]["full"]["out_of_range_frames"])
            k[f"real_{short}_out_ok"] = num(v["methods"]["full"]["out_of_range_clamped_ok"])
            k[f"real_{short}_b0_mae_cm"] = num(v["methods"]["B0_base_repo_firewall"].get("mae_cm"))
        item("real_full_mae", "Stage error on real USGS staff-gauge cameras (physical calibration, nothing fitted)", p["full"]["mae_cm"], "cm",
             {"name": "original PIL heuristic", "value": p["B0_base_repo_firewall"]["mae_cm"]}, f"REAL, {p['full']['n']} in-range frames, 2 sites",
             "eval/results/stage_real_physical.json")
    if r:
        p = r["pooled_in_range"]
        k["real_e3_mae_cm"] = num(p["E3_only"]["mae_cm"])
        k["real_e3_within10"] = pct(p["E3_only"]["within_10cm"])
    lt2 = _load(RES / "leadtime_v2.json")
    if lt2:
        sources.append("eval/results/leadtime_v2.json")
        for cond, key in [("nws_action/gauge", "lt2_nws"), ("p95/gauge", "lt2_p95"), ("p95/camera_noise", "lt2_p95cam"), ("nws_action/camera_noise", "lt2_nwscam")]:
            t = lt2["pooled"][cond]["test"]
            k[f"{key}_gain_median_h"] = num(t["gain_median_min"] / 60, 1)
            k[f"{key}_gain_median_min"] = num(t["gain_median_min"], 0)
            k[f"{key}_gain_mean_h"] = num(t["gain_mean_min"] / 60, 1)
            k[f"{key}_det_down"] = pct(t["detection_rate_downstream_only"])
            k[f"{key}_det_comb"] = pct(t["detection_rate_combined"])
            k[f"{key}_fa_up"] = num(t["false_alerts_upstream_per_30d"], 2)
        k["lt2_z"] = str(lt2["meta"].get("z", lt2["meta"].get("rate_significance_z", 1.5)))
    gd = _load(RES / "guard_eval.json")
    if gd:
        sources.append("eval/results/guard_eval.json")
        bad = sum(v["n"] for kk, v in gd["by_kind"].items() if kk != "confirm")
        caught = sum(v["ok"] for kk, v in gd["by_kind"].items() if kk != "confirm")
        k["guard_cases"] = num(sum(v["n"] for v in gd["by_kind"].values()))  # counted, not taken from the label
        k["guard_bad"] = num(bad)
        k["guard_caught"] = num(caught)
        k["guard_catch_rate"] = pct(gd["catch_rate"])
        k["guard_confirm_ok"] = f"{gd['by_kind']['confirm']['ok']}/{gd['by_kind']['confirm']['n']}"
        k["guard_inject_ok"] = f"{gd['by_kind']['inject']['ok']}/{gd['by_kind']['inject']['n']}"
        nr = gd.get("negative_result")
        if nr:
            k["glare_wrong"] = num(nr["confidently_wrong"])
            k["glare_bursts"] = num(nr["bursts"])
            k["glare_wrong_pct"] = pct(nr["rate"])
            k["glare_err_range"] = f"{abs(nr['error_m_range'][1]):.1f}–{abs(nr['error_m_range'][0]):.1f} m" if nr["error_m_range"] else "n/a"
        item("guard_catch", "Bad VLM replies caught (contradicting, injected EN/HI/NE, malformed)", gd["catch_rate"], "fraction",
             {"name": "honest confirmations accepted", "value": gd["by_kind"]["confirm"]["ok"] / gd["by_kind"]["confirm"]["n"]},
             gd["meta"]["label"], "eval/results/guard_eval.json")
    rp = _load(RES / "real_replay.json")
    if rp:
        sources.append("eval/results/real_replay.json")
        k["rr_frames"] = num(rp["frames"])
        k["rr_used"] = num(rp["used_readings"])
        k["rr_used_mae_cm"] = num(rp["used_mae_cm"])
        k["rr_used_median_cm"] = num(rp["used_median_cm"])
        k["rr_held_pct"] = pct(rp["held_fraction"])
        k["rr_siren_first"] = "yes" if rp["siren_on_first_danger_frame"] else "no"
        k["rr_quiet_alerts"] = num(rp["alert_drafts_on_quiet_frames"])
        k["rr_all_clear"] = "yes" if rp["all_clear_proposed_at"] else "no"
        item("real_replay_mae", "Agent on a real USGS camera: error of the readings it used", rp["used_mae_cm"], "cm",
             None, rp["meta"]["label"], "eval/results/real_replay.json")
    vb = _load(RES / "vlm_baseline.json")
    if vb:
        sources.append("eval/results/vlm_baseline.json")
        if vb.get("status") == "ok":
            k["vlm_status"] = "measured"
            k["vlm_mae_cm"] = num(vb["vlm"]["mae_cm"])
            k["vlm_coverage"] = pct(vb["vlm"]["coverage"])
            k["vlm_cost_1k"] = f"${vb['vlm']['cost_usd_per_1k_frames_est']:.3f}"
            k["vlm_frames"] = num(vb["frames"])
            k["vlm_cv_same_mae_cm"] = num(vb["opencv_same_frames"]["mae_cm"])
            k["vlm_sentence"] = (f"A vision-language model ({vb['meta']['model']}) reading the gauge on the same {k['vlm_frames']} real frames: "
                                 f"{k['vlm_mae_cm']} cm MAE ({k['vlm_coverage']} answered), about {k['vlm_cost_1k']} per 1,000 frames; OpenCV on the same frames {k['vlm_cv_same_mae_cm']} cm.")
        else:
            k["vlm_status"] = "not measured"
            k["vlm_sentence"] = ("The planned vision-language baseline (a Bedrock model reading the gauge on every real frame, `eval/run_vlm_baseline.py`) "
                                 "could not run: the account's Bedrock quota is zero. No comparison is claimed.")
    sk = _load(RES / "soak.json")
    if sk:
        sources.append("eval/results/soak.json")
        k["soak_hours"] = num(sk["hours_observed"])
        k["soak_probes"] = num(sk["health_probes"])
        k["soak_uptime"] = pct(sk["uptime"], 1)
        k["soak_p50_ms"] = num(sk["health_latency_ms_p50"], 0)
        k["soak_p95_ms"] = num(sk["health_latency_ms_p95"], 0)
        k["soak_cycles"] = num(sk["agent_cycles_total"])
    old = _load(RES / "stage_real.json")
    if old:
        sources.append("eval/results/stage_real.json")
        k["real_fitted_protocol_mae_cm"] = num(old["pooled"]["full"]["mean_site_mae_cm"])
        k["real_fitted_protocol_const_cm"] = num(old["pooled"]["B_const_calibration_median"]["mean_site_mae_cm"])

    # ---- lead time on real gauge pairs
    lt = _load(RES / "leadtime.json")
    if lt:
        sources.append("eval/results/leadtime.json")
        for cond, key in [("nws_action/gauge", "lt_nws"), ("p95/gauge", "lt_p95"), ("p95/camera_noise", "lt_p95cam"), ("nws_action/camera_noise", "lt_nwscam")]:
            t = lt["pooled"][cond]["test"]
            k[f"{key}_events"] = num(t["n_events"])
            k[f"{key}_gain_median_min"] = num(t["gain_median_min"], 0)
            k[f"{key}_gain_median_h"] = num(t["gain_median_min"] / 60, 1)
            k[f"{key}_gain_ci"] = f"{t['gain_median_ci95_min'][0]:.0f}–{t['gain_median_ci95_min'][1]:.0f}"
            k[f"{key}_gain_mean_min"] = num(t["gain_mean_min"], 0)
            k[f"{key}_gain_mean_h"] = num(t["gain_mean_min"] / 60, 1)
            k[f"{key}_det_down"] = pct(t["detection_rate_downstream_only"])
            k[f"{key}_det_comb"] = pct(t["detection_rate_combined"])
            k[f"{key}_fa_up"] = num(t["false_alerts_upstream_per_30d"], 2)
            k[f"{key}_fa_down"] = num(t["false_alerts_downstream_only_per_30d"], 2)
            k[f"{key}_frac_gain"] = pct(t["frac_events_with_gain"])
        k["lt_pairs"] = num(lt["pooled"]["nws_action/gauge"]["test"]["n_pairs"])
        item("leadtime_p95", "Median lead time gained downstream (real gauge pairs, percentile warning levels)", lt["pooled"]["p95/gauge"]["test"]["gain_median_min"], "min",
             {"name": "same rule at the downstream gauge only", "value": 0}, "REAL USGS gauge pairs, held-out 2024-2026", "eval/results/leadtime.json")
        item("leadtime_nws", "Median lead time gained downstream (official NWS action stages, pre-registered primary)", lt["pooled"]["nws_action/gauge"]["test"]["gain_median_min"], "min",
             {"name": "downstream gauge only", "value": 0}, "REAL USGS gauge pairs, held-out 2024-2026", "eval/results/leadtime.json")

    # ---- agent scenario suite
    ag = _load(RES / "agent_suite.json")
    if ag:
        sources.append("eval/results/agent_suite.json")
        a, b = ag["summary"]["agent"], ag["summary"]["baseline_rule_only"]
        for key, d in [("ag", a), ("rb", b)]:
            k[f"{key}_false_alert_runs"] = num(d["false_alert_runs"])
            k[f"{key}_false_sirens"] = num(d["false_sirens"])
            k[f"{key}_missed_alerts"] = num(d["missed_alerts"])
            k[f"{key}_missed_sirens"] = num(d["missed_sirens"])
            k[f"{key}_lead_median_min"] = num(d["alert_lead_min_median"], 0)
            k[f"{key}_success"] = f"{d['success_runs']}/{d['flood_runs'] + d['quiet_runs']}"
            k[f"{key}_cycles"] = num(d["decision_cycles"])
            k[f"{key}_ms_cycle"] = num(d["ms_per_cycle_median"], 0)
        k["ag_quiet_runs"] = num(a["quiet_runs"])
        pj = ag["summary"].get("baseline_projection_no_gates")
        if pj:
            for kk, v in [("pj_false_alert_runs", pj["false_alert_runs"]), ("pj_false_sirens", pj["false_sirens"]),
                          ("pj_missed_alerts", pj["missed_alerts"]), ("pj_missed_sirens", pj["missed_sirens"])]:
                k[kk] = num(v)
            k["pj_lead_median_min"] = num(pj["alert_lead_min_median"], 0)
            k["pj_success"] = f"{pj['success_runs']}/{pj['flood_runs'] + pj['quiet_runs']}"
        k["ag_runs"] = num(a["flood_runs"] + a["quiet_runs"])
        sp = ag.get("plan_splits") or []
        k["split_n"] = num(len(sp))
        if sp:
            k["split_variant"] = sp[0]["variant"]
            k["split_t"] = num(sp[0]["no_gates_alert_min"], 0)
            k["split_agent_summary"] = sp[0]["agent_cycle"]["summary"]
            k["split_branches"] = ", ".join(sp[0]["agent_cycle"]["branches"]) or "none"
        un = ag.get("summary_unseen_seeds")
        if un:
            for key, d in [("agu", un["agent"]), ("rbu", un["baseline_rule_only"]), ("pju", un["baseline_projection_no_gates"])]:
                k[f"{key}_success"] = f"{d['success_runs']}/{d['flood_runs'] + d['quiet_runs']}"
                k[f"{key}_false_alert_runs"] = num(d["false_alert_runs"])
                k[f"{key}_lead_median_min"] = num(d["alert_lead_min_median"], 0)
            k["agu_runs"] = num(un["agent"]["flood_runs"] + un["agent"]["quiet_runs"])
        k["ag_flood_runs"] = num(a["flood_runs"])
        item("agent_success", "Agent scenario suite success (runs)", a["success_runs"], "runs",
             {"name": "rule-only threshold agent", "value": b["success_runs"]}, ag["meta"]["label"], "eval/results/agent_suite.json")

    # ---- COOL / Graviton benchmark
    bench = {p.stem: json.loads(p.read_text()) for p in BENCH.glob("*.json")} if BENCH.exists() else {}
    def bk(prefix, d):
        k[f"{prefix}_ms"] = num(d["latency"]["ms_per_burst_mean_of_repeats"])
        k[f"{prefix}_ms_sd"] = num(d["latency"]["ms_per_burst_stdev"], 2)
        k[f"{prefix}_fps"] = num(d["throughput"]["frames_per_s"])
        k[f"{prefix}_cams"] = num(d["throughput"]["cameras_at_10s_cadence"])
        k[f"{prefix}_usd_1m"] = "n/a" if d["cost"]["usd_per_million_frames"] is None else f"${d['cost']['usd_per_million_frames']:.3f}"
        k[f"{prefix}_usd_h"] = "n/a" if d["cost"]["usd_per_hour_total"] is None else f"${d['cost']['usd_per_hour_total']:.4f}"
        k[f"{prefix}_ami"] = d["host"].get("ec2_ami_id") or "n/a"
        k[f"{prefix}_type"] = d["host"].get("ec2_instance_type") or "local"
        k[f"{prefix}_cpu"] = d["host"].get("cpu_model") or "n/a"
        usd_h = d["cost"]["usd_per_hour_total"]
        bps = d["throughput"]["bursts_per_s"]
        if usd_h:
            month = usd_h * 730
            k[f"{prefix}_usd_month"] = f"${month:,.0f}"
            for cad in (10, 300):
                cams = int(bps * cad)
                k[f"{prefix}_cams_{cad}s"] = num(cams)
                k[f"{prefix}_usd_cam_month_{cad}s"] = f"${month / max(cams, 1):,.2f}"
        k[f"{prefix}_kleidi"] = "yes" if d["host"]["kleidicv_present"] else "no"
        k[f"{prefix}_cv2"] = d["host"]["opencv_version"]
        k[f"{prefix}_hash"] = d["equivalence"]["outputs_mm_sha256"][:12]
        m = d["micro_ms"]
        k[f"{prefix}_aliked_ms"] = num(m["aliked_lightglue_registration"]["ms_p50"], 0) if isinstance(m["aliked_lightglue_registration"], dict) else "n/a"
        k[f"{prefix}_dis_ms"] = num(m["dis_flow_960x540"]["ms_p50"])
        k[f"{prefix}_yunet_ms"] = num(m["yunet_redact_960x540"]["ms_p50"])
        k[f"{prefix}_orb_ms"] = num(m["orb_registration"]["ms_p50"])
        st = d["latency"]["per_stage_ms"]
        for s_ in ("register", "redact", "E2_temporal", "surface_motion", "warp", "quality"):
            if s_ in st:
                k[f"{prefix}_st_{s_}"] = num(st[s_]["p50"])
        sc = {x["threads"]: x["ms_per_burst"] for x in d["thread_scaling"]}
        k[f"{prefix}_t1"] = num(sc.get(1))
        k[f"{prefix}_t4"] = num(sc.get(4))
    for name, prefix in [("A-cool-c8g.xlarge", "A"), ("B-stock-wheel-c8g.xlarge", "B"), ("C-stock-wheel-c7i.xlarge", "C")]:
        if name in bench:
            sources.append(f"bench/results/{name}.json")
            bk(prefix, bench[name])
        else:
            k[f"{prefix}_status"] = "not yet run"
    if "B" + "_fps" in k and "C_fps" in k:
        b, c = bench["B-stock-wheel-c8g.xlarge"], bench["C-stock-wheel-c7i.xlarge"]
        k["BC_speedup"] = f"{c['latency']['ms_per_burst_mean_of_repeats'] / b['latency']['ms_per_burst_mean_of_repeats']:.2f}×"
        k["BC_tp_ratio"] = f"{b['throughput']['frames_per_s'] / c['throughput']['frames_per_s']:.2f}×"
        k["BC_cost_saving"] = pct(1 - b["cost"]["usd_per_million_frames"] / c["cost"]["usd_per_million_frames"])
        k["BC_aliked_speedup"] = f"{c['micro_ms']['aliked_lightglue_registration']['ms_p50'] / b['micro_ms']['aliked_lightglue_registration']['ms_p50']:.2f}×"
        k["BC_dis_speedup"] = f"{c['micro_ms']['dis_flow_960x540']['ms_p50'] / b['micro_ms']['dis_flow_960x540']['ms_p50']:.2f}×"
        k["BC_equal"] = "identical" if b["equivalence"]["outputs_mm_sha256"] == c["equivalence"]["outputs_mm_sha256"] else "different"
        item("graviton_cost", "Cost per 1M frames, Graviton4 c8g vs x86 c7i (same 4 vCPU, same frames)", b["cost"]["usd_per_million_frames"], "USD",
             {"name": "c7i.xlarge x86", "value": c["cost"]["usd_per_million_frames"]}, "SYNTHETIC benchmark workload", "bench/results/")
    if "A_fps" in k and "B_fps" in k:
        a_, b_ = bench["A-cool-c8g.xlarge"], bench["B-stock-wheel-c8g.xlarge"]
        k["AB_speedup"] = f"{b_['latency']['ms_per_burst_mean_of_repeats'] / a_['latency']['ms_per_burst_mean_of_repeats']:.2f}×"
        k["AB_equal"] = "identical" if a_["equivalence"]["outputs_mm_sha256"] == b_["equivalence"]["outputs_mm_sha256"] else "different"
    sk = _load(RES / "soak.json")
    if sk:
        if sk.get("stage_ms_mean_of_5min_means") and "B_usd_month" in k:
            ms = sk["stage_ms_mean_of_5min_means"]
            vcpu = 4
            cyc_per_s = vcpu * 1000.0 / ms
            month = float(k["B_usd_month"].strip("$").replace(",", ""))
            k["cloud_cycle_ms"] = num(ms, 0)
            for cad in (10, 300):
                cams = int(cyc_per_s * cad)
                k[f"cloud_cams_{cad}s"] = num(cams)
                k[f"cloud_usd_cam_month_{cad}s"] = f"${month / max(cams, 1):,.2f}"
    k["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return k, items, sources


def render(text: str, keys: dict[str, str]) -> tuple[str, list[str]]:
    missing: list[str] = []

    def sub(m):
        name = m.group(1)
        if name not in keys:
            missing.append(name)
            return f"[[missing:{name}]]"
        return keys[name]

    return re.sub(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}", sub, text), missing


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    keys, items, sources = build()
    headline = {"generated_from": sources, "items": items, "keys": keys}
    stale, missing_all = [], []
    out_headline = RES / "headline.json"
    if not a.check:
        out_headline.write_text(json.dumps(headline, indent=1, ensure_ascii=False))
    for tpl, target in TARGETS.items():
        src = TEMPLATES / tpl
        if not src.exists():
            continue
        text, missing = render(src.read_text(encoding="utf-8"), keys)
        missing_all += [f"{tpl}:{m}" for m in missing]
        if a.check:
            cur = target.read_text(encoding="utf-8") if target.exists() else ""
            # generated_at changes every run; compare without it
            if re.sub(r"Numbers generated .*?\.", "", cur) != re.sub(r"Numbers generated .*?\.", "", text):
                stale.append(str(target.relative_to(ROOT)))
        else:
            target.write_text(text, encoding="utf-8")
    if missing_all:
        print("unknown keys:", ", ".join(missing_all))
    if a.check:
        if stale or missing_all:
            print("STALE docs (run python scripts/make_headline.py):", ", ".join(stale))
            return 1
        print(f"check-numbers OK: {len(keys)} keys, {len(TARGETS)} documents in sync with {len(sources)} result files")
        return 0
    print(f"wrote eval/results/headline.json ({len(keys)} keys) and {sum((TEMPLATES / t).exists() for t in TARGETS)} documents")
    return 1 if missing_all else 0


if __name__ == "__main__":
    sys.exit(main())
