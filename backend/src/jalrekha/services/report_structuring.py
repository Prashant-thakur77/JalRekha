from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass

from jalrekha.adapters.llm import OpenAICompatibleLLM
from jalrekha.models.domain import Site


@dataclass
class StructuredReportResult:
    water_level_category: str
    trend: str
    road_status: str
    bridge_status: str
    homes_affected: bool
    urgency: str
    confidence: float
    summary: str
    severity_score: float
    parser_source: str
    decision_trace: list[str]


LOW_WORDS = ("bajo", "normal", "tranquilo")
MEDIUM_WORDS = ("medio", "moderado")
HIGH_WORDS = ("alto", "por encima", "muy cerca")
CRITICAL_WORDS = (
    "marca critica",
    "marca crítica",
    "paso la marca",
    "pasó la marca",
    "desbord",
    "tapa el puente",
    "inundable",
)
RISING_WORDS = ("subiendo", "sube", "creciendo", "aumentando", "subida")
FALLING_WORDS = ("bajando", "baja", "retrocede", "descendiendo")
BLOCKED_WORDS = ("cortado", "cortada", "intransitable", "bloqueado", "bloqueada", "no se puede pasar", "cerrado", "cerrada")
CAUTION_WORDS = ("complicado", "precaucion", "precaución", "difícil")
UNSAFE_BRIDGE_WORDS = ("puente peligroso", "puente inestable", "puente cerrado", "puente tapado")
HOMES_WORDS = ("vivienda", "casa", "hogar", "familia evacuada")



def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)



def _fallback_parse(transcript_text: str) -> StructuredReportResult:
    text = re.sub(r"\s+", " ", transcript_text.strip().lower())
    decision_trace: list[str] = []

    if _contains_any(text, CRITICAL_WORDS):
        water_level_category = "critical"
        severity_score = 0.92
        decision_trace.append("Transcript mentions critical threshold or overflow")
    elif _contains_any(text, HIGH_WORDS):
        water_level_category = "high"
        severity_score = 0.72
        decision_trace.append("Transcript indicates high water")
    elif _contains_any(text, MEDIUM_WORDS):
        water_level_category = "medium"
        severity_score = 0.48
        decision_trace.append("Transcript indicates medium water")
    elif _contains_any(text, LOW_WORDS):
        water_level_category = "low"
        severity_score = 0.2
        decision_trace.append("Transcript indicates low water")
    else:
        water_level_category = "unknown"
        severity_score = 0.35
        decision_trace.append("No direct water-level keyword found")

    if _contains_any(text, RISING_WORDS):
        trend = "rising"
        severity_score += 0.08
        decision_trace.append("Rising trend detected")
    elif _contains_any(text, FALLING_WORDS):
        trend = "falling"
        severity_score -= 0.05
        decision_trace.append("Falling trend detected")
    else:
        trend = "stable"

    if _contains_any(text, BLOCKED_WORDS):
        road_status = "blocked"
        severity_score += 0.08
        decision_trace.append("Transit blockage detected")
    elif _contains_any(text, CAUTION_WORDS):
        road_status = "caution"
        severity_score += 0.03
    else:
        road_status = "open"

    if _contains_any(text, UNSAFE_BRIDGE_WORDS):
        bridge_status = "unsafe"
        severity_score += 0.05
        decision_trace.append("Bridge risk detected")
    elif "puente" in text:
        bridge_status = "open"
    else:
        bridge_status = "unknown"

    homes_affected = _contains_any(text, HOMES_WORDS)
    if homes_affected:
        severity_score += 0.08
        decision_trace.append("Homes mentioned as affected")

    severity_score = max(0.0, min(1.0, severity_score))
    if severity_score >= 0.85:
        urgency = "critical"
    elif severity_score >= 0.65:
        urgency = "high"
    elif severity_score >= 0.4:
        urgency = "normal"
    else:
        urgency = "low"

    summary = (
        f"Volunteer report: water={water_level_category}, trend={trend}, "
        f"road={road_status}, bridge={bridge_status}"
    )
    return StructuredReportResult(
        water_level_category=water_level_category,
        trend=trend,
        road_status=road_status,
        bridge_status=bridge_status,
        homes_affected=homes_affected,
        urgency=urgency,
        confidence=0.62,
        summary=summary,
        severity_score=severity_score,
        parser_source="rules",
        decision_trace=decision_trace,
    )



def _normalize_llm_payload(payload: dict[str, object]) -> StructuredReportResult | None:
    required_fields = {
        "water_level_category",
        "trend",
        "road_status",
        "bridge_status",
        "homes_affected",
        "urgency",
        "summary",
        "confidence",
    }
    if not required_fields.issubset(payload):
        return None

    water_level_category = _normalize_category(str(payload["water_level_category"]).lower())
    trend = _normalize_trend(str(payload["trend"]).lower())
    road_status = _normalize_road_status(str(payload["road_status"]).lower())
    bridge_status = _normalize_bridge_status(str(payload["bridge_status"]).lower())
    homes_affected = _normalize_bool(payload["homes_affected"])
    urgency = _normalize_urgency(str(payload["urgency"]).lower())
    summary = str(payload["summary"]).strip()
    confidence = _normalize_confidence(payload["confidence"])

    base = {
        "low": 0.2,
        "medium": 0.45,
        "high": 0.7,
        "critical": 0.92,
        "unknown": 0.35,
    }.get(water_level_category, 0.35)
    if trend == "rising":
        base += 0.08
    if road_status == "blocked":
        base += 0.08
    if bridge_status in {"unsafe", "closed"}:
        base += 0.05
    if homes_affected:
        base += 0.08

    return StructuredReportResult(
        water_level_category=water_level_category,
        trend=trend,
        road_status=road_status,
        bridge_status=bridge_status,
        homes_affected=homes_affected,
        urgency=urgency,
        confidence=max(0.0, min(1.0, confidence)),
        summary=summary,
        severity_score=max(0.0, min(1.0, base)),
        parser_source="llm",
        decision_trace=["Structured with local Gemma-compatible endpoint"],
    )


def _normalize_category(value: str) -> str:
    if value in {"critical", "critico", "critica"}:
        return "critical"
    if value in {"high", "alto", "elevated"}:
        return "high"
    if value in {"medium", "moderate", "medio", "moderado"}:
        return "medium"
    if value in {"low", "bajo", "normal"}:
        return "low"
    return "unknown"


def _normalize_trend(value: str) -> str:
    if value in {"rising", "up", "subiendo", "creciendo"}:
        return "rising"
    if value in {"falling", "down", "bajando", "retrocediendo"}:
        return "falling"
    if value in {"stable", "steady", "estable"}:
        return "stable"
    return "unknown"


def _normalize_road_status(value: str) -> str:
    if value in {"blocked", "closed", "impassable", "intransitable", "bloqueado", "cerrado"}:
        return "blocked"
    if value in {"caution", "impaired", "limited", "precaution", "precaucion", "precaución"}:
        return "caution"
    if value in {"open", "clear", "transitable", "abierto"}:
        return "open"
    return "unknown"


def _normalize_bridge_status(value: str) -> str:
    if value in {"unsafe", "compromised", "damaged", "inestable", "peligroso"}:
        return "unsafe"
    if value in {"closed", "cerrado"}:
        return "closed"
    if value in {"open", "clear", "abierto"}:
        return "open"
    return "unknown"


def _normalize_urgency(value: str) -> str:
    if value in {"critical", "critico", "critica"}:
        return "critical"
    if value in {"high", "alta", "alto"}:
        return "high"
    if value in {"normal", "medium", "moderate"}:
        return "normal"
    if value in {"low", "baja", "bajo"}:
        return "low"
    return "normal"


def _normalize_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    return text in {"true", "yes", "y", "si", "sí", "affected", "1"}


def _normalize_confidence(value: object) -> float:
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    text = str(value).strip().lower()
    if text in {"high", "alta", "alto"}:
        return 0.85
    if text in {"medium", "moderate", "normal", "media"}:
        return 0.65
    if text in {"low", "baja", "bajo"}:
        return 0.4
    try:
        return max(0.0, min(1.0, float(text)))
    except ValueError:
        return 0.7



def structure_report(transcript_text: str, site: Site | None, llm: OpenAICompatibleLLM | None = None) -> StructuredReportResult:
    fallback = _fallback_parse(transcript_text)
    if llm is None or site is None:
        return fallback

    site_context = {
        "site_id": site.id,
        "site_name": site.name,
        "region": site.region,
    }
    llm_payload = llm.structure_observation(transcript_text, site_context)
    llm_result = _normalize_llm_payload(llm_payload) if llm_payload else None
    if llm_result is None:
        return fallback

    if llm_result.water_level_category == "unknown":
        llm_result.water_level_category = fallback.water_level_category
    if llm_result.trend == "unknown":
        llm_result.trend = fallback.trend
    if llm_result.road_status == "unknown":
        llm_result.road_status = fallback.road_status
    if llm_result.bridge_status == "unknown":
        llm_result.bridge_status = fallback.bridge_status
    if not llm_result.homes_affected and fallback.homes_affected:
        llm_result.homes_affected = True
    if _urgency_rank(llm_result.urgency) < _urgency_rank(fallback.urgency):
        llm_result.urgency = fallback.urgency
    llm_result.severity_score = max(llm_result.severity_score, fallback.severity_score)
    llm_result.decision_trace.extend(fallback.decision_trace[:2])
    if not llm_result.summary:
        llm_result.summary = fallback.summary
    return llm_result



def structured_result_to_json(result: StructuredReportResult) -> str:
    return json.dumps(asdict(result), ensure_ascii=True)


def _urgency_rank(value: str) -> int:
    return {
        "low": 0,
        "normal": 1,
        "high": 2,
        "critical": 3,
    }.get(value, 1)
