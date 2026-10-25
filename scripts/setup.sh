#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required" >&2
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg is required (used by scripts/fetch_demo_assets.py to extract reference frames)." >&2
  echo "  Debian/Ubuntu: sudo apt-get install -y ffmpeg" >&2
  echo "  macOS:         brew install ffmpeg" >&2
  exit 1
fi

cd "$BACKEND_DIR"
if [[ ! -d .venv ]]; then
  uv venv
fi
source .venv/bin/activate
uv pip install -e .[dev]

cd "$ROOT_DIR"
python3 scripts/fetch_demo_assets.py

cd "$BACKEND_DIR"
PYTHONPATH=src python -m jalrekha.scripts.seed

cd "$FRONTEND_DIR"
npm install --legacy-peer-deps

echo "Setup complete."
