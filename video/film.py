"""The NadiSaathi film, built from data: the edit list below, the narrator's voiced lines (synth.py), screen takes of
the live deployment and the AWS console (record.py), drawn scenes (gfx.html), Prashant's own camera lines, and the
composed theme (music.py). A change to a line or a shot means re-running this script, not re-editing a timeline.

    python3 video/film.py              ->  ~/Videos/jalrekha/NadiSaathi.mp4 (+ a 720p copy and an .srt)
    python3 video/film.py --preview    ->  faster, lower quality

Prashant's camera lines come from ~/Downloads/*nadisaathi-face*.(mp4|mov|webm|mkv): transcribed once with Whisper,
the better take of each scripted line picked by its words. Until that file exists, each line is a labelled
placeholder card, so the rest of the film can be reviewed.
"""

from __future__ import annotations

import asyncio
import difflib
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.parse
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from facts import F  # noqa: E402
from narration import load  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HOME = Path(os.path.expanduser("~/Videos/jalrekha"))
B = HOME / "build"
TAKES = HOME / "takes"
AUDIO = HOME / "audio"
FONTS = HOME / "fonts"
PREVIEW = "--preview" in sys.argv
HARDWARE = "--hardware" in sys.argv  # private cut: field-hardware scene and real edge-hardware footage after line 3
HW = HOME / "hw"
W, H, FPS, SR = 1920, 1080, 30, 48000
NAR_AT = 0.4      # narrator starts this long into a segment
GAP = 0.55        # between two narrator lines in one segment
TAIL = 0.5        # after the last word of a segment
IMG = ROOT / "frontend" / "public" / "images" / "india"
LIME = "&H003DFFC6&"  # #C6FF3D in ASS (blue, green, red)

FACE_LINES = {
    1: "I'm Prashant. I built NadiSaathi. It means river friend.",
    2: "The Koshi rises in Nepal and floods Bihar hours later. Today, most of those hours are wasted.",
    3: "So I pointed a camera at a river gauge, and taught OpenCV to read it in metres.",
    4: "Everything the agent decides starts with what OpenCV sees. Let me show you, step by step.",
    5: "Nothing goes to the public without a person. The agent drafts. A human approves.",
    6: "And every decision is logged on AWS. You don't have to take my word for it.",
    7: "The river will rise again this monsoon. This time, the warning can arrive first.",
    8: "NadiSaathi is live. Open it, run a replay, and read the traces yourself.",
}


def photo(pid: str) -> dict:
    c = next(x for x in json.loads((IMG / "credits.json").read_text()) if x["id"] == pid)
    return {"img": f"file://{IMG / (pid + '-1600.webp')}", "credit": f"Photo: {c['author']} · {c['license']} · Wikimedia Commons"}


FOOTAGE = HOME / "footage"


def footage_credit(key: str) -> str:
    c = json.loads((FOOTAGE / "credits.json").read_text())[key]
    who = c["author"].split("\n")[0].strip()
    return f"Footage: {who} · {c['license']} · Wikimedia Commons"


def seg(**kw) -> dict:
    kw.setdefault("nar", [])
    return kw


# ------------------------------------------------------------------ the edit list
EDL = [
    seg(name="story1", kind="footage", src="kosi_vn", a=750.0, b=760.0, sub=True, nar=["s1"], chapter="The river",
        label="Kosi flood · Bihar · 2008 (aerial)"),
    seg(name="story2", kind="footage", src="trishuli", a=0.0, b=10.2, nar=["s2"], label="Trishuli River · the hills of Nepal"),
    seg(name="story3", kind="footage", src="kosi_vn", a=183.0, b=196.5, sub=True, nar=["s3"], label="The Kosi on the plains"),
    seg(name="story4", kind="footage", src="kosi_vn", a=1208.2, b=1215.5, sub=True, nar=["s4"], label="Leaving home through floodwater · Kosi basin"),
    seg(name="story5", kind="footage", src="kosi4k", a=3.0, b=20.0, nar=["s5"], min=5.0, label="The Kosi moving its course, 1984 → 2018 · satellite timelapse"),
    seg(name="turn", kind="gfx", scene="turn", p={"t1": 1.5, "t2": 2.2, "t3": 3.3, "t4": 4.3}, nar=["t1"], min=6.0),
    seg(name="face1", kind="face", line=1, chapter="Why"),
    seg(name="face2", kind="face", line=2),
    seg(name="face3", kind="face", line=3),
    seg(name="live1", kind="screen", take="live", a="speed", b=12.0, nar=["l1"], chapter="Live", clicks=["speed", "run"],
        label="Live · scenario replay: generated camera frames, real OpenCV, real agent"),
    seg(name="live2", kind="screen", take="live", a=12.0, b="chart", nar=["l2", "l3"], label="Live · the river climbs; the agent checks more often"),
    seg(name="rivers", kind="screen", take="rivers", a=1.5, b="end", nar=["l4"], clicks=["eta"], label="Rivers · arrival windows from Chatara"),
    seg(name="face4", kind="face", line=4, chapter="OpenCV"),
    seg(name="v_quality", kind="screen", take="vision", a="quality", b="registration", nar=["v1", "v2"], label="Vision Lab · one real cycle, rebuilt · quality gate"),
    seg(name="v_reg", kind="screen", take="vision", a="registration", b="strip", nar=["v3"], label="Vision Lab · ORB registration (RANSAC inliers)"),
    seg(name="v_strip", kind="screen", take="vision", a="strip", b="estimators", nar=["v4"], label="Vision Lab · warpAffine gauge strip · burst median"),
    seg(name="v_est", kind="screen", take="vision", a="estimators", b="fusion", nar=["v5"], label="Vision Lab · Scharr edges · DIS optical flow · Lab colour"),
    seg(name="v_time", kind="screen", take="vision", a="timing", b="end", nar=["v6", "v7"], label="Vision Lab · stage timing on AWS Graviton4"),
    seg(name="redteam", kind="screen", take="redteam", a=0.0, b="end", nar=["a1", "a2", "a3"], chapter="Agent", clicks=["submit"],
        label="Agent trace · try to fool the guard (sandbox camera, no recipients)"),
    seg(name="face5", kind="face", line=5),
    seg(name="approve", kind="screen", take="approve", a=1.0, b="end", nar=["p1"], clicks=["pin", "sent"],
        label="Approvals · drafts in Hindi, Maithili and English · operator PIN"),
    seg(name="arch", kind="three", nar=["x1", "x2", "x3", "x4", "x5"], chapter="Under the hood"),
    seg(name="face6", kind="face", line=6, chapter="AWS"),
    seg(name="cloud", kind="screen", take="cloud", a="log", b="insights", nar=["w1"], label="NadiSaathi · AWS cloud page, read live"),
    seg(name="aws_logs", kind="screen", take="aws_logs", a=0.5, b="end", nar=[], label="AWS console · CloudWatch Logs · one JSON event per cycle (read-only session)"),
    seg(name="aws_dash", kind="screen", take="aws_dashboard", a=0.5, b="end", nar=["w2"], label="AWS console · CloudWatch dashboard and Logs Insights"),
    seg(name="aws_s3", kind="screen", take="aws_s3", a=0.5, b="end", nar=[], label="AWS console · S3 evidence archive, one event and one overlay per cycle"),
    seg(name="aws_sfn", kind="screen", take="aws_sfn", a=0.5, b="end", nar=["w5"], label="AWS console · Step Functions approval reminders"),
    seg(name="aws_stack", kind="screen", take="aws_stack", a=0.5, b="end", nar=["w3"], label="AWS console · CloudFormation stack"),
    seg(name="aws_ec2", kind="screen", take="aws_ec2", a=0.5, b="end", nar=[], label="AWS console · EC2 c8g.xlarge (Graviton4, arm64)"),
    seg(name="mcp", kind="gfx", scene="mcp", nar=["w4"], min=7.0),
    seg(name="stats", kind="gfx", scene="stats", nar=["n1"], min=9.0, chapter="Proof"),
    seg(name="built", kind="gfx", scene="built", nar=["b1"], min=8.0),
    seg(name="close_photo", kind="footage", src="kosi_vn", a=75.0, b=79.5, sub=True, nar=[], min=2.4, chapter="Close", label="The Kosi, coming down from Nepal"),
    seg(name="face7", kind="face", line=7),
    seg(name="face8", kind="face", line=8),
    seg(name="end", kind="gfx", scene="end", nar=["c1"], min=7.0),
]
# The private hardware cut reads its extra segments from a local file outside the repository.
HW_FILE = HW / "segments.json"
HW_SEGS = [seg(**x) for x in json.loads(HW_FILE.read_text())] if HARDWARE and HW_FILE.exists() else []
if HARDWARE:
    at = next(i for i, x in enumerate(EDL) if x["name"] == "face3") + 1
    EDL[at:at] = HW_SEGS
# Segments with no narrator line still have a voice: the previous line runs over them (an L-cut), set by `carry`.
CARRY = {"aws_logs": "cloud", "aws_s3": "aws_dash", "aws_ec2": "aws_stack"}


# ------------------------------------------------------------------ inputs
def lines() -> dict:
    return json.loads((AUDIO / "lines.json").read_text())


def words() -> dict:
    return json.loads((AUDIO / "words.json").read_text())


CAPTIONS = {lid: cap for _s, lid, cap, *_ in load()}


def take_marks(name: str) -> dict:
    return json.loads((TAKES / f"{name}.json").read_text())["marks"]


def mark(take: str, v) -> float:
    return float(take_marks(take)[v]) if isinstance(v, str) else float(v)


FACE_DIR = Path(os.path.expanduser("~/Downloads"))
FACE_WORDS = HOME / "face_words.json"   # Whisper word times for each camera clip (n.mov), made once


def fix_words(ws: list) -> list:
    """Whisper's words as captions: the product's spelling, hyphenated words joined, metres not meters."""
    out: list = []
    for w, a, b in ws:
        if out and w.startswith("-"):
            out[-1] = [out[-1][0] + w, out[-1][1], b]
            continue
        if out and out[-1][0].lower() == "nadi" and w.lower().startswith("sati"):
            out[-1] = ["NadiSaathi" + w[4:], out[-1][1], b]
            continue
        w = re.sub(r"^meters", "metres", w)
        out.append([w, a, b])
    return out


def face_take(n: int) -> dict | None:
    src = FACE_DIR / f"{n}.mov"
    if not src.exists() or not FACE_WORDS.exists():
        return None
    ws = json.loads(FACE_WORDS.read_text()).get(str(n))
    if not ws:
        return None
    ws = fix_words(ws)
    if n == 8:  # he says "live"; Whisper hears "life"
        ws = [[("live," if w.lower() == "life," else w), a, b] for w, a, b in ws]
    return {"src": str(src), "start": max(ws[0][1] - 0.05, 0.0), "end": ws[-1][2], "words": ws,
            "caption": " ".join(w for w, *_ in ws)}


# ------------------------------------------------------------------ timing
def plan() -> tuple[list[dict], float]:
    L = lines()
    faces = {n: face_take(n) for n in FACE_LINES}
    t = 0.0
    out = []
    for s in EDL:
        s = dict(s)
        nar_len = sum(L[lid]["s"] for lid in s["nar"]) + GAP * max(0, len(s["nar"]) - 1)
        need = (NAR_AT + nar_len + TAIL) if s["nar"] else 0.0
        if s["kind"] == "face":
            f = faces.get(s["line"])
            if f:
                s["face"] = f
                s["dur"] = round(f["end"] - f["start"] + 0.75, 2)
            else:
                s["dur"] = round(len(FACE_LINES[s["line"]].split()) / 2.4 + 1.2, 2)
        elif s["kind"] == "screen":
            a, b = mark(s["take"], s["a"]), mark(s["take"], s["b"])
            span = b - a
            if s["name"] in CARRY:  # an L-cut: picture only, kept short
                dur = min(span, 4.5)
            else:
                dur = max(need, 3.0)
            speed = span / dur if span > dur else 1.0
            speed = min(speed, 3.0)
            s.update(a_s=a, span=span, speed=round(speed, 3), dur=round(max(dur, span / 3.0), 2))
        elif s["kind"] == "footage":
            span = s["b"] - s["a"]
            dur = max(need, s.get("min", 3.0))
            s.update(a_s=s["a"], speed=round(max(min(span / dur, 1.0), 0.65), 3))
            s["span"] = round(min(span, dur * s["speed"]), 3)
            s["dur"] = dur
        else:
            s["dur"] = round(max(need, s.get("min", 4.0)), 2)
        s["dur"] = round(round(s["dur"] * FPS) / FPS, 4)
        s["start"] = round(t, 4)
        t += s["dur"]
        out.append(s)
    return out, round(t, 4)


# ------------------------------------------------------------------ the 3D architecture scene
HW_BEATS = [("pole", "h1", r"camera"), ("burst", "h2", r"burst"), ("uplink", "h2", r"mobile|network"),
            ("opencv", "h3", r"opencv|open|waterline"), ("rise", "h3", r"metres|meters")]
THREE_BEATS = [("layer1", "x2", r"camera"), ("layer2", "x2", r"opencv|open"), ("packets", "x2", r"metres|meters"),
               ("layer3", "x3", r"agent"), ("layer4", "x3", r"guard"), ("blocked", "x4", r"lying"),
               ("layer5", "x4", r"person"), ("person", "x4", r"pin"), ("layer6", "x4", r"districts"), ("aws", "x5", r"cloudwatch")]


def three_cues(s: dict) -> dict:
    L, WD = lines(), words()
    beats = HW_BEATS if s["kind"] == "hwthree" else THREE_BEATS
    starts, t = {}, NAR_AT
    for lid in s["nar"]:
        starts[lid] = t
        t += L[lid]["s"] + GAP
    cues = {}
    for name, lid, rx in beats:
        hit = next((w for w in WD.get(lid, []) if re.search(rx, w[0].lower())), None)
        cues[name] = round(starts[lid] + (hit[1] if hit else 0.5), 2)
    if s["kind"] == "hwthree":
        cues["scene"] = 0.2
    return cues


async def record_three(todo: list[dict]) -> None:
    from playwright.async_api import async_playwright

    from record import Take

    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--use-angle=gl", "--enable-gpu", "--ignore-gpu-blocklist", "--allow-file-access-from-files"])
        for s in todo:
            ctx = await browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=1)
            page = await ctx.new_page()
            page_file = "hardware.html" if s["kind"] == "hwthree" else "three.html"
            url = f"file://{ROOT / 'video' / page_file}?dur={s['dur']}&cues=" + urllib.parse.quote(json.dumps(three_cues(s)))
            await page.goto(url)
            await page.wait_for_function("window.__ready === true", timeout=60000)
            await asyncio.sleep(0.8)
            cdp = await ctx.new_cdp_session(page)
            t = Take(s["key"], page, cdp)
            await t.start()
            await page.evaluate("window.__start()")
            await asyncio.sleep(s["dur"] + 0.3)
            await t.stop()
            await ctx.close()
        await browser.close()


# ------------------------------------------------------------------ drawn scenes (Playwright screencast)
def gfx_params(s: dict) -> dict:
    if s["kind"] == "photo":
        return s["p"]
    if s["scene"] == "turn":
        return s.get("p", {})
    if s["scene"] == "stats":
        b0 = F["b0_on_subset_cm"]
        return {"cards": [
            {"tag": "OpenCV · real USGS cameras", "value": float(F["real_mae_cm"]), "dec": 1, "unit": "cm",
             "label": "average error reading a real river gauge", "vs": f"method we started from: {b0} cm on the frames it could read",
             "src": "eval/results/stage_real_physical.json", "at": 0.9},
            {"tag": "Agent · guard", "value": float(F["guard_caught"]), "unit": f"/ {F['guard_bad']}",
             "label": "lying or injected model replies caught", "vs": "the danger siren was never cancelled",
             "src": "eval/results/guard_eval.json", "at": 2.4},
            {"tag": "Agent · 36 replays", "value": float(F["lead_min"]), "unit": "min",
             "label": "median warning before the river crossed the warning level", "vs": f"{F['false_alert_runs']} false-alert runs",
             "src": "eval/results/agent_suite.json", "at": 3.9},
        ]}
    if s["scene"] == "built":
        return {"boxes": [
            {"k": "Camera", "v": "Staff gauge", "d": "a burst of 5 frames", "at": 0.6},
            {"k": "OpenCV 5", "v": "Metres ± σ", "d": "ORB · ALIKED+LightGlue · Scharr · DIS flow · Kalman · YuNet", "at": 1.3},
            {"k": "Agent", "v": "D1–D9", "d": "cadence, second opinion, ETA, drafts", "at": 2.0},
            {"k": "Person", "v": "PIN", "d": "approves every public alert", "at": 2.7},
        ], "chipsAt": 3.4, "chips": [{"t": t, "l": i < 2} for i, t in enumerate(
            ["EC2 Graviton4 · c8g", "OpenCV 5 + KleidiCV", "API Gateway", "CloudWatch Logs + Insights", "CloudWatch metrics + alarms",
             "S3 evidence", "Step Functions", "SNS", "Polly", "Lambda", "SSM", "Budgets", "CloudFormation", "Claude", "MCP"])]}
    if s["scene"] == "mcp":
        m = json.loads((HOME / "mcp_session.json").read_text())
        rs, eta = m["river_status"], m["downstream_eta"]["downstream"]
        lines_ = ['<span class="p">$</span> mcp client → nadisaathi (stdio) · list_tools',
                  f"  {len(m['tools'])} tools: " + ", ".join(t["name"] for t in m["tools"]),
                  '  <span class="no">no tool can approve, edit or send an alert</span>', "",
                  '<span class="p">$</span> call river_status(site_id="koshi-chatara-cam")',
                  f"  stage_m: {rs['stage_m']:.2f}   sigma_m: {rs['sigma_m']:.3f}   rate_m_per_h: {rs['rate_m_per_h']:+.2f}",
                  f"  warning_m: {rs['warning_m']}   danger_m: {rs['danger_m']}   quality_ok: {rs['quality_ok']}", "",
                  '<span class="p">$</span> call downstream_eta(basin="koshi", from_node="chatara")']
        lines_ += [f"  {n['name']:<26} {n['eta_h']['min']:>5.1f} – {n['eta_h']['max']:>5.1f} h" + ("   crosses border" if n["crosses_border"] else "") for n in eta]
        return {"lines": lines_, "gap": 230}
    if s["scene"] == "end":
        qr = subprocess.run(["qrencode", "-t", "SVG", "-m", "1", "-o", "-", "https://gaq7chhmb2.execute-api.us-east-1.amazonaws.com"],
                            check=True, capture_output=True, text=True).stdout
        qr = qr[qr.index("<svg"):]
        return {"qr": qr, "links": [{"k": "Live", "v": "gaq7chhmb2.execute-api.us-east-1.amazonaws.com"},
                                    {"k": "Code", "v": "github.com/Prashant-thakur77/JalRekha"},
                                    {"k": "Try it", "v": "run a replay · open the Vision Lab · read the traces"}]}
    return {}


async def record_gfx(todo: list[dict]) -> None:
    from playwright.async_api import async_playwright

    from record import Take

    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--use-angle=gl", "--enable-gpu", "--ignore-gpu-blocklist", "--allow-file-access-from-files"])
        for s in todo:
            ctx = await browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=1)
            page = await ctx.new_page()
            scene = "photo" if s["kind"] == "photo" else s["scene"]
            url = (f"file://{ROOT / 'video' / 'gfx.html'}?scene={scene}&dur={s['dur']}&p="
                   + urllib.parse.quote(urllib.parse.quote(json.dumps(gfx_params(s)))))
            await page.goto(url)
            await page.wait_for_function("window.__ready === true", timeout=30000)
            await asyncio.sleep(0.6)
            cdp = await ctx.new_cdp_session(page)
            t = Take(s["key"], page, cdp)
            await t.start()
            await page.evaluate("window.__start()")
            await asyncio.sleep(s["dur"] + 0.3)
            await t.stop()
            await ctx.close()
        await browser.close()


# ------------------------------------------------------------------ captions (ASS)
def chunks(ws: list[tuple[str, float, float]], max_chars: int = 34) -> list[list[tuple[str, float, float]]]:
    out, cur = [], []
    for w in ws:
        cur.append(w)
        text = " ".join(x[0] for x in cur)
        if len(text) >= max_chars or w[0][-1:] in ".?!," and len(cur) >= 2:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def caption_words(caption: str, heard: list) -> list[tuple[str, float, float]]:
    """Map the caption's own words (real spelling) onto Whisper's word times."""
    cap = caption.split()
    if not heard:
        return []
    hw = [h[0] for h in heard]
    sm = difflib.SequenceMatcher(None, [re.sub(r"\W", "", c.lower()) for c in cap], [re.sub(r"\W", "", h.lower()) for h in hw])
    times: list[tuple[float, float] | None] = [None] * len(cap)
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            times[a + k] = (heard[b + k][1], heard[b + k][2])
    t0, t1 = heard[0][1], heard[-1][2]
    for i in range(len(cap)):  # interpolate the words Whisper spelled differently
        if times[i] is None:
            prev = next((times[j][1] for j in range(i - 1, -1, -1) if times[j]), t0)
            nxt = next((times[j][0] for j in range(i + 1, len(cap)) if times[j]), t1)
            times[i] = (prev, max(prev + 0.05, nxt))
    return [(c, *times[i]) for i, c in enumerate(cap)]


def ass_time(t: float) -> str:
    t = max(t, 0)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def esc(s: str) -> str:
    return s.replace("{", "(").replace("}", ")")


KEY = re.compile(r"^(\d[\d.,/]*|NadiSaathi\.?|OpenCV|never|person|PIN\.?|Graviton,?|AWS|approves\.?|decides\.?|reads)$", re.I)


def build_ass(segs: list[dict], placements: list[tuple[float, str, list]], total: float) -> tuple[str, list]:
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Host Grotesk,62,&H00FFFFFF,&H00FFFFFF,&H66000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,2,2,120,120,92,1
Style: Label,Fragment Mono,22,&H00F3F2EE,&H00F3F2EE,&H00121211,&HB4121211,0,0,0,0,100,100,1.5,0,3,10,0,7,48,48,40,1
Style: Chip,Fragment Mono,22,&H003DFFC6,&H003DFFC6,&H00121211,&HB4121211,0,0,0,0,100,100,2,0,3,10,0,9,48,48,40,1
Style: Tag,Fragment Mono,20,&H00121211,&H00121211,&H003DFFC6,&H003DFFC6,0,0,0,0,100,100,1,0,3,8,0,9,48,48,96,1
Style: LabelSmall,Fragment Mono,11,&H00D9D8D2,&H00D9D8D2,&H00121211,&H99121211,0,0,0,0,100,100,0.8,0,3,4,0,7,22,22,18,1
Style: CapFace,Host Grotesk,58,&H00FFFFFF,&H00FFFFFF,&H66000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,2,2,120,120,30,1
Style: Name,Host Grotesk,54,&H00F3F2EE,&H00F3F2EE,&H00121211,&H80121211,0,0,0,0,100,100,0,0,1,0,2,1,90,90,250,1
Style: Ph,Host Grotesk,54,&H00F3F2EE,&H00F3F2EE,&H00121211,&H00121211,0,0,0,0,100,100,0,0,1,0,0,5,200,200,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev, srt = [], []
    chapter_n = 0
    chapter = ""
    for s in segs:
        a, b = s["start"], s["start"] + s["dur"]
        if s.get("chapter"):
            chapter_n += 1
            chapter = s["chapter"]
        if s["name"] != "story1":
            ev.append(f"Dialogue: 2,{ass_time(a)},{ass_time(b)},Chip,,0,0,0,,{chapter_n} · {chapter.upper()}")
        if s.get("label"):
            lab = s["label"] + (f" · {s.get('credit') or footage_credit(s['src'])}" if s["kind"] == "footage" else "")
            ev.append(f"Dialogue: 2,{ass_time(a)},{ass_time(b)},{'LabelSmall' if s.get('small') else 'Label'},,0,0,0,,{esc(lab)}")
        if s.get("speed", 1) > 1.25:
            ev.append(f"Dialogue: 2,{ass_time(a)},{ass_time(b)},Tag,,0,0,0,,SPED UP ×{s['speed']:.1f}")
        if s["name"] == "face1" and s.get("face"):
            ev.append(f"Dialogue: 2,{ass_time(a + 0.4)},{ass_time(b)},Name,,0,0,0,,Prashant{{\\fs28\\c&H3DFFC6&}}\\N{{\\fnFragment Mono}}BUILT NADISAATHI")
        if s["kind"] == "face" and not s.get("face"):
            ev.append(f"Dialogue: 1,{ass_time(a)},{ass_time(b)},Ph,,0,0,0,,{{\\fs30\\c&H3DFFC6&}}PRASHANT ON CAMERA · LINE {s['line']} (placeholder)\\N{{\\fs54\\c&HF3F2EE&}}{esc(FACE_LINES[s['line']])}")
    face_spans = [(x["start"], x["start"] + x["dur"]) for x in segs if x["kind"] == "face" and x.get("face")]
    for t0, cap, heard in placements:
        ws = caption_words(cap, heard)
        style = "CapFace" if ws and any(a_ <= t0 + ws[0][1] < b_ for a_, b_ in face_spans) else "Cap"
        if not ws:
            continue
        srt.append((t0 + ws[0][1], t0 + ws[-1][2], cap))
        phrases = chunks(ws)
        for k_, ph in enumerate(phrases):
            p0, p1 = t0 + ph[0][1], t0 + ph[-1][2] + 0.25
            if k_ + 1 < len(phrases):  # never two phrases on screen at once
                p1 = min(p1, t0 + phrases[k_ + 1][0][1] - 0.02)
            for i, (w, w0, w1) in enumerate(ph):
                s0 = t0 + w0 if i else p0
                s1 = t0 + ph[i + 1][1] if i + 1 < len(ph) else p1
                parts = []
                for j, (x, *_r) in enumerate(ph):
                    if j == i:
                        parts.append(f"{{\\c{LIME}\\fscx108\\fscy108}}{esc(x)}{{\\c&HFFFFFF&\\fscx100\\fscy100}}")
                    elif KEY.match(x):
                        parts.append(f"{{\\c{LIME}}}{esc(x)}{{\\c&HFFFFFF&}}")
                    else:
                        parts.append(esc(x))
                ev.append(f"Dialogue: 0,{ass_time(s0)},{ass_time(s1)},{style},,0,0,0,,{' '.join(parts)}")
    return head + "\n".join(ev) + "\n", srt


def write_srt(entries: list, path: Path) -> None:
    def ts(t):
        return f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{int(t % 60):02d},{int((t % 1) * 1000):03d}"
    path.write_text("\n".join(f"{i}\n{ts(a)} --> {ts(b)}\n{c}\n" for i, (a, b, c) in enumerate(sorted(entries), 1)))


# ------------------------------------------------------------------ audio
def read_wav(path: str) -> np.ndarray:
    out = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", path, "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(out, dtype=np.float32).copy()


def write_wav(path: Path, x: np.ndarray, ch: int = 1) -> None:
    x = np.clip(x, -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((x * 32767).astype("<i2").tobytes())


def sfx(kind: str) -> np.ndarray:
    p = B / f"sfx-{kind}.wav"
    if not p.exists():
        src = {"whoosh": "anoisesrc=color=pink:d=0.7:a=0.5,bandpass=f=1400:w=1100,afade=t=in:d=0.3:curve=qsin,afade=t=out:st=0.35:d=0.35:curve=qsin",
               "swish": "anoisesrc=color=pink:d=0.32:a=0.4,bandpass=f=2600:w=2200,afade=t=in:d=0.12:curve=qsin,afade=t=out:st=0.14:d=0.18:curve=qsin",
               "click": "sine=frequency=2200:duration=0.03,afade=t=out:st=0.008:d=0.022",
               "tick": "sine=frequency=3200:duration=0.014,afade=t=out:st=0.004:d=0.01",
               "hit": "aevalsrc='0.8*sin(2*PI*(55+80*exp(-30*t))*t)*exp(-6*t)':d=0.9",
               "riser": "aevalsrc='0.28*sin(2*PI*(180*t+260*t*t))*(t/1.3)*(t/1.3)':d=1.3,afade=t=out:st=1.2:d=0.1",
               "shimmer": "aevalsrc='0.22*(sin(2*PI*1568*t)+sin(2*PI*2093*t)+0.6*sin(2*PI*2637*t))*exp(-3*t)':d=1.2",
               "chime": "aevalsrc='0.32*(sin(2*PI*1046.5*t)*exp(-4*t)+gte(t,0.09)*sin(2*PI*1318.5*(t-0.09))*exp(-4*(t-0.09)))':d=1.0",
               "blip": "aevalsrc='0.4*sin(2*PI*1320*t)*exp(-25*t)':d=0.16",
               "buzz": "aevalsrc='0.32*(2*mod(110*t,1)-1)*exp(-5*t)':d=0.45,lowpass=f=900"}[kind]
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", src, "-ar", str(SR), "-ac", "1", str(p)], check=True)
    return read_wav(str(p))


def face_audio(src: str, a: float, b: float) -> np.ndarray:
    """His line from the camera clip: rumble cut, light denoise, softened esses, levelled to sit with the narrator."""
    out = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", src, "-af",
                          "highpass=f=80,afftdn=nr=10:nf=-42:tn=1,deesser=i=0.4:f=0.55,loudnorm=I=-19:TP=-2:LRA=7",
                          "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"], check=True, capture_output=True).stdout
    x = np.frombuffer(out, dtype=np.float32).copy()
    fade = int(0.03 * SR)
    x[:fade] *= np.linspace(0, 1, fade)
    x[-fade:] *= np.linspace(1, 0, fade)
    return x


def mix_at(track: np.ndarray, clip: np.ndarray, t: float, gain: float = 1.0) -> None:
    i = int(round(t * SR))
    j = min(len(track), i + len(clip))
    if i < len(track) and j > i:
        track[i:j] += clip[: j - i] * gain


# ------------------------------------------------------------------ main
def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def main() -> None:
    B.mkdir(parents=True, exist_ok=True)
    segs, total = plan()
    L = lines()
    WD = words()
    # where each narrator line lands
    placements, voice = [], np.zeros(int(total * SR) + SR, dtype=np.float32)
    for s in segs:
        t = s["start"] + NAR_AT
        for lid in s["nar"]:
            clip = read_wav(str(AUDIO / "lines" / f"{lid}.wav"))
            mix_at(voice, clip, t)
            placements.append((t, CAPTIONS[lid], WD.get(lid, [])))
            t += L[lid]["s"] + GAP
        if s["kind"] == "face" and s.get("face"):
            f = s["face"]
            a = face_audio(f["src"], f["start"], f["end"] + 0.2)
            mix_at(voice, a, s["start"] + 0.3)
            placements.append((s["start"] + 0.3 - f["start"], f["caption"], f["words"]))
    turn = next(s["start"] for s in segs if s["name"] == "turn")
    close = next(s["start"] for s in segs if s["name"] == "close_photo")
    (B / "timeline.json").write_text(json.dumps({"total": total, "turn": turn, "close": close,
                                                 "segments": [{k: s[k] for k in ("name", "kind", "start", "dur")} for s in segs]}, indent=1))
    # effects: whoosh at each chapter, a soft swish on every other cut, risers into the big moments, and a sound for
    # what happens on screen (a click, a chime when the alert is approved, a buzz when the guard blocks a reply)
    fx = np.zeros_like(voice)
    for k, s in enumerate(segs):
        if s["start"] > 0:
            if s.get("chapter"):
                mix_at(fx, sfx("whoosh"), s["start"] - 0.3, 0.42)
            elif segs[k - 1]["kind"] != s["kind"] or s["kind"] in ("footage", "screen"):
                mix_at(fx, sfx("swish"), s["start"] - 0.12, 0.16)
        for c in s.get("clicks", []):
            tc = (mark(s["take"], c) - s["a_s"]) / s["speed"]
            if 0 <= tc < s["dur"]:
                mix_at(fx, sfx("click"), s["start"] + tc + 0.55, 0.4)
        if s["name"] in ("turn", "arch", "stats"):
            mix_at(fx, sfx("riser"), s["start"] - 1.3, 0.3)
        if s["name"] == "turn":
            mix_at(fx, sfx("hit"), s["start"] + 0.2, 0.45)
            mix_at(fx, sfx("shimmer"), s["start"] + 0.25, 0.3)
        if s["name"] == "stats":
            for at in (0.9, 2.4, 3.9):
                mix_at(fx, sfx("hit"), s["start"] + at, 0.35)
        if s["name"] == "arch":
            cues = three_cues(s)
            for name in ("layer1", "layer2", "layer3", "layer4", "layer5", "layer6"):
                mix_at(fx, sfx("blip"), s["start"] + cues[name], 0.3)
            mix_at(fx, sfx("buzz"), s["start"] + cues["blocked"] + 0.5, 0.38)
            mix_at(fx, sfx("chime"), s["start"] + cues["person"], 0.34)
            mix_at(fx, sfx("shimmer"), s["start"] + cues["aws"], 0.2)
        if s["name"] == "redteam":
            tr = (mark("redteam", "result") - s["a_s"]) / s["speed"]
            mix_at(fx, sfx("buzz"), s["start"] + tr + 0.3, 0.32)
        if s["name"] == "approve":
            tr = (mark("approve", "sent") - s["a_s"]) / s["speed"]
            mix_at(fx, sfx("chime"), s["start"] + tr + 0.6, 0.34)
        if s["name"] == "mcp":
            for i_ in range(16):
                mix_at(fx, sfx("tick"), s["start"] + 0.9 + i_ * 0.23, 0.12)
        if s["name"] == "rivers":
            mix_at(fx, sfx("blip"), s["start"] + 2.6, 0.25)
        if s["name"] == "end":
            mix_at(fx, sfx("hit"), s["start"] + 0.2, 0.4)
            mix_at(fx, sfx("shimmer"), s["start"] + 0.3, 0.25)
    write_wav(B / "voice.wav", voice)
    write_wav(B / "fx.wav", fx)
    run([os.path.expanduser("~/Videos/jalrekha/.venv-music/bin/python"), str(ROOT / "video" / "music.py")])

    # drawn scenes: record the ones not cached for their current parameters
    todo = []
    for s in segs:
        if s["kind"] in ("photo", "gfx"):
            s["key"] = "gfx-" + hashlib.sha1(json.dumps([s["name"], s["dur"], gfx_params(s),
                                                         (ROOT / "video" / "gfx.html").read_text()]).encode()).hexdigest()[:12]
            if not (TAKES / f"{s['key']}.mp4").exists():
                todo.append(s)
    if todo:
        asyncio.run(record_gfx(todo))
    todo3 = []
    for s in segs:
        if s["kind"] in ("three", "hwthree"):
            page_file = "hardware.html" if s["kind"] == "hwthree" else "three.html"
            s["key"] = s["kind"] + "-" + hashlib.sha1(json.dumps([s["dur"], three_cues(s), (ROOT / "video" / page_file).read_text()]).encode()).hexdigest()[:12]
            if not (TAKES / f"{s['key']}.mp4").exists():
                todo3.append(s)
    if todo3:
        asyncio.run(record_three(todo3))

    # picture: each segment to the same format, then one concat
    crf = "26" if PREVIEW else "17"
    parts = []
    for i, s in enumerate(segs):
        out = B / f"seg{i:02d}-{s['name']}.mkv"
        d = s["dur"]
        if s["kind"] in ("photo", "gfx"):
            inp = ["-i", str(TAKES / f"{s['key']}.mp4")]
            vf = f"trim=start=0.3,setpts=PTS-STARTPTS,fps={FPS},scale={W}:{H},tpad=stop_mode=clone:stop_duration={d}"
        elif s["kind"] == "footage":
            inp = ["-ss", f"{s['a_s']:.3f}", "-t", f"{s['span']:.3f}", "-i", s.get("path") or str(FOOTAGE / f"{s['src']}.webm")]
            crop = "crop=iw:ih*0.76:0:0," if s.get("sub") else ""  # the documentary's burned-in subtitles sit below this
            vf = (f"{crop}scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},setpts=(PTS-STARTPTS)/{s['speed']},fps={FPS},"
                  f"eq=saturation=0.82:contrast=1.05:brightness=-0.02,colorbalance=rs=0.04:gs=0.01:bs=-0.04,"
                  f"tpad=stop_mode=clone:stop_duration={d},"
                  f"drawbox=x=0:y={H - 210}:w={W}:h=210:color=0x121211@0.30:t=fill")
        elif s["kind"] in ("three", "hwthree"):
            inp = ["-i", str(TAKES / f"{s['key']}.mp4")]
            vf = f"trim=start=0.3,setpts=PTS-STARTPTS,fps={FPS},scale={W}:{H},tpad=stop_mode=clone:stop_duration={d}"
        elif s["kind"] == "screen":
            inp = ["-ss", f"{s['a_s']:.3f}", "-t", f"{s['span']:.3f}", "-i", str(TAKES / f"{s['take']}.mp4")]
            vf = (f"setpts=(PTS-STARTPTS)/{s['speed']},fps={FPS},scale={W}:{H},tpad=stop_mode=clone:stop_duration={d},"
                  # a soft dark band at the bottom keeps captions readable over light pages
                  f"drawbox=x=0:y={H - 210}:w={W}:h=210:color=0x121211@0.38:t=fill")
        else:
            if s.get("face"):
                f = s["face"]
                inp = ["-ss", f"{max(f['start'] - 0.3, 0):.3f}", "-t", f"{d:.3f}", "-i", f["src"]]
                vf = (f"scale={W}:-2:flags=lanczos,crop={W}:{H}:0:40,fps={FPS},"
                      f"eq=saturation=1.04:contrast=1.03,tpad=stop_mode=clone:stop_duration={d}")
            else:
                inp = ["-f", "lavfi", "-i", f"color=c=0x1C1C1A:s={W}x{H}:r={FPS}:d={d}"]
                vf = f"drawbox=x=160:y=200:w={W - 320}:h={H - 400}:color=0x5F5E58:t=3"
        vf += f",trim=duration={d},format=yuv420p,setsar=1"
        run(["ffmpeg", "-loglevel", "error", "-y", *inp, "-vf", vf, "-an", "-c:v", "libx264", "-preset", "veryfast" if PREVIEW else "medium",
             "-crf", crf, "-r", str(FPS), str(out)])
        parts.append(out)
    ass, srt = build_ass(segs, placements, total)
    (B / "film.ass").write_text(ass)
    inputs = []
    for p_ in parts:
        inputs += ["-i", str(p_)]
    n = len(parts)
    music = HOME / "music" / "theme.wav"
    final = HOME / (("NadiSaathi-hardware" if HARDWARE else "NadiSaathi") + ("-preview" if PREVIEW else "") + ".mp4")
    fc = ("".join(f"[{i}:v]" for i in range(n)) + f"concat=n={n}:v=1:a=0,setpts=N/{FPS}/TB,"
          f"fade=t=in:st=0:d=0.8,fade=t=out:st={total - 1.2:.2f}:d=1.2,"
          f"subtitles='{B / 'film.ass'}':fontsdir='{FONTS}'[v];"
          f"[{n}:a]aresample={SR},pan=stereo|c0=c0|c1=c0,asplit=2[vo][key];"
          f"[{n + 2}:a]aresample={SR},volume=0.3,equalizer=f=2500:t=q:w=1.2:g=-5[mu];"
          f"[mu][key]sidechaincompress=threshold=0.02:ratio=8:attack=150:release=900:makeup=1[duck];"
          f"[{n + 1}:a]aresample={SR},pan=stereo|c0=c0|c1=c0[fx];"
          f"[vo][duck][fx]amix=inputs=3:normalize=0,alimiter=limit=0.7,loudnorm=I=-14:TP=-2:LRA=11[a]")
    run(["ffmpeg", "-loglevel", "error", "-stats", "-y", *inputs, "-i", str(B / "voice.wav"), "-i", str(B / "fx.wav"), "-i", str(music),
         "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}",
         "-c:v", "libx264", "-preset", "veryfast" if PREVIEW else "slow", "-crf", "26" if PREVIEW else "17", "-tune", "film",
         "-c:a", "aac", "-b:a", "192k", "-ar", str(SR), "-movflags", "+faststart", str(final)])
    write_srt(srt, final.with_suffix(".srt"))
    if not PREVIEW:
        run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(final), "-vf", "scale=1280:720", "-c:v", "libx264", "-crf", "28",
             "-preset", "medium", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(final.with_name(final.stem + "-720p.mp4"))])
    print(f"film: {final} ({total:.1f} s, {n} segments)")
    for s in segs:
        print(f"  {s['start']:6.1f}  {s['dur']:5.1f}s  {s['name']:<12} {s['kind']:<6} speed {s.get('speed', 1):.2f}" + ("  [face placeholder]" if s["kind"] == "face" and not s.get("face") else ""))


if __name__ == "__main__":
    main()
