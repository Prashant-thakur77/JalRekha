from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = PROJECT_ROOT / "backend" / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from jalrekha.adapters.litert_node import LiteRTNodeRuntime  # noqa: E402
from jalrekha.services.reasoning import generate_alert_reasoning  # noqa: E402


TOKEN_COUNT_DETAIL = (
    "not exposed by the current LiteRTNodeRuntime/litert_lm response path; "
    "the script does not estimate tokens from text"
)
TTFT_DETAIL = (
    "not measured: the current LiteRTNodeRuntime call returns only a final response "
    "and exposes no streaming callback or first-token event"
)


def _rss_mb() -> float | None:
    try:
        import resource
    except ImportError:
        return None
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return round(usage / (1024 * 1024), 1)
    return round(usage / 1024, 1)


def _json_default(value: Any) -> Any:
    if hasattr(value, "__dict__"):
        return value.__dict__
    return str(value)


def _settings_fields(runtime: LiteRTNodeRuntime | None, mode: str) -> dict[str, Any]:
    if runtime is None:
        return {
            "model": None,
            "model_path": None,
            "backend": None,
            "multimodal_backend": None,
            "vision_backend": None,
            "speculative_decoding_enabled": None,
            "engine_max_output_tokens": None,
        }
    settings = runtime.settings
    return {
        "model": runtime.model_name,
        "model_path": str(settings.node_model_path),
        "backend": settings.node_backend,
        "multimodal_backend": settings.node_multimodal_backend,
        "vision_backend": settings.node_multimodal_vision_backend,
        "speculative_decoding_enabled": settings.node_enable_speculative_decoding,
        "engine_max_output_tokens": (
            settings.node_multimodal_max_output_tokens
            if mode == "image"
            else settings.node_max_output_tokens
        ),
    }


def _base_record(
    *,
    runtime: LiteRTNodeRuntime | None,
    mode: str,
    run_index: int,
    run_temperature: str,
) -> dict[str, Any]:
    return {
        "record_type": "litert_benchmark_run",
        "schema_version": 1,
        "created_at_unix": round(time.time(), 3),
        "hardware": "Raspberry Pi 5 8GB",
        "mode": mode,
        "run_index": run_index,
        "run_temperature": run_temperature,
        "runtime_reuse_mode": None,
        **_settings_fields(runtime, mode),
        "wall_clock_elapsed_seconds": None,
        "rss_peak_mb": None,
        "rss_peak_detail": "process peak RSS from resource.getrusage(RUSAGE_SELF).ru_maxrss",
        "output_token_count": None,
        "token_count_detail": TOKEN_COUNT_DETAIL,
        "decode_tok_s": None,
        "decode_tok_s_detail": "not computed because output_token_count is unavailable",
        "ttft_seconds": None,
        "ttft_detail": TTFT_DETAIL,
        "pass": False,
        "error_detail": None,
        "runtime_error_type": None,
        "runtime_error_detail": None,
        "runtime_response_type": None,
        "runtime_response_preview": None,
        "output_preview": None,
    }


def _preview(value: Any) -> str | None:
    if value is None:
        return None
    text = json.dumps(value, ensure_ascii=True, default=_json_default) if not isinstance(value, str) else value
    return text[:500]


def _runtime_detail(runtime: LiteRTNodeRuntime, default_error: str) -> str:
    error_type = getattr(runtime, "last_error_type", None)
    error_detail = getattr(runtime, "last_error_detail", None)
    response_type = getattr(runtime, "last_response_type", None)
    response_preview = getattr(runtime, "last_response_preview", None)
    parts = [default_error]
    if error_type or error_detail:
        parts.append(f"runtime_error={error_type or 'unknown'}: {error_detail or ''}".strip())
    elif response_type or response_preview:
        parts.append(f"runtime_response={response_type or 'unknown'}: {response_preview or ''}".strip())
    return "; ".join(parts)


def _run_mode(runtime: LiteRTNodeRuntime, mode: str, prompt: str, image_path: Path | None) -> tuple[bool, Any, str | None]:
    if mode == "text":
        result = runtime.generate_text("Responde de forma breve.", prompt)
        return (
            result is not None,
            result,
            None if result is not None else _runtime_detail(runtime, "runtime returned no text"),
        )

    if mode == "reasoning":
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
        passed = block.model_name != "rule-fallback"
        error = None if passed else _runtime_detail(
            runtime,
            "reasoning path fell back because LiteRT returned no usable text",
        )
        return passed, block.__dict__, error

    if mode == "image":
        if image_path is None:
            return False, None, "image mode requires --image"
        result = runtime.generate_multimodal_json(
            "Responde solo JSON valido.",
            prompt,
            [image_path],
        )
        return (
            result is not None,
            result,
            None if result is not None else _runtime_detail(runtime, "runtime returned no multimodal JSON"),
        )

    return False, None, f"unknown mode: {mode}"


def run_benchmark_modes(
    modes: Iterable[str],
    *,
    repeats: int = 2,
    prompt: str = 'Responde solo JSON valido: {"status":"ok","engine":"litert"}',
    image_path: Path | None = None,
    fresh_runtime_per_run: bool = False,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for mode in modes:
        if mode == "image" and image_path is not None and not image_path.exists():
            record = _base_record(runtime=None, mode=mode, run_index=1, run_temperature="cold")
            record["error_detail"] = f"image path does not exist: {image_path}"
            records.append(record)
            continue

        runtime = None if fresh_runtime_per_run else LiteRTNodeRuntime()
        if runtime is not None:
            health = runtime.health()
            if not health.reachable:
                record = _base_record(runtime=runtime, mode=mode, run_index=1, run_temperature="cold")
                record["runtime_reuse_mode"] = "shared"
                record["error_detail"] = f"LiteRT runtime is not ready: {health.detail}"
                records.append(record)
                continue

        for index in range(1, max(1, repeats) + 1):
            run_runtime = LiteRTNodeRuntime() if fresh_runtime_per_run else runtime
            if run_runtime is None:
                raise RuntimeError("benchmark runtime was not initialized")
            run_temperature = "cold" if index == 1 or fresh_runtime_per_run else "warm"
            if fresh_runtime_per_run:
                health = run_runtime.health()
                if not health.reachable:
                    record = _base_record(
                        runtime=run_runtime,
                        mode=mode,
                        run_index=index,
                        run_temperature=run_temperature,
                    )
                    record["runtime_reuse_mode"] = "fresh-per-run"
                    record["error_detail"] = f"LiteRT runtime is not ready: {health.detail}"
                    records.append(record)
                    continue
            record = _base_record(
                runtime=run_runtime,
                mode=mode,
                run_index=index,
                run_temperature=run_temperature,
            )
            record["runtime_reuse_mode"] = "fresh-per-run" if fresh_runtime_per_run else "shared"
            started = time.monotonic()
            try:
                passed, result, error = _run_mode(run_runtime, mode, prompt, image_path)
            except Exception as exc:
                passed, result, error = False, None, f"{type(exc).__name__}: {exc}"
            record["wall_clock_elapsed_seconds"] = round(time.monotonic() - started, 3)
            record["rss_peak_mb"] = _rss_mb()
            record["pass"] = passed
            record["error_detail"] = error
            record["runtime_error_type"] = getattr(run_runtime, "last_error_type", None)
            record["runtime_error_detail"] = getattr(run_runtime, "last_error_detail", None)
            record["runtime_response_type"] = getattr(run_runtime, "last_response_type", None)
            record["runtime_response_preview"] = getattr(run_runtime, "last_response_preview", None)
            record["output_preview"] = _preview(result)
            records.append(record)
    return records


def _write_records(records: list[dict[str, Any]], output: Path | None, json_array: bool) -> None:
    lines: list[str]
    if json_array:
        text = json.dumps(records, ensure_ascii=True, default=_json_default, indent=2)
    else:
        lines = [json.dumps(record, ensure_ascii=True, default=_json_default) for record in records]
        text = "\n".join(lines) + "\n"
    if output is None:
        print(text, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run reproducible LiteRT-LM benchmark records for JalRekha Node.")
    parser.add_argument("--mode", choices=["text", "reasoning", "image"], action="append")
    parser.add_argument("--all", action="store_true", help="Run text, reasoning, and image modes.")
    parser.add_argument("--image", type=Path, default=None, help="Image path for image/multimodal mode.")
    parser.add_argument("--prompt", default='Responde solo JSON valido: {"status":"ok","engine":"litert"}')
    parser.add_argument("--repeats", type=int, default=2, help="Runs per mode; first is cold, later runs are warm.")
    parser.add_argument("--engine-tokens", type=int, default=None)
    parser.add_argument("--multimodal-engine-tokens", type=int, default=None)
    parser.add_argument("--model-path", type=Path, default=None, help="Override JALREKHA_NODE_MODEL_PATH for this run.")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSONL/JSON output file.")
    parser.add_argument("--json-array", action="store_true", help="Write one JSON array instead of JSONL.")
    parser.add_argument(
        "--fresh-runtime-per-run",
        action="store_true",
        help="Create a new LiteRTNodeRuntime for each repeat instead of reusing the engine.",
    )
    args = parser.parse_args()

    if args.engine_tokens is not None:
        os.environ["JALREKHA_NODE_MAX_OUTPUT_TOKENS"] = str(args.engine_tokens)
    if args.multimodal_engine_tokens is not None:
        os.environ["JALREKHA_NODE_MULTIMODAL_MAX_OUTPUT_TOKENS"] = str(args.multimodal_engine_tokens)
    if args.model_path is not None:
        os.environ["JALREKHA_NODE_MODEL_PATH"] = str(args.model_path)

    modes = ["text", "reasoning", "image"] if args.all else args.mode or ["text", "reasoning"]
    records = run_benchmark_modes(
        modes,
        repeats=args.repeats,
        prompt=args.prompt,
        image_path=args.image,
        fresh_runtime_per_run=args.fresh_runtime_per_run,
    )
    _write_records(records, args.output, args.json_array)


if __name__ == "__main__":
    main()
