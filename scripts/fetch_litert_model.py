from __future__ import annotations

import argparse
import os
import shutil
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL_URL = (
    "https://huggingface.co/litert-community/gemma-4-E2B-it-litert-lm/resolve/main/"
    "gemma-4-E2B-it.litertlm?download=true"
)
DEFAULT_MODEL_PATH = PROJECT_ROOT / "backend" / "data" / "models" / "gemma-4-E2B-it.litertlm"
CHUNK_SIZE = 1024 * 1024


def _resolve_target() -> Path:
    env_path = os.environ.get("JALREKHA_NODE_MODEL_PATH")
    return Path(env_path) if env_path else DEFAULT_MODEL_PATH


def download_model(target_path: Path, model_url: str, *, force: bool) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists() and target_path.stat().st_size > 0 and not force:
        print(f"LiteRT model already present: {target_path}")
        return

    tmp_path = target_path.with_suffix(target_path.suffix + ".part")
    if tmp_path.exists():
        tmp_path.unlink()

    print(f"Downloading LiteRT model to {target_path}")
    request = urllib.request.Request(
        model_url,
        headers={"User-Agent": "jalrekha-litert-fetch/1.0"},
    )
    with urllib.request.urlopen(request) as response, tmp_path.open("wb") as handle:
        shutil.copyfileobj(response, handle, length=CHUNK_SIZE)
    tmp_path.replace(target_path)
    print(f"Saved LiteRT model to {target_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download the LiteRT-LM model for the JalRekha Node.")
    parser.add_argument(
        "--target",
        type=Path,
        default=_resolve_target(),
        help="Target .litertlm file path",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_MODEL_URL,
        help="Model download URL",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if the file already exists",
    )
    args = parser.parse_args()
    download_model(args.target, args.url, force=args.force)


if __name__ == "__main__":
    main()
