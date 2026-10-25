"""Auditable thinking-mode chain for FusedAlert severity decisions.

Runs an English-language prompt through the local Gemma endpoint and produces a
ReasoningBlock that accompanies the deterministic decision_trace. Green alerts
skip the LLM (cost/latency). If Ollama is down, a rule-fallback summary is
generated so alert emission never blocks on model availability.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

from jalrekha.services.historical_context import HistoricalContextHit, render_historical_context, validate_context_citations

class TextGenerator(Protocol):
    def generate_text(self, system_prompt: str, user_prompt: str, max_tokens: int = 320) -> str | None: ...


@dataclass
class ReasoningBlock:
    llm_summary: str
    llm_chain_of_thought: list[str] = field(default_factory=list)
    model_name: str = "rule-fallback"


SYSTEM_PROMPT = (
    "You are Gemma running on the JalRekha Node. Respond in English. "
    "Use at most 35 words. Cite signals by name. "
    "Exact format: Summary: ... Chain: step1 -> step2. "
    "No markdown and no invented data."
)


def _render_inputs(
    node_obs: Optional[dict[str, Any]],
    volunteer_parsed: Optional[dict[str, Any]],
    hydromet: Optional[dict[str, Any]],
    fused_score: float,
    level: str,
    rules_fired: list[str],
    historical_context: str | None = None,
) -> str:
    parts: list[str] = []
    parts.append(f"level={level} score={fused_score:.2f}")
    if node_obs:
        parts.append(
            "node "
            f"waterline_ratio={node_obs.get('waterline_ratio', 0):.2f} "
            f"rise_velocity={node_obs.get('rise_velocity', 0):.2f} "
            f"crossed_critical_line={node_obs.get('crossed_critical_line', False)} "
            f"confidence={node_obs.get('confidence', 0):.2f}"
        )
    else:
        parts.append("node none")
    if volunteer_parsed:
        parts.append(
            "volunteer "
            f"water_level_category={volunteer_parsed.get('water_level_category', 'unknown')} "
            f"trend={volunteer_parsed.get('trend', 'unknown')} "
            f"road_status={volunteer_parsed.get('road_status', 'unknown')} "
            f"bridge_status={volunteer_parsed.get('bridge_status', 'unknown')} "
            f"urgency={volunteer_parsed.get('urgency', 'unknown')}"
        )
    if hydromet:
        parts.append(
            "hydromet "
            f"precipitation_mm={hydromet.get('precipitation_mm', 0):.1f} "
            f"river_discharge={hydromet.get('river_discharge', 'NA')} "
            f"river_discharge_trend={hydromet.get('river_discharge_trend', 'NA')}"
        )
    if rules_fired:
        parts.append("rules " + ", ".join(rules_fired[:4]))
    if historical_context:
        parts.append(f"historical_context {historical_context[:360]}")
    return "\n".join(parts)


def _parse_llm_output(raw: str) -> tuple[str, list[str]]:
    summary = raw.strip()
    chain: list[str] = []
    if "Chain:" in summary:
        head, _, tail = summary.partition("Chain:")
        summary = head.strip()
        chain = [step.strip() for step in tail.split("->") if step.strip()]
    elif "Cadena:" in summary:
        head, _, tail = summary.partition("Cadena:")
        summary = head.strip()
        chain = [step.strip() for step in tail.split("->") if step.strip()]
    if not chain:
        # Split into up-to-3 sentence-like fragments as a coarse CoT surrogate.
        pieces = [p.strip() for p in summary.replace("\n", " ").split(".") if p.strip()]
        chain = pieces[:3]
    if summary.startswith("Summary:"):
        summary = summary.removeprefix("Summary:").strip()
    elif summary.startswith("Resumen:"):
        summary = summary.removeprefix("Resumen:").strip()
    return summary, chain[:5]


def _fallback(level: str, rules_fired: list[str]) -> ReasoningBlock:
    rules = rules_fired or ["no deterministic rules fired"]
    summary = (
        f"{level.upper()} alert emitted by local rule. "
        f"Active signals: {', '.join(rules[:3])}. "
        "Gemma unavailable; deterministic summary used."
    )
    return ReasoningBlock(
        llm_summary=summary,
        llm_chain_of_thought=rules[:3],
        model_name="rule-fallback",
    )


def _runtime_model_name(llm: object) -> str:
    if hasattr(llm, "model_name"):
        value = getattr(llm, "model_name")
        if isinstance(value, str) and value.strip():
            return value.strip()
    settings = getattr(llm, "settings", None)
    if settings is not None:
        value = getattr(settings, "llm_model", None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "unknown-runtime"


def generate_alert_reasoning(
    level: str,
    fused_score: float,
    node_obs: Optional[dict[str, Any]],
    volunteer_parsed: Optional[dict[str, Any]],
    hydromet: Optional[dict[str, Any]],
    rules_fired: list[str],
    llm: Optional[TextGenerator] = None,
    historical_context: str | None = None,
    historical_hits: list[HistoricalContextHit] | None = None,
) -> ReasoningBlock:
    """Produce an English reasoning block for an alert.

    Green alerts return an empty-ish block with only a rule-based single-line
    summary (no LLM call). Yellow/orange/red call the LLM with a deterministic
    fallback.
    """
    if level == "green":
        return ReasoningBlock(
            llm_summary="Green/verde level: no risk threshold exceeded. Gemma not invoked.",
            llm_chain_of_thought=["no signals above threshold"],
            model_name="rule-skip-green",
        )

    if llm is None:
        return _fallback(level, rules_fired)

    user_prompt = _render_inputs(
        node_obs,
        volunteer_parsed,
        hydromet,
        fused_score,
        level,
        rules_fired,
        historical_context,
    )
    raw = llm.generate_text(SYSTEM_PROMPT, user_prompt, max_tokens=192)
    if not raw:
        return _fallback(level, rules_fired)

    summary, chain = _parse_llm_output(raw)
    if not summary:
        return _fallback(level, rules_fired)

    if historical_hits and not validate_context_citations(summary, historical_hits):
        summary = summary.split("[ctx:", 1)[0].strip()
    if historical_hits:
        summary = f"{summary} Historical context: {render_historical_context(historical_hits)[:220]}"
    elif historical_context:
        summary = f"{summary} Historical context: {historical_context[:180]}"

    return ReasoningBlock(
        llm_summary=summary,
        llm_chain_of_thought=chain,
        model_name=_runtime_model_name(llm),
    )


def serialize_chain(chain: list[str]) -> str:
    return json.dumps(chain, ensure_ascii=True)


def deserialize_chain(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in value] if isinstance(value, list) else []
