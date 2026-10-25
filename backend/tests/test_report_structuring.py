from __future__ import annotations

from jalrekha.adapters.llm import OpenAICompatibleLLM
from jalrekha.models.domain import Site
from jalrekha.services.report_structuring import _normalize_llm_payload, structure_report


def test_normalize_llm_payload_accepts_ollama_style_values():
    payload = {
        "water_level_category": "Critical",
        "trend": "Rising",
        "road_status": "impassable",
        "bridge_status": "compromised",
        "homes_affected": "yes",
        "urgency": "High",
        "summary": "Water crossed the critical mark.",
        "confidence": "high",
    }

    result = _normalize_llm_payload(payload)

    assert result is not None
    assert result.parser_source == "llm"
    assert result.water_level_category == "critical"
    assert result.trend == "rising"
    assert result.road_status == "blocked"
    assert result.bridge_status == "unsafe"
    assert result.homes_affected is True
    assert result.urgency == "high"
    assert result.confidence == 0.85


def test_structure_report_uses_llm_payload_when_available():
    site = Site(id="test-site", name="Puente Test", region="Zona Demo", lat=0, lng=0)

    class StubLLM(OpenAICompatibleLLM):
        def __init__(self) -> None:
            pass

        def structure_observation(self, transcript_text: str, site_context: dict[str, object]):
            assert transcript_text
            assert site_context["site_id"] == "test-site"
            return {
                "water_level_category": "critical",
                "trend": "rising",
                "road_status": "impassable",
                "bridge_status": "compromised",
                "homes_affected": "no",
                "urgency": "high",
                "summary": "Water crossed the critical line.",
                "confidence": "high",
            }

    result = structure_report(
        "El agua cruzo la marca critica y trae barro",
        site=site,
        llm=StubLLM(),
    )

    assert result.parser_source == "llm"
    assert result.road_status == "blocked"
    assert result.bridge_status == "unsafe"
    assert result.summary == "Water crossed the critical line."


def test_structure_report_backfills_conservative_llm_fields_from_fallback():
    site = Site(id="test-site", name="Puente Test", region="Zona Demo", lat=0, lng=0)

    class StubLLM(OpenAICompatibleLLM):
        def __init__(self) -> None:
            pass

        def structure_observation(self, transcript_text: str, site_context: dict[str, object]):
            return {
                "water_level_category": "unknown",
                "trend": "unknown",
                "road_status": "unknown",
                "bridge_status": "unknown",
                "homes_affected": "no",
                "urgency": "normal",
                "summary": "Conservative reading.",
                "confidence": 0.8,
            }

    result = structure_report(
        "El agua paso la marca critica y la calle esta cortada",
        site=site,
        llm=StubLLM(),
    )

    assert result.parser_source == "llm"
    assert result.water_level_category == "critical"
    assert result.road_status == "blocked"
    assert result.urgency == "critical"
    assert result.confidence == 0.8
