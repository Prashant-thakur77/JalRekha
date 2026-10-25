from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


BACKEND_SRC = Path(__file__).resolve().parents[1] / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

# Tests never touch backend/data: every run gets its own data dir (DBs, uploads).
os.environ.setdefault("JALREKHA_DATA_DIR", tempfile.mkdtemp(prefix="jalrekha-test-"))
# No cloud calls from tests, even when AWS credentials exist on the machine.
os.environ["NADISAATHI_AWS_ENABLED"] = "0"
os.environ.setdefault("NADISAATHI_TTS_ENABLED", "0")
# No Claude calls from the default test run (tests/test_claude_live.py opts in explicitly).
os.environ["NADISAATHI_CLAUDE_ENABLED"] = "0"
