from __future__ import annotations

import anyio
from fastapi import BackgroundTasks
from sqlmodel import Session

from jalrekha.api.routers.alerts import get_alert
from jalrekha.api.routers.volunteer import create_report
from jalrekha.db.database import edge_engine
from jalrekha.services.reasoning import (
    deserialize_chain,
    generate_alert_reasoning,
    serialize_chain,
)


def test_reasoning_green_skips_llm():
    block = generate_alert_reasoning(
        level="green",
        fused_score=0.0,
        node_obs=None,
        volunteer_parsed=None,
        hydromet=None,
        rules_fired=[],
        llm=object(),
    )
    assert block.model_name == "rule-skip-green"
    assert "verde" in block.llm_summary.lower()


def test_reasoning_fallback_when_llm_none():
    block = generate_alert_reasoning(
        level="red",
        fused_score=0.9,
        node_obs={"waterline_ratio": 0.8, "rise_velocity": 0.3, "crossed_critical_line": True, "confidence": 0.9},
        volunteer_parsed=None,
        hydromet=None,
        rules_fired=["node=0.80", "crossed_critical_line"],
    )
    assert block.model_name == "rule-fallback"
    assert "crossed_critical_line" in block.llm_summary or "node=0.80" in block.llm_summary


def test_reasoning_fallback_when_llm_returns_none(monkeypatch):
    class FakeLLM:
        class _s:
            llm_model = "gemma4:e2b"
        settings = _s()
        def generate_text(self, *a, **k):
            return None
    block = generate_alert_reasoning(
        level="orange",
        fused_score=0.7,
        node_obs=None,
        volunteer_parsed={"water_level_category": "high", "trend": "rising", "road_status": "blocked", "bridge_status": "unknown", "urgency": "high", "summary": "x"},
        hydromet=None,
        rules_fired=["volunteer=0.70"],
        llm=FakeLLM(),
    )
    assert block.model_name == "rule-fallback"


def test_reasoning_uses_llm_output():
    class FakeLLM:
        class _s:
            llm_model = "gemma4:e2b"
        settings = _s()
        def generate_text(self, *a, **k):
            return "El nivel es rojo porque waterline_ratio=0.80 y crossed_critical_line=True.\nCadena: ver ratio -> confirmar cruce -> escalar"
    block = generate_alert_reasoning(
        level="red",
        fused_score=0.9,
        node_obs={"waterline_ratio": 0.8, "rise_velocity": 0.3, "crossed_critical_line": True, "confidence": 0.9},
        volunteer_parsed=None,
        hydromet=None,
        rules_fired=["node=0.80"],
        llm=FakeLLM(),
    )
    assert block.model_name == "gemma4:e2b"
    assert "waterline_ratio" in block.llm_summary
    assert len(block.llm_chain_of_thought) == 3


def test_reasoning_uses_runtime_model_name_property():
    class FakeRuntime:
        model_name = "gemma-4-E2B-it.litertlm"

        def generate_text(self, *a, **k):
            return "Se emite amarillo por waterline_ratio=0.52 y trend=rising.\nCadena: mirar ratio -> confirmar tendencia -> escalar"

    block = generate_alert_reasoning(
        level="yellow",
        fused_score=0.52,
        node_obs={"waterline_ratio": 0.52, "rise_velocity": 0.08, "crossed_critical_line": False, "confidence": 0.76},
        volunteer_parsed={"water_level_category": "medium", "trend": "rising", "road_status": "caution", "bridge_status": "unknown", "urgency": "normal", "summary": "x"},
        hydromet=None,
        rules_fired=["node=0.52", "volunteer=0.50"],
        llm=FakeRuntime(),
    )
    assert block.model_name == "gemma-4-E2B-it.litertlm"
    assert len(block.llm_chain_of_thought) == 3


def test_chain_roundtrip():
    chain = ["uno", "dos", "tres"]
    assert deserialize_chain(serialize_chain(chain)) == chain
    assert deserialize_chain(None) == []
    assert deserialize_chain("not-json") == []


def test_alert_persists_reasoning_fields():
    async def run():
        with Session(edge_engine) as s:
            payload = await create_report(
                background_tasks=BackgroundTasks(),
                site_id="test-site",
                reporter_name="t",
                reporter_role="t",
                transcript_text="paso la marca critica y cortamos la ruta",
                offline_created=False,
                photo=None,
                audio=None,
                session=s,
            )
            alert_id = payload["alert"].id
        with Session(edge_engine) as s:
            response = await get_alert(alert_id=alert_id, session=s)
            return response

    response = anyio.run(run)
    assert response["reasoning_summary"]
    assert response["reasoning_model"] in {"rule-fallback", "rule-skip-green", "gemma4:e2b"} or response["reasoning_model"].startswith("gemma")
    assert isinstance(response["reasoning_chain_parsed"], list)
    assert isinstance(response["decision_trace_parsed"], list)
