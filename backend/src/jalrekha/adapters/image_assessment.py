"""Image assessment adapter interface + Gemma multimodal implementation.

The adapter is *explanatory* only: it never overrides the CV-based
severity_score. Judges can rely on the deterministic pipeline while the
multimodal Gemma path adds Spanish descriptions for demo/evidence use.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx
from PIL import Image, ImageOps

from jalrekha.core.settings import get_settings


@dataclass
class ImageAssessmentResult:
    description_es: str
    water_visible: bool
    infrastructure_at_risk: bool
    confidence: float
    raw_model_output: str
    model_name: str


class ImageAssessmentAdapter(Protocol):
    def assess(self, image_path: str | Path) -> ImageAssessmentResult | None: ...


FEW_SHOT_SYSTEM = (
    "Sos un analista visual del sistema JalRekha. Ante un frame de "
    "camara fija o foto de voluntario sobre una escena hidrica, devolves un JSON "
    "con claves: description_es (1 a 2 oraciones en espanol rioplatense), "
    "water_visible (true/false), infrastructure_at_risk (true/false), "
    "confidence (0.0 a 1.0). No agregues texto fuera del JSON."
)

FEW_SHOT_EXAMPLES = [
    (
        "Ejemplo 1 (rio en calma, puente intacto):",
        {
            "description_es": "Se ve un rio en calma con el puente completamente seco y la ruta transitable.",
            "water_visible": True,
            "infrastructure_at_risk": False,
            "confidence": 0.9,
        },
    ),
    (
        "Ejemplo 2 (agua sobre el puente):",
        {
            "description_es": "El agua cubre parcialmente el tablero del puente; la baranda queda a medio tapar.",
            "water_visible": True,
            "infrastructure_at_risk": True,
            "confidence": 0.85,
        },
    ),
    (
        "Ejemplo 3 (frame ruidoso nocturno):",
        {
            "description_es": "Imagen de baja luz con reflejos; se intuye linea de agua pero sin certeza sobre la cota.",
            "water_visible": True,
            "infrastructure_at_risk": False,
            "confidence": 0.45,
        },
    ),
]


def _build_user_prompt() -> str:
    parts = ["Analiza el siguiente frame y respondeme en el formato JSON pedido."]
    for caption, example in FEW_SHOT_EXAMPLES:
        parts.append(f"{caption} {json.dumps(example, ensure_ascii=True)}")
    parts.append("Ahora analiza el frame nuevo. Devuelve solo el JSON, sin markdown.")
    return "\n".join(parts)


def _encode_image(path: Path, *, max_side: int, jpeg_quality: int = 82) -> str:
    try:
        from io import BytesIO

        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            if max_side > 0:
                image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            buffer = BytesIO()
            image.save(buffer, format="JPEG", quality=jpeg_quality, optimize=True)
            return base64.b64encode(buffer.getvalue()).decode("ascii")
    except Exception:
        return base64.b64encode(path.read_bytes()).decode("ascii")


def _parse_json_block(text: str) -> dict | None:
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


class GemmaImageAssessmentAdapter:
    """Calls Gemma through Ollama's `/api/chat` with one optimized image."""

    def __init__(self, runtime: object | None = None, *, force_embedded: bool = False) -> None:
        self.settings = get_settings()
        self.runtime = runtime
        self.force_embedded = force_embedded

    @property
    def model_name(self) -> str:
        if self.runtime is not None and self.force_embedded:
            return str(getattr(self.runtime, "model_name", self.settings.node_multimodal_model))
        return self.settings.node_multimodal_model

    def assess(self, image_path: str | Path) -> ImageAssessmentResult | None:
        path = Path(image_path)
        if not path.exists():
            return None

        if self.runtime is not None and self.force_embedded:
            return self._assess_embedded(path)

        if not self.settings.llm_enabled:
            return None
        multimodal_allowed = (
            self.settings.node_multimodal_verifier_enabled
            or self.settings.node_multimodal_enabled
            or self.settings.volunteer_image_enabled
        )
        if not multimodal_allowed:
            return None

        encoded = _encode_image(path, max_side=self.settings.node_multimodal_image_max_side)
        primary = self.settings.node_multimodal_model
        fallback = "gemma4:e2b" if primary != "gemma4:e2b" else None

        result = self._call_model(primary, encoded)
        if result is None and fallback:
            result = self._call_model(fallback, encoded)
        return result

    def _assess_embedded(self, path: Path) -> ImageAssessmentResult | None:
        if self.runtime is None:
            return None
        payload = self.runtime.generate_multimodal_json(
            FEW_SHOT_SYSTEM,
            _build_user_prompt(),
            [path],
            max_tokens=256,
        )
        if not isinstance(payload, dict):
            return None
        description = str(payload.get("description_es", "")).strip()
        if not description:
            return None
        try:
            confidence = float(payload.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        return ImageAssessmentResult(
            description_es=description,
            water_visible=bool(payload.get("water_visible", False)),
            infrastructure_at_risk=bool(payload.get("infrastructure_at_risk", False)),
            confidence=max(0.0, min(1.0, confidence)),
            raw_model_output=json.dumps(payload, ensure_ascii=True),
            model_name=self.model_name,
        )

    def _ollama_chat_url(self) -> str:
        return self.settings.node_multimodal_base_url.rstrip("/").removesuffix("/v1") + "/api/chat"

    def _call_model(self, model_name: str, encoded_image: str) -> ImageAssessmentResult | None:
        payload = {
            "model": model_name,
            "stream": False,
            "format": "json",
            # Gemma 4 routes output into message.thinking by default; disable so
            # message.content holds the JSON we asked for (same workaround used
            # in adapters/llm.py).
            "think": False,
            "messages": [
                {"role": "system", "content": FEW_SHOT_SYSTEM},
                {
                    "role": "user",
                    "content": _build_user_prompt(),
                    "images": [encoded_image],
                },
            ],
            "options": {
                "temperature": 0.1,
                "num_ctx": self.settings.node_multimodal_num_ctx,
                "num_predict": self.settings.node_multimodal_num_predict,
            },
        }
        try:
            with httpx.Client(timeout=self.settings.node_multimodal_timeout_seconds) as client:
                response = client.post(self._ollama_chat_url(), json=payload)
                response.raise_for_status()
            body = response.json()
            content = body.get("message", {}).get("content", "")
        except Exception:
            return None

        raw = str(content)
        parsed = _parse_json_block(raw)
        if not isinstance(parsed, dict):
            return None

        description = str(parsed.get("description_es", "")).strip()
        if not description:
            return None
        try:
            confidence = float(parsed.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        return ImageAssessmentResult(
            description_es=description,
            water_visible=bool(parsed.get("water_visible", False)),
            infrastructure_at_risk=bool(parsed.get("infrastructure_at_risk", False)),
            confidence=max(0.0, min(1.0, confidence)),
            raw_model_output=raw,
            model_name=model_name,
        )
