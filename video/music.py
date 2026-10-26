"""NadiSaathi's own piano theme, composed here and rendered from a General MIDI SoundFont.

One instrument from start to end. Under the flood story it is sparse and minor (Dm Bb F C, one note a beat); from
"This is NadiSaathi" the same melody runs over warmer major chords (F C Dm Bb) with moving eighths; from the close it
thins out again and resolves on a long F under the end card. Timing follows build/timeline.json.

    ~/Videos/jalrekha/.venv-music/bin/python video/music.py  (a venv with tinysoundfont and numpy)   ->  ~/Videos/jalrekha/music/theme.wav
"""

from __future__ import annotations

import json
import os
import wave

import numpy as np
import tinysoundfont

SR = 48000
BPM = 76
BEAT = 60 / BPM
BAR = 4 * BEAT
HOME = os.path.expanduser("~/Videos/jalrekha")
SF2 = os.environ.get("NADI_SF2", os.path.expanduser("~/Videos/jalrekha/sf2/YDP-GrandPiano.sf2"))

Dm, Bb, F, C = (38, (62, 65, 69)), (34, (58, 62, 65)), (41, (60, 65, 69)), (36, (60, 64, 67))
NIGHT = [Dm, Bb, F, C]
DAY = [F, C, Dm, Bb]
# The theme: a falling line that lifts at the end of each phrase, like water settling and the warning arriving.
PHRASE_A = [[(0, 74, 2), (2, 72, 1), (3, 69, 1)], [(0, 67, 2), (2, 69, 2)], [(0, 65, 1.5), (1.5, 67, 0.5), (2, 69, 2)], [(0, 72, 3), (3, 74, 1)]]
PHRASE_B = [[(0, 77, 1.5), (1.5, 76, 0.5), (2, 74, 2)], [(0, 72, 2), (2, 74, 1), (3, 72, 1)], [(0, 69, 2), (2, 72, 2)], [(0, 72, 4)]]


def events(total: float, turn: float, close: float) -> list[tuple[float, int, float, int]]:
    out: list[tuple[float, int, float, int]] = []
    end_bar = int((total - 4) / BAR)
    turn_bar = max(1, round(turn / BAR))
    close_bar = int(close / BAR)
    for b in range(end_bar + 1):
        t0 = b * BAR
        day = b >= turn_bar
        last = b == end_bar
        quiet = b >= close_bar
        bass, triad = (F if last else DAY[(b - turn_bar) % 4]) if day else NIGHT[b % 4]
        soft = 34 if not day else (40 if quiet else 44)
        if last:
            out.append((t0, bass - 12, BAR * 2.4, soft + 8))
            for i, n in enumerate((bass, *triad, triad[0] + 12)):
                out.append((t0 + i * 0.22, n, BAR * 2.4, soft + 6))
            break
        if day and not quiet:
            pattern = [bass, bass + 7, triad[0], triad[1], triad[2], triad[1], triad[0], bass + 7]
        else:
            pattern = [bass, triad[1], bass + 7, triad[2]]
        step = BAR / len(pattern)
        for i, n in enumerate(pattern):
            out.append((t0 + i * step, n, step * (1.6 if len(pattern) == 8 else 2.4), soft + (6 if i % 8 == 0 else 0)))
        if b < 1:
            continue
        phrase = PHRASE_A if ((b - (turn_bar if day else 0)) // 4) % 2 == 0 else PHRASE_B
        if not day and (b // 4) % 2 == 1:
            out.append((t0, triad[2] + 12, BAR * 0.9, soft + 2))
            continue
        for off, n, beats in phrase[b % 4]:
            out.append((t0 + off * BEAT, n, beats * BEAT * 1.05, 54 if day else 42))
    return out


def render(evts, seconds):
    sf = tinysoundfont._tinysoundfont.SoundFont(SF2)
    sf.set_output(tinysoundfont._tinysoundfont.OutputMode.StereoInterleaved, SR, -6.0)
    sf.channel_set_preset_number(0, 0, 0)
    sched = sorted([(s, 1, n, v) for s, n, _, v in evts] + [(s + d, 0, n, 0) for s, n, d, _ in evts])
    total = int(seconds * SR)
    out = np.zeros((total, 2), dtype=np.float32)
    pos, i = 0, 0
    while pos < total:
        nxt = min(max(int(sched[i][0] * SR) if i < len(sched) else total, pos), total)
        if nxt > pos:
            buf = np.zeros((nxt - pos) * 2, dtype=np.float32)
            sf.render(memoryview(buf).cast("B"))
            out[pos:nxt] = buf.reshape(-1, 2)
            pos = nxt
        while i < len(sched) and int(sched[i][0] * SR) <= pos:
            _, on, n, v = sched[i]
            if on:
                sf.channel_note_on(0, n, v / 127)
            else:
                sf.channel_note_off(0, n)
            i += 1
        if i >= len(sched) and pos < total:
            buf = np.zeros((total - pos) * 2, dtype=np.float32)
            sf.render(memoryview(buf).cast("B"))
            out[pos:] = buf.reshape(-1, 2)
            pos = total
    return out


def reverb(dry, decay=2.4, wet=0.32):
    rng = np.random.default_rng(11)
    n = int(decay * SR)
    env = np.exp(-6.9 * np.arange(n) / n)
    out = np.empty_like(dry)
    size = 1 << int(np.ceil(np.log2(len(dry) + n)))
    for ch in range(2):
        ir = rng.standard_normal(n) * env
        ir[: int(0.012 * SR)] = 0
        ir /= np.sqrt((ir ** 2).sum())
        wet_ch = np.fft.irfft(np.fft.rfft(dry[:, ch], size) * np.fft.rfft(ir, size), size)[: len(dry)]
        out[:, ch] = (1 - wet) * dry[:, ch] + wet * wet_ch
    return out


def main() -> None:
    tl = json.load(open(f"{HOME}/build/timeline.json"))
    total, turn, close = tl["total"], tl["turn"], tl["close"]
    evts = events(total, turn, close)
    seconds = max(total, max(s + d for s, _, d, _ in evts) + 2)
    audio = reverb(render(evts, seconds))[: int(total * SR)]
    fade = int(3.0 * SR)
    audio[-fade:] *= np.linspace(1, 0, fade)[:, None]
    audio[: int(2 * SR)] *= np.linspace(0, 1, int(2 * SR))[:, None]
    audio *= 0.89 / max(1e-6, float(np.abs(audio).max()))
    os.makedirs(f"{HOME}/music", exist_ok=True)
    path = f"{HOME}/music/theme.wav"
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((audio * 32767).astype("<i2").tobytes())
    print(f"wrote {path}: {total:.1f} s, {len(evts)} notes, title at {turn:.1f} s, close at {close:.1f} s")


if __name__ == "__main__":
    main()
