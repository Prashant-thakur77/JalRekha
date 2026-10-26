"""Run the backend and frontend test suites and write their counts to eval/results/tests.json.

make_headline.py reads that file, so the test counts in README.md (badges and the
"Built and tested" section) come from a real run, not from a hand-typed number.

    python3 scripts/count_tests.py     # or: make count-tests
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "eval" / "results" / "tests.json"


def backend(tmp: Path) -> dict:
    xml = tmp / "pytest.xml"
    cmd = ["uv", "run", "pytest", "-q", "-p", "no:warnings", f"--junitxml={xml}"]
    subprocess.run(cmd, cwd=ROOT / "backend", check=False, stdout=subprocess.DEVNULL)
    cases = ET.parse(xml).getroot().iter("testcase")
    counts = {"passed": 0, "failed": 0, "xfailed": 0, "skipped": 0}
    files = set()
    for c in cases:
        files.add(c.get("classname", "").split(".")[1] if "." in c.get("classname", "") else c.get("classname", ""))
        if c.find("failure") is not None or c.find("error") is not None:
            counts["failed"] += 1
        elif (s := c.find("skipped")) is not None:
            counts["xfailed" if "xfail" in (s.get("type", "") + s.get("message", "")) else "skipped"] += 1
        else:
            counts["passed"] += 1
    return {"command": "cd backend && uv run pytest -q", "files": len(files), "collected": sum(counts.values()), **counts}


def frontend(tmp: Path) -> dict:
    out = tmp / "vitest.json"
    cmd = ["npm", "test", "--", "--reporter=json", f"--outputFile={out}"]
    subprocess.run(cmd, cwd=ROOT / "frontend", check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    d = json.loads(out.read_text())
    return {"command": "cd frontend && npm test", "files": len(d["testResults"]), "collected": d["numTotalTests"],
            "passed": d["numPassedTests"], "failed": d["numFailedTests"], "skipped": d.get("numPendingTests", 0) + d.get("numTodoTests", 0)}


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        b, f = backend(Path(t)), frontend(Path(t))
    res = {"meta": {"generated_by": "scripts/count_tests.py", "generated_at": datetime.now(timezone.utc).isoformat()},
           "backend": b, "frontend": f}
    OUT.write_text(json.dumps(res, indent=1) + "\n")
    print(f"backend {b['passed']} passed, {b['failed']} failed, {b['xfailed']} xfailed; frontend {f['passed']} passed, {f['failed']} failed -> {OUT.relative_to(ROOT)}")
    return 1 if b["failed"] or f["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
