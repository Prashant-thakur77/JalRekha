"""Fail if the AWS account id is readable in any AWS take: OCR one frame every 0.5 s of every aws_*.mp4.

    ~/Videos/jalrekha/.venv-ocr/bin/python video/check_private.py [takes...]

Matches the id with or without dashes and tolerates OCR spacing. Prints the take and second of every hit.
"""

from __future__ import annotations

import glob
import os
import re
import subprocess
import sys
import tempfile

from rapidocr_onnxruntime import RapidOCR

TAKES = os.path.expanduser("~/Videos/jalrekha/takes")


def main(names: list[str]) -> int:
    acct = subprocess.run(["aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"],
                          check=True, capture_output=True, text=True).stdout.strip()
    pat = re.compile(r"[\s-]*".join(acct))
    ocr = RapidOCR()
    files = [f"{TAKES}/{n}.mp4" for n in names] if names else sorted(glob.glob(f"{TAKES}/aws_*.mp4"))
    hits = 0
    for f in files:
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["ffmpeg", "-loglevel", "error", "-i", f, "-vf", "fps=2", f"{d}/%05d.png"], check=True)
            for png in sorted(glob.glob(f"{d}/*.png")):
                res, _ = ocr(png)
                text = " ".join(r[1] for r in (res or []))
                if pat.search(text.replace("O", "0").replace("o", "0")):
                    hits += 1
                    print(f"LEAK {os.path.basename(f)} at {(int(os.path.basename(png)[:5]) - 1) / 2:.1f}s")
        print(f"checked {os.path.basename(f)}", flush=True)
    print("account id leaks:", hits)
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
