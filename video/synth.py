"""The narration, voiced by Chatterbox in the reference voice (refs/narrator.wav): three takes per line, and the take
Whisper hears closest to the script is kept, trimmed, with inner pauses capped. Whisper's word times for every kept
line go to words.json for word-by-word captions.

    LD_LIBRARY_PATH=<nvidia libs> ~/.pyenv/versions/3.10.13/bin/python video/synth.py [line ids]

Writes ~/Videos/jalrekha/audio/lines/<id>.wav, lines.json and words.json. Takes are cached, so a rerun only voices
lines that changed.
"""

from __future__ import annotations

import contextlib
import difflib
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from narration import load  # noqa: E402

HOME = os.path.expanduser("~/Videos/jalrekha")
AUDIO = f"{HOME}/audio"
CACHE = f"{HOME}/cache/takes"
REF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "refs", "narrator.wav")
SEEDS = (11, 23, 37)
MORE = (41, 53, 67)
MAX_PAUSE = 0.35
NUM = {"0": "zero", "1": "one", "2": "two", "3": "three", "4": "four", "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine"}
SAME = {"nadisaathi": "nadi saathi", "opencv": "open c v", "usgs": "u s g s", "aws": "a w s", "mcp": "m c p", "s3": "s three",
        "json": "jason", "kleidicv": "klydee c v", "cm": "centimetres", "centimeters": "centimetres", "meters": "metres"}


def norm(text: str) -> list[str]:
    t = text.lower().replace("’", "'").replace("%", " percent").replace("-", " ")
    t = re.sub(r"[^a-z0-9' ]", " ", t)
    out: list[str] = []
    for w in t.split():
        out.extend(SAME.get(w, w).split())
    return out


def score(ref: str, heard: str) -> float:
    return difflib.SequenceMatcher(None, norm(ref), norm(heard)).ratio()


_tts = None
_asr = None


def tts():
    global _tts
    if _tts is None:
        import torch
        from chatterbox.tts import ChatterboxTTS

        with contextlib.redirect_stderr(io.StringIO()):
            _tts = ChatterboxTTS.from_pretrained(device="cuda" if torch.cuda.is_available() else "cpu")
    return _tts


def asr():
    global _asr
    if _asr is None:
        from faster_whisper import WhisperModel

        _asr = WhisperModel("small.en", device="cuda", compute_type="float16")
    return _asr


def take(text: str, seed: int, ex: float, cfg: float) -> str:
    import soundfile as sf
    import torch

    key = hashlib.sha1(json.dumps([text, seed, ex, cfg, 0.7, hashlib.sha1(open(REF, "rb").read()).hexdigest()]).encode()).hexdigest()[:16]
    path = f"{CACHE}/{key}.wav"
    if not os.path.exists(path):
        torch.manual_seed(seed)
        with contextlib.redirect_stderr(io.StringIO()):
            wav = tts().generate(text, audio_prompt_path=REF, exaggeration=ex, cfg_weight=cfg, temperature=0.7)
        sf.write(path, wav.squeeze(0).cpu().numpy(), tts().sr)
    return path


def heard(path: str) -> str:
    segs, _ = asr().transcribe(path, beam_size=5, language="en")
    return " ".join(s.text.strip() for s in segs)


def tighten(src: str, dst: str) -> None:
    af = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,"
          "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.12,areverse,"
          f"silenceremove=stop_periods=-1:stop_threshold=-40dB:stop_duration={MAX_PAUSE}:stop_silence={MAX_PAUSE}")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", src, "-af", af, "-ar", "48000", "-ac", "1", dst], check=True)


def duration(path: str) -> float:
    import soundfile as sf

    info = sf.info(path)
    return info.frames / info.samplerate


def main(only: set[str]) -> None:
    os.makedirs(CACHE, exist_ok=True)
    os.makedirs(f"{AUDIO}/lines", exist_ok=True)
    report_path = f"{AUDIO}/lines.json"
    report = json.load(open(report_path)) if os.path.exists(report_path) else {}
    asr_cache_path = f"{CACHE}/asr.json"
    asr_cache = json.load(open(asr_cache_path)) if os.path.exists(asr_cache_path) else {}
    for _scene, lid, caption, spoken, ex, cfg in load():
        if only and lid not in only:
            continue
        seeds = SEEDS + (MORE if only else ())
        scored = []
        for seed in seeds:
            path = take(spoken, seed, ex, cfg)
            name = os.path.basename(path)
            if name not in asr_cache:
                asr_cache[name] = heard(path)
                json.dump(asr_cache, open(asr_cache_path, "w"), indent=0)
            rate = len(spoken) / max(duration(path), 0.1)
            scored.append((score(caption, asr_cache[name]), -abs(rate - 15), path, asr_cache[name]))
        best = max(scored)
        out = f"{AUDIO}/lines/{lid}.wav"
        tighten(best[2], out)
        report[lid] = {"score": round(best[0], 3), "heard": best[3], "take": os.path.basename(best[2]), "s": round(duration(out), 2),
                       "all": sorted(round(s[0], 3) for s in scored)}
        print(f"{lid:4s} {report[lid]['s']:5.2f}s  score {best[0]:.2f}  | {best[3]}", flush=True)
    keep = {lid for _, lid, *_ in load()}
    report = {k: v for k, v in report.items() if k in keep}
    json.dump(report, open(report_path, "w"), indent=1)
    print("voice total:", round(sum(r["s"] for r in report.values()), 1), "s")
    words = {}
    for _scene, lid, *_ in load():
        p = f"{AUDIO}/lines/{lid}.wav"
        if not os.path.exists(p):
            continue
        segs, _ = asr().transcribe(p, beam_size=5, language="en", word_timestamps=True)
        words[lid] = [(w.word.strip(), round(w.start, 3), round(w.end, 3)) for s in segs for w in s.words]
    json.dump(words, open(f"{AUDIO}/words.json", "w"), indent=0)


if __name__ == "__main__":
    main({a for a in sys.argv[1:] if not a.startswith("-")})
