"""Actuator dispatch via local Gemma tool selection.

When a fused alert is escalated to orange/red, we ask the configured local
Gemma runtime which actuators to fire. LiteRT production uses strict JSON tool
selection through ``LiteRTNodeRuntime``; Ollama remains supported as an explicit
development provider through native ``tool_calls``.

The default implementations are stdout-printing stubs that also append every
fired call to ``RECORDED_CALLS`` so tests can assert behaviour without going
through a real I/O backend (siren GPIO, LoRa modem, mobile push, etc.).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

import httpx

from jalrekha.adapters.litert_node import LiteRTNodeRuntime
from jalrekha.core.settings import get_settings


if TYPE_CHECKING:
    from jalrekha.adapters.llm import OpenAICompatibleLLM
    from jalrekha.models.domain import FusedAlert


_LOGGER = logging.getLogger(__name__)


# Test inspection hook. Each entry is ``(tool_name, payload)``.
RECORDED_CALLS: list[tuple[str, dict[str, Any]]] = []


def reset_recorded_calls() -> None:
    """Clear ``RECORDED_CALLS`` — intended for test fixtures."""
    RECORDED_CALLS.clear()


class AlarmActuator(Protocol):
    def fire(self, payload: dict[str, Any]) -> None: ...


class RadioActuator(Protocol):
    def fire(self, payload: dict[str, Any]) -> None: ...


class NotificationActuator(Protocol):
    def fire(self, payload: dict[str, Any]) -> None: ...


class LoggingAlarmActuator:
    """Default alarm actuator: prints an operator-visible message and
    records the call for tests. A real deployment would replace this with a
    GPIO-backed siren driver."""

    def fire(self, payload: dict[str, Any]) -> None:
        reason = str(payload.get("reason", "")).strip() or "no reason given"
        print(f"[SIREN] activated, reason: {reason}")
        RECORDED_CALLS.append(("trigger_alarm", dict(payload)))


class LoraFileRadioActuator:
    """Default radio actuator: emits the payload that would be transmitted on
    the LoRa mesh. The real implementation pushes a frame to a serial modem."""

    def fire(self, payload: dict[str, Any]) -> None:
        severity = str(payload.get("severity", "")).strip() or "unknown"
        print(f"[RADIO] LoRa message queued, severity: {severity}")
        RECORDED_CALLS.append(("send_radio_payload", dict(payload)))


class InAppBannerNotifier:
    """Default in-app notifier: would normally push to FCM / the running
    Android client. Here we just log and record."""

    def fire(self, payload: dict[str, Any]) -> None:
        text = str(payload.get("text", "")).strip() or "(empty message)"
        print(f"[APP] notification sent: {text}")
        RECORDED_CALLS.append(("notify_app", dict(payload)))


ACTUATOR_REGISTRY: dict[str, Any] = {
    "trigger_alarm": LoggingAlarmActuator(),
    "send_radio_payload": LoraFileRadioActuator(),
    "notify_app": InAppBannerNotifier(),
}


ACTUATOR_TOOL_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "trigger_alarm",
            "description": (
                "Activa la sirena local del nodo JalRekha. Usar solo "
                "cuando la alerta sea naranja o roja y haya riesgo inmediato "
                "para la comunidad."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": (
                            "Motivo conciso en espanol que justifica encender "
                            "la sirena (ej: 'agua cruzo la marca critica')."
                        ),
                    }
                },
                "required": ["reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_radio_payload",
            "description": (
                "Envia un mensaje por radio LoRa a los demas nodos de la red "
                "para informar la nueva situacion."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "severity": {
                        "type": "string",
                        "description": (
                            "Severidad de la alerta a difundir: orange o red."
                        ),
                    },
                    "summary": {
                        "type": "string",
                        "description": "Resumen breve para el frame LoRa.",
                    },
                },
                "required": ["severity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notify_app",
            "description": (
                "Envia una notificacion push al panel de la aplicacion movil "
                "para que los brigadistas la vean."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": (
                            "Texto corto en espanol con la informacion clave "
                            "para los brigadistas."
                        ),
                    }
                },
                "required": ["text"],
            },
        },
    },
]


def _build_messages(alert: "FusedAlert") -> list[dict[str, str]]:
    system = (
        "Eres el coordinador de actuadores de un sistema temprano de aviso "
        "de inundaciones. Recibis una alerta ya fusionada y decidis que "
        "actuadores disparar usando las herramientas disponibles. Solo "
        "invoca herramientas si la alerta es naranja o roja. No agregues "
        "texto adicional fuera de las llamadas a herramientas."
    )
    user = (
        f"Alerta para el sitio {alert.site_id}.\n"
        f"Nivel: {alert.level}.\n"
        f"Puntaje fusionado: {alert.score:.2f}.\n"
        f"Fuente disparadora: {alert.trigger_source}.\n"
        f"Resumen: {alert.summary}.\n"
        "Decidi que actuadores disparar."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _ollama_chat_url(base_url: str) -> str:
    """Mirror of OpenAICompatibleLLM._ollama_chat_url so we can call /api/chat
    directly (the public adapter does not expose tool-calling yet)."""
    return base_url.rstrip("/").removesuffix("/v1") + "/api/chat"


def _build_litert_prompts(alert: "FusedAlert") -> tuple[str, str]:
    system = (
        "You select actuator tool calls for an offline flood warning node. "
        "Return only valid JSON, with no markdown and no prose. "
        "Schema: {\"tool_calls\":[{\"name\":\"trigger_alarm|send_radio_payload|notify_app\","
        "\"arguments\":{}}]}. "
        "Use an empty tool_calls array unless the alert level is orange or red. "
        "Only use the listed tool names. "
        "Arguments: trigger_alarm needs reason; send_radio_payload needs severity and optional summary; "
        "notify_app needs text."
    )
    user = (
        f"Alert site_id={alert.site_id!r}, level={alert.level!r}, "
        f"score={alert.score:.2f}, trigger_source={alert.trigger_source!r}.\n"
        f"Summary: {alert.summary}\n"
        "Select the minimal actuator calls now."
    )
    return system, user


def _call_litert_tool_selection(alert: "FusedAlert", runtime: LiteRTNodeRuntime) -> dict[str, Any] | None:
    system_prompt, user_prompt = _build_litert_prompts(alert)
    try:
        return runtime.generate_json(system_prompt, user_prompt, max_tokens=96)
    except Exception as exc:
        _LOGGER.warning("LiteRT actuator selection failed: %s", exc)
        return None


def _call_ollama_tool_selection(
    alert: "FusedAlert",
    llm: "OpenAICompatibleLLM",
) -> dict[str, Any] | None:
    messages = _build_messages(alert)
    payload = {
        "model": get_settings().llm_model,
        "stream": False,
        "think": False,
        "keep_alive": -1,
        "tools": ACTUATOR_TOOL_SCHEMA,
        "messages": messages,
        "options": {"num_predict": 200, "temperature": 0},
    }
    url = _ollama_chat_url(llm.settings.llm_base_url)

    try:
        with httpx.Client(timeout=llm.settings.llm_timeout_seconds) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
        return response.json()
    except Exception as exc:
        _LOGGER.warning("actuator LLM call failed: %s", exc)
        return None


def _tool_calls_from_body(body: dict[str, Any] | None) -> list[Any]:
    if not isinstance(body, dict):
        return []
    message = body.get("message")
    if isinstance(message, dict):
        tool_calls = message.get("tool_calls")
    else:
        tool_calls = body.get("tool_calls")
    if not isinstance(tool_calls, list):
        return []
    return tool_calls


def dispatch_actuators(
    alert: "FusedAlert",
    llm: "OpenAICompatibleLLM | LiteRTNodeRuntime",
    *,
    allowed_tools: set[str] | None = None,
) -> list[str]:
    """Ask Gemma which actuators to fire for ``alert`` and dispatch them.

    Returns the list of tool names that were successfully fired. Any failure
    (settings gate, transport error, malformed response, actuator missing in
    registry) is swallowed and returns an empty list — actuator dispatch must
    never break the decision pipeline.
    """
    settings = get_settings()
    if not settings.actuators_enabled:
        _LOGGER.info("actuators disabled by settings; skipping dispatch")
        return []
    if alert.level not in {"orange", "red"}:
        _LOGGER.info("actuator dispatch guardrail skipped level=%s", alert.level)
        return []

    body = (
        _call_litert_tool_selection(alert, llm)
        if isinstance(llm, LiteRTNodeRuntime)
        else _call_ollama_tool_selection(alert, llm)
    )

    try:
        tool_calls = _tool_calls_from_body(body)
        if not tool_calls:
            _LOGGER.info("actuator LLM returned no tool_calls")
            return []

        fired: list[str] = []
        seen: set[str] = set()
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            function = call.get("function") if isinstance(call.get("function"), dict) else call
            name = function.get("name")
            arguments = function.get("arguments") or {}
            if not isinstance(arguments, dict):
                arguments = {}
            if not isinstance(name, str):
                continue
            actuator = ACTUATOR_REGISTRY.get(name)
            if actuator is None:
                _LOGGER.warning("LLM requested unknown actuator: %s", name)
                continue
            if allowed_tools is not None and name not in allowed_tools:
                _LOGGER.warning("LLM requested actuator outside recommended set: %s", name)
                continue
            if name in seen:
                _LOGGER.info("LLM requested duplicate actuator in one response: %s", name)
                continue
            try:
                actuator.fire(arguments)
                seen.add(name)
                fired.append(name)
            except Exception as exc:
                _LOGGER.warning("actuator %s raised during fire(): %s", name, exc)
        return fired
    except Exception as exc:
        _LOGGER.warning("actuator response parsing failed: %s", exc)
        return []
