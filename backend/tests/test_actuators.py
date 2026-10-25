from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlmodel import Session, SQLModel

from jalrekha.api import deps
from jalrekha.adapters.litert_node import LiteRTNodeRuntime
from jalrekha.core import settings as settings_module
from jalrekha.db.database import central_engine, edge_engine, init_db
from jalrekha.models.domain import FusedAlert, Site
from jalrekha.services import actuators as actuators_module
from jalrekha.services.actuators import (
    RECORDED_CALLS,
    dispatch_actuators,
    reset_recorded_calls,
)
from jalrekha.services.storage import get_upload_dir


init_db()


@pytest.fixture(autouse=True)
def _reset_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JALREKHA_UPLOAD_DIR", str(tmp_path / "uploads"))
    settings_module.get_settings.cache_clear()
    deps.is_online = True
    for engine in (edge_engine, central_engine):
        with Session(engine) as session:
            for table in reversed(SQLModel.metadata.sorted_tables):
                session.exec(table.delete())
            session.commit()
    upload_dir = get_upload_dir()
    upload_dir.mkdir(parents=True, exist_ok=True)
    with Session(edge_engine) as session:
        session.add(
            Site(
                id="test-site",
                name="Test Site",
                region="Demo",
                lat=-32.95,
                lng=-60.64,
                description="for tests",
                is_active=True,
            )
        )
        session.commit()
    reset_recorded_calls()
    yield
    settings_module.get_settings.cache_clear()


def _make_alert(level: str = "red") -> FusedAlert:
    return FusedAlert(
        site_id="test-site",
        level=level,
        score=0.95,
        trigger_source="volunteer",
        summary="agua paso la marca, ruta cortada",
        decision_trace="[]",
        local_alarm_triggered=True,
        reasoning_summary="...",
        reasoning_chain="[]",
        reasoning_model="gemma4:e2b",
    )


class _FakeResponse:
    def __init__(self, json_body: dict[str, Any], status_code: int = 200):
        self._json = json_body
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    """Drop-in replacement for httpx.Client that returns a pre-baked response."""

    def __init__(self, response: _FakeResponse | None = None, raise_on_post: Exception | None = None):
        self._response = response
        self._raise = raise_on_post
        self.posts: list[tuple[str, dict[str, Any]]] = []

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *exc) -> None:  # noqa: ANN001
        return None

    def post(self, url: str, json: dict[str, Any] | None = None) -> _FakeResponse:
        self.posts.append((url, json or {}))
        if self._raise:
            raise self._raise
        assert self._response is not None
        return self._response


def _install_fake_client(monkeypatch: pytest.MonkeyPatch, fake: _FakeClient) -> None:
    monkeypatch.setattr(actuators_module.httpx, "Client", lambda **_kw: fake)


class _FakeLiteRTRuntime(LiteRTNodeRuntime):
    def __init__(self, payload: dict[str, Any] | None):
        self.payload = payload
        self.prompts: list[tuple[str, str, int]] = []

    def generate_json(self, system_prompt: str, user_prompt: str, max_tokens: int = 320) -> dict[str, Any] | None:
        self.prompts.append((system_prompt, user_prompt, max_tokens))
        return self.payload


def test_dispatch_disabled_returns_empty(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JALREKHA_ACTUATORS_ENABLED", "false")
    settings_module.get_settings.cache_clear()

    _install_fake_client(
        monkeypatch,
        _FakeClient(response=_FakeResponse({"message": {"tool_calls": []}})),
    )

    fired = dispatch_actuators(_make_alert(), deps.llm_client)
    assert fired == []
    assert RECORDED_CALLS == []


def test_dispatch_fires_single_tool_call(monkeypatch: pytest.MonkeyPatch):
    response = _FakeResponse(
        {
            "message": {
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {
                            "name": "trigger_alarm",
                            "arguments": {"reason": "agua sobre la calle"},
                        },
                    }
                ]
            }
        }
    )
    _install_fake_client(monkeypatch, _FakeClient(response=response))

    fired = dispatch_actuators(_make_alert(), deps.llm_client)
    assert fired == ["trigger_alarm"]
    assert RECORDED_CALLS == [("trigger_alarm", {"reason": "agua sobre la calle"})]


def test_dispatch_litert_path_does_not_use_httpx(monkeypatch: pytest.MonkeyPatch):
    def fail_if_httpx_used(**_kwargs):
        raise AssertionError("LiteRT actuator dispatch must not use httpx")

    monkeypatch.setattr(actuators_module.httpx, "Client", fail_if_httpx_used)
    runtime = _FakeLiteRTRuntime(
        {
            "tool_calls": [
                {
                    "function": {
                        "name": "notify_app",
                        "arguments": {"text": "preparar evacuacion preventiva"},
                    }
                }
            ]
        }
    )

    fired = dispatch_actuators(_make_alert(level="orange"), runtime)

    assert fired == ["notify_app"]
    assert RECORDED_CALLS == [("notify_app", {"text": "preparar evacuacion preventiva"})]
    assert runtime.prompts


def test_dispatch_litert_path_executes_valid_tool_calls():
    runtime = _FakeLiteRTRuntime(
        {
            "tool_calls": [
                {
                    "name": "trigger_alarm",
                    "arguments": {"reason": "agua cruzo la marca critica"},
                },
                {
                    "function": {
                        "name": "send_radio_payload",
                        "arguments": {"severity": "red", "summary": "evacuar zona baja"},
                    }
                },
            ]
        }
    )

    fired = dispatch_actuators(_make_alert(), runtime)

    assert fired == ["trigger_alarm", "send_radio_payload"]
    assert RECORDED_CALLS == [
        ("trigger_alarm", {"reason": "agua cruzo la marca critica"}),
        ("send_radio_payload", {"severity": "red", "summary": "evacuar zona baja"}),
    ]


def test_dispatch_litert_path_ignores_unknown_tools():
    runtime = _FakeLiteRTRuntime(
        {
            "tool_calls": [
                {"name": "launch_nukes", "arguments": {}},
                {"name": "notify_app", "arguments": {"text": "alerta roja"}},
            ]
        }
    )

    fired = dispatch_actuators(_make_alert(), runtime)

    assert fired == ["notify_app"]
    assert RECORDED_CALLS == [("notify_app", {"text": "alerta roja"})]


def test_dispatch_litert_path_dedupes_duplicate_allowed_tool_calls():
    runtime = _FakeLiteRTRuntime(
        {
            "tool_calls": [
                {"name": "notify_app", "arguments": {"text": "alerta naranja"}},
                {"name": "notify_app", "arguments": {"text": "alerta duplicada"}},
            ]
        }
    )

    fired = dispatch_actuators(
        _make_alert(level="orange"),
        runtime,
        allowed_tools={"notify_app"},
    )

    assert fired == ["notify_app"]
    assert RECORDED_CALLS == [("notify_app", {"text": "alerta naranja"})]


def test_dispatch_litert_path_malformed_json_returns_empty():
    runtime = _FakeLiteRTRuntime(None)

    fired = dispatch_actuators(_make_alert(), runtime)

    assert fired == []
    assert RECORDED_CALLS == []


def test_dispatch_litert_path_keeps_orange_red_guardrail():
    runtime = _FakeLiteRTRuntime(
        {
            "tool_calls": [
                {"name": "trigger_alarm", "arguments": {"reason": "modelo pidio herramienta"}}
            ]
        }
    )

    fired = dispatch_actuators(_make_alert(level="yellow"), runtime)

    assert fired == []
    assert RECORDED_CALLS == []
    assert runtime.prompts == []


def test_dispatch_fires_multiple_tool_calls(monkeypatch: pytest.MonkeyPatch):
    response = _FakeResponse(
        {
            "message": {
                "tool_calls": [
                    {"function": {"name": "trigger_alarm", "arguments": {"reason": "rojo"}}},
                    {"function": {"name": "notify_app", "arguments": {"text": "evacuar zona baja"}}},
                ]
            }
        }
    )
    _install_fake_client(monkeypatch, _FakeClient(response=response))

    fired = dispatch_actuators(_make_alert(), deps.llm_client)
    assert fired == ["trigger_alarm", "notify_app"]
    assert len(RECORDED_CALLS) == 2
    names = [name for name, _ in RECORDED_CALLS]
    assert names == ["trigger_alarm", "notify_app"]


def test_dispatch_no_tool_calls_returns_empty(monkeypatch: pytest.MonkeyPatch):
    response = _FakeResponse({"message": {"content": "no tools needed", "tool_calls": []}})
    _install_fake_client(monkeypatch, _FakeClient(response=response))

    fired = dispatch_actuators(_make_alert(), deps.llm_client)
    assert fired == []
    assert RECORDED_CALLS == []


def test_dispatch_transport_error_returns_empty(monkeypatch: pytest.MonkeyPatch):
    _install_fake_client(monkeypatch, _FakeClient(raise_on_post=RuntimeError("boom")))

    fired = dispatch_actuators(_make_alert(), deps.llm_client)
    assert fired == []
    assert RECORDED_CALLS == []


def test_dispatch_unknown_tool_name_ignored(monkeypatch: pytest.MonkeyPatch):
    response = _FakeResponse(
        {
            "message": {
                "tool_calls": [
                    {"function": {"name": "trigger_alarm", "arguments": {"reason": "ok"}}},
                    {"function": {"name": "launch_nukes", "arguments": {}}},
                ]
            }
        }
    )
    _install_fake_client(monkeypatch, _FakeClient(response=response))

    fired = dispatch_actuators(_make_alert(), deps.llm_client)
    assert fired == ["trigger_alarm"]
