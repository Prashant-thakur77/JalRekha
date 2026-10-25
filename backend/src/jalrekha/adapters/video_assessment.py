from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

_LOGGER = logging.getLogger(__name__)

from jalrekha.adapters.image_assessment import _encode_image
from jalrekha.adapters.litert_node import LiteRTNodeRuntime
from jalrekha.adapters.llm import OpenAICompatibleLLM
from jalrekha.core.settings import get_settings
from jalrekha.services.node_assessment import AssessmentVerdict, TemporalEvidencePack


SYSTEM_PROMPT = (
    "You are JalRekha Node, a multimodal flood assessment engine for fixed cameras. "
    "You receive one or more time-ordered images and an optional deterministic vector (deterministic_prefilter) "
    "computed by a PIL firewall with waterline_ratio, rise_velocity, water_level and crossed_critical_line. "
    "When an OpenCV gauge measurement (opencv_measurement) is present, its stage in metres is authoritative. "
    "Use these numbers as an anti-hallucination anchor, but confirm them visually before escalating. "
    "Reply ONLY with a JSON object with these exact keys: assessment_level (green|yellow|orange|red), "
    "assessment_score (0.0 to 1.0), temporal_summary (1 or 2 sentences), reasoning_summary (2 or 3 sentences), "
    "reasoning_steps (short list), critical_evidence (JSON object). critical_evidence must include, when possible, "
    "waterline_ratio (0.0 to 1.0), crossed_critical_line (true/false), rise_velocity (number), confidence (0.0 to 1.0), "
    "visual_cues (short list). No markdown, no extra text."
)


def _level_from_score(score: float) -> str:
    if score >= 0.82:
        return "red"
    if score >= 0.62:
        return "orange"
    if score >= 0.4:
        return "yellow"
    return "green"


def _parse_steps(raw: object) -> list[str]:
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()][:5]
    text = str(raw or "").strip()
    if not text:
        return []
    if "->" in text:
        return [piece.strip() for piece in text.split("->") if piece.strip()][:5]
    return [piece.strip() for piece in text.replace("\n", ". ").split(".") if piece.strip()][:5]


def _normalize_verdict_payload(
    payload: dict[str, Any],
    *,
    runner_name: str,
    runner_mode: str,
) -> AssessmentVerdict | None:
    try:
        score = float(payload.get("assessment_score"))
    except (TypeError, ValueError):
        return None

    score = max(0.0, min(1.0, score))
    level = str(payload.get("assessment_level", "")).strip().lower()
    level_aliases = {
        "low": "green",
        "medium": "yellow",
        "moderate": "yellow",
        "high": "orange",
        "critical": "red",
    }
    level = level_aliases.get(level, level)
    if level not in {"green", "yellow", "orange", "red"}:
        level = _level_from_score(score)

    temporal_summary = str(payload.get("temporal_summary", "")).strip()
    reasoning_summary = str(payload.get("reasoning_summary", "")).strip()
    if not temporal_summary or not reasoning_summary:
        return None

    reasoning_steps = _parse_steps(payload.get("reasoning_steps"))
    if not reasoning_steps:
        reasoning_steps = [f"score={score:.2f}", f"level={level}"]

    critical_evidence = payload.get("critical_evidence")
    if not isinstance(critical_evidence, dict):
        critical_evidence = {"raw": critical_evidence}

    return AssessmentVerdict(
        assessment_level=level,
        assessment_score=round(score, 4),
        temporal_summary=temporal_summary,
        reasoning_summary=reasoning_summary,
        reasoning_steps=reasoning_steps,
        critical_evidence=critical_evidence,
        runner_name=runner_name,
        runner_mode=runner_mode,
        fallback_used=False,
    )


class OllamaGemmaRunner:
    def __init__(self, llm: OpenAICompatibleLLM) -> None:
        self.llm = llm
        self.settings = getattr(llm, "settings", get_settings())

    def assess(self, pack: TemporalEvidencePack) -> AssessmentVerdict | None:
        if not self.settings.llm_enabled:
            return None

        if not self.settings.node_multimodal_enabled:
            return None
        return self._assess_multimodal(pack)

    def _assess_multimodal(self, pack: TemporalEvidencePack) -> AssessmentVerdict | None:
        encoded_images = []
        for frame in pack.selected_frames:
            path = Path(frame.frame_path)
            if not path.exists():
                continue
            encoded_images.append(_encode_image(path, max_side=self.settings.node_multimodal_image_max_side))

        if not encoded_images:
            return None

        payload = {
            "model": self.settings.node_multimodal_model,
            "stream": False,
            "format": "json",
            # Gemma 4 routes output into message.thinking by default; disable it
            # so the requested JSON lands in message.content.
            "think": False,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": self._build_user_prompt(pack),
                    "images": encoded_images,
                },
            ],
            "options": {
                "temperature": 0.1,
                "num_ctx": self.settings.node_multimodal_num_ctx,
                "num_predict": max(512, self.settings.node_multimodal_num_predict),
            },
        }
        try:
            with httpx.Client(timeout=self.settings.node_multimodal_timeout_seconds) as client:
                response = client.post(self._multimodal_ollama_chat_url(), json=payload)
                response.raise_for_status()
            body = response.json()
            message = body.get("message", {})
            content = message.get("content") or message.get("thinking") or ""
        except httpx.HTTPStatusError as exc:
            body_text = exc.response.text[:300] if exc.response is not None else ""
            _LOGGER.warning(
                "multimodal Ollama HTTP %s for model=%s url=%s body=%s",
                exc.response.status_code if exc.response is not None else "?",
                self.settings.node_multimodal_model,
                self._multimodal_ollama_chat_url(),
                body_text,
            )
            return None
        except Exception as exc:
            _LOGGER.warning(
                "multimodal Ollama call failed model=%s url=%s err=%r",
                self.settings.node_multimodal_model,
                self._multimodal_ollama_chat_url(),
                exc,
            )
            return None

        parsed = self.llm._extract_json(content)
        if not isinstance(parsed, dict):
            return None
        return _normalize_verdict_payload(
            parsed,
            runner_name=self.settings.node_multimodal_model,
            runner_mode="ollama-multimodal-temporal",
        )

    def _multimodal_ollama_chat_url(self) -> str:
        return self.settings.node_multimodal_base_url.rstrip("/").removesuffix("/v1") + "/api/chat"

    @staticmethod
    def _build_user_prompt(pack: TemporalEvidencePack) -> str:
        frame_lines = []
        for index, frame in enumerate(pack.selected_frames, start=1):
            frame_lines.append(
                " | ".join(
                    [
                        f"frame_{index}",
                        f"t={frame.timestamp_s:.1f}s",
                "visual_source=gemma4_image",
            ]
                )
            )
        return "\n".join(
            [
                f"Site: {pack.site_name} ({pack.site_region})",
                f"Source: {pack.source_type}",
                f"Frames analysed: {pack.frames_analyzed}",
                f"Metric summary: {json.dumps(pack.summary_metrics, ensure_ascii=True)}",
                "Curated frames in time order:",
                *frame_lines,
                (
                    "Decide the main risk by looking directly at the images. "
                    "If there is only one image, estimate the current state and mark low confidence for the temporal trend. "
                    "If there are several, compare the progression, waterline, reference structures, turbidity, obstructions and reflections."
                ),
            ]
        )


class LiteRTGemmaRunner:
    def __init__(self, runtime: LiteRTNodeRuntime) -> None:
        self.runtime = runtime
        self.settings = get_settings()

    def assess(self, pack: TemporalEvidencePack) -> AssessmentVerdict | None:
        if self.settings.node_provider != "litert":
            return None
        image_paths = [
            Path(frame.frame_path)
            for frame in pack.selected_frames
            if Path(frame.frame_path).exists()
        ]
        if not image_paths:
            return None
        user_prompt = OllamaGemmaRunner._build_user_prompt(pack)
        payload = None
        for _attempt in range(2):
            payload = self.runtime.generate_multimodal_json(
                SYSTEM_PROMPT,
                user_prompt,
                image_paths,
                max_tokens=min(512, self.settings.node_max_output_tokens),
            )
            if isinstance(payload, dict):
                break
        if not isinstance(payload, dict):
            return None
        return _normalize_verdict_payload(
            payload,
            runner_name=self.runtime.model_name,
            runner_mode="litert-multimodal-temporal",
        )
