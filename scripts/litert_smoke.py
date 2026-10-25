from __future__ import annotations

import argparse
import json
import os
import time
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = PROJECT_ROOT / "backend" / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from jalrekha.adapters.litert_node import LiteRTNodeRuntime
from jalrekha.services.reasoning import generate_alert_reasoning


def _rss_mb() -> float | None:
    try:
        import resource
    except ImportError:
        return None
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return round(usage / (1024 * 1024), 1)
    return round(usage / 1024, 1)


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=True, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a LiteRT-LM smoke prompt for the JalRekha Node.")
    parser.add_argument(
        "--prompt",
        default="Responde solo JSON valido: {\"status\":\"ok\",\"engine\":\"litert\"}",
        help="Prompt to send to the model",
    )
    parser.add_argument(
        "--image",
        type=Path,
        default=None,
        help="Optional image path for a multimodal smoke prompt",
    )
    parser.add_argument(
        "--reasoning",
        action="store_true",
        help="Run the JalRekha Node alert reasoning path instead of the generic text prompt.",
    )
    parser.add_argument(
        "--engine-tokens",
        type=int,
        default=None,
        help="Override JALREKHA_NODE_MAX_OUTPUT_TOKENS before runtime initialization.",
    )
    parser.add_argument(
        "--multimodal-engine-tokens",
        type=int,
        default=None,
        help="Override JALREKHA_NODE_MULTIMODAL_MAX_OUTPUT_TOKENS before runtime initialization.",
    )
    args = parser.parse_args()

    if args.engine_tokens is not None:
        os.environ["JALREKHA_NODE_MAX_OUTPUT_TOKENS"] = str(args.engine_tokens)
    if args.multimodal_engine_tokens is not None:
        os.environ["JALREKHA_NODE_MULTIMODAL_MAX_OUTPUT_TOKENS"] = str(args.multimodal_engine_tokens)

    runtime = LiteRTNodeRuntime()
    health = runtime.health()
    _print_json({"health": health.__dict__})

    if not health.reachable:
        raise SystemExit("LiteRT runtime is not ready")

    started = time.monotonic()
    if args.image is not None:
        result = runtime.generate_multimodal_json(
            "Responde solo JSON valido.",
            args.prompt,
            [args.image],
        )
    elif args.reasoning:
        block = generate_alert_reasoning(
            level="red",
            fused_score=0.86,
            node_obs={
                "waterline_ratio": 0.83,
                "rise_velocity": 0.11,
                "crossed_critical_line": True,
                "confidence": 0.78,
            },
            volunteer_parsed=None,
            hydromet=None,
            rules_fired=["node_critical_line_crossed", "node_fast_rise"],
            llm=runtime,
        )
        result = block.__dict__
    else:
        result = runtime.generate_text(
            "Responde de forma breve.",
            args.prompt,
        )

    elapsed = round(time.monotonic() - started, 2)
    _print_json(
        {
            "result": result,
            "benchmark": {
                "elapsed_seconds": elapsed,
                "rss_mb": _rss_mb(),
                "engine_tokens": runtime.settings.node_max_output_tokens,
                "multimodal_engine_tokens": runtime.settings.node_multimodal_max_output_tokens,
                "backend": runtime.settings.node_backend,
                "multimodal_backend": runtime.settings.node_multimodal_backend,
                "multimodal_vision_backend": runtime.settings.node_multimodal_vision_backend,
                "model": runtime.model_name,
            },
        }
    )


if __name__ == "__main__":
    main()
