"""Few-shot Gemma adapter for Rioplatense hydro transcripts.

Wraps OpenAICompatibleLLM with a tightly controlled 12-example few-shot prompt
covering regional phrases. Produces the same JSON shape that
`services.report_structuring._normalize_llm_payload` expects, so it is a
drop-in substitute for the default `structure_observation` call when the
backend detects the local Gemma runtime is reachable.
"""

from __future__ import annotations

import json
import os
from typing import Any

from typing import Protocol

from jalrekha.adapters.llm import OpenAICompatibleLLM


class _TextGenClient(Protocol):
    def generate_text(self, system_prompt: str, user_prompt: str, max_tokens: int = ...) -> str | None: ...


def _resolve_fewshot_count(total: int) -> int:
    """Number of few-shot examples to inline in the prompt.

    Defaults to all of them (max accuracy). On CPU-only dev machines, set
    JALREKHA_FEWSHOT_COUNT to a smaller number (e.g. 4) to keep prompt
    processing under a usable latency budget.
    """
    raw = os.environ.get("JALREKHA_FEWSHOT_COUNT")
    if not raw:
        return total
    try:
        n = int(raw)
    except ValueError:
        return total
    return max(1, min(n, total))


FEW_SHOT = [
    {
        "in": "El agua ya paso la marca critica y sigue subiendo rapido, cortamos la ruta.",
        "out": {
            "water_level_category": "critical",
            "trend": "rising",
            "road_status": "blocked",
            "bridge_status": "unknown",
            "homes_affected": False,
            "urgency": "critical",
            "summary": "Nivel critico y ruta cortada.",
            "confidence": 0.9,
        },
    },
    {
        "in": "Ya tapo la calle principal, hay gente subida a los techos, vengan ya.",
        "out": {
            "water_level_category": "critical",
            "trend": "rising",
            "road_status": "blocked",
            "bridge_status": "unknown",
            "homes_affected": True,
            "urgency": "critical",
            "summary": "Calle tapada y rescates necesarios.",
            "confidence": 0.92,
        },
    },
    {
        "in": "El riacho esta estable, nivel bajo, todo tranquilo.",
        "out": {
            "water_level_category": "low",
            "trend": "stable",
            "road_status": "open",
            "bridge_status": "open",
            "homes_affected": False,
            "urgency": "low",
            "summary": "Situacion normal.",
            "confidence": 0.88,
        },
    },
    {
        "in": "El puente esta tapado, el agua pasa por encima del tablero.",
        "out": {
            "water_level_category": "critical",
            "trend": "rising",
            "road_status": "blocked",
            "bridge_status": "unsafe",
            "homes_affected": False,
            "urgency": "critical",
            "summary": "Puente intransitable por crecida.",
            "confidence": 0.9,
        },
    },
    {
        "in": "Crece desde anoche, llega por las rodillas en la zona baja.",
        "out": {
            "water_level_category": "high",
            "trend": "rising",
            "road_status": "caution",
            "bridge_status": "unknown",
            "homes_affected": True,
            "urgency": "high",
            "summary": "Crecida sostenida en zona baja.",
            "confidence": 0.85,
        },
    },
    {
        "in": "Llovio toda la tarde pero el arroyo esta estable ahora.",
        "out": {
            "water_level_category": "medium",
            "trend": "stable",
            "road_status": "open",
            "bridge_status": "open",
            "homes_affected": False,
            "urgency": "normal",
            "summary": "Precipitacion sin impacto hidrologico.",
            "confidence": 0.82,
        },
    },
    {
        "in": "Baja despacio, se calmo la crecida, la ruta vuelve a estar transitable.",
        "out": {
            "water_level_category": "medium",
            "trend": "falling",
            "road_status": "open",
            "bridge_status": "open",
            "homes_affected": False,
            "urgency": "normal",
            "summary": "Descenso controlado.",
            "confidence": 0.84,
        },
    },
    {
        "in": "Entro agua en las casas de la costanera, familias evacuadas.",
        "out": {
            "water_level_category": "critical",
            "trend": "rising",
            "road_status": "blocked",
            "bridge_status": "unknown",
            "homes_affected": True,
            "urgency": "critical",
            "summary": "Viviendas inundadas, evacuacion en curso.",
            "confidence": 0.93,
        },
    },
    {
        "in": "El agua ya toca el puente, viene creciendo fuerte desde la madrugada.",
        "out": {
            "water_level_category": "high",
            "trend": "rising",
            "road_status": "caution",
            "bridge_status": "unsafe",
            "homes_affected": False,
            "urgency": "high",
            "summary": "Puente amenazado por crecida.",
            "confidence": 0.87,
        },
    },
    {
        "in": "Calle complicada, hay barro y agua, pasar con precaucion.",
        "out": {
            "water_level_category": "medium",
            "trend": "stable",
            "road_status": "caution",
            "bridge_status": "open",
            "homes_affected": False,
            "urgency": "normal",
            "summary": "Calle precaria, transito restringido.",
            "confidence": 0.8,
        },
    },
    {
        "in": "Rio retrocede, se ven de nuevo las piedras del cauce.",
        "out": {
            "water_level_category": "low",
            "trend": "falling",
            "road_status": "open",
            "bridge_status": "open",
            "homes_affected": False,
            "urgency": "low",
            "summary": "Cauce recuperando niveles normales.",
            "confidence": 0.86,
        },
    },
    {
        "in": "El puente inestable, mejor cerrarlo preventivamente.",
        "out": {
            "water_level_category": "high",
            "trend": "rising",
            "road_status": "caution",
            "bridge_status": "unsafe",
            "homes_affected": False,
            "urgency": "high",
            "summary": "Riesgo estructural preventivo.",
            "confidence": 0.83,
        },
    },
]


SYSTEM_PROMPT = (
    "Sos un parser de reportes de voluntarios en espanol rioplatense/litoral. "
    "Dado un transcript, devolves SOLO un JSON con: water_level_category "
    "(low|medium|high|critical|unknown), trend (rising|falling|stable|unknown), "
    "road_status (open|caution|blocked|unknown), bridge_status (open|unsafe|closed|unknown), "
    "homes_affected (true/false), urgency (low|normal|high|critical), "
    "summary (una oracion) y confidence (0.0 a 1.0). No markdown. No texto extra."
)


def _build_user_prompt(transcript: str, site_context: dict[str, Any]) -> str:
    parts = [f"Contexto del sitio: {json.dumps(site_context, ensure_ascii=True)}"]
    parts.append("Ejemplos:")
    count = _resolve_fewshot_count(len(FEW_SHOT))
    for ex in FEW_SHOT[:count]:
        parts.append(f"Transcript: {ex['in']}")
        parts.append(f"JSON: {json.dumps(ex['out'], ensure_ascii=True)}")
    parts.append(f"Transcript: {transcript}")
    parts.append("JSON:")
    return "\n".join(parts)


class GemmaFewShotTextStructurer:
    """Drop-in alternative to `OpenAICompatibleLLM.structure_observation` with
    a domain-tuned few-shot prompt for Litoral Spanish. Returns the same
    dict-or-None contract so the existing normalization path in
    `services.report_structuring` picks it up unchanged.
    """

    def __init__(self, llm: _TextGenClient | OpenAICompatibleLLM) -> None:
        self._llm = llm

    def structure_observation(self, transcript: str, site_context: dict[str, Any]) -> dict[str, Any] | None:
        if not transcript.strip():
            return None
        raw = self._llm.generate_text(
            SYSTEM_PROMPT,
            _build_user_prompt(transcript, site_context),
            max_tokens=220,
        )
        if not raw:
            return None
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end < start:
            return None
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return None
