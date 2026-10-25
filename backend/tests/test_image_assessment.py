from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from jalrekha.adapters.image_assessment import (
    GemmaImageAssessmentAdapter,
    _parse_json_block,
)
from jalrekha.core.settings import get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_parse_json_block_extracts_dict():
    text = "blah blah {\"description_es\": \"hola\", \"water_visible\": true, \"infrastructure_at_risk\": false, \"confidence\": 0.7} tail"
    parsed = _parse_json_block(text)
    assert parsed is not None
    assert parsed["description_es"] == "hola"


def test_parse_json_block_rejects_junk():
    assert _parse_json_block("no braces here") is None
    assert _parse_json_block("{broken") is None


def test_adapter_returns_none_for_missing_path(tmp_path: Path):
    adapter = GemmaImageAssessmentAdapter()
    assert adapter.assess(tmp_path / "missing.jpg") is None


def test_adapter_handles_http_error(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("JALREKHA_MULTIMODAL_VERIFIER_ENABLED", "true")
    img = tmp_path / "x.jpg"
    img.write_bytes(b"\x89PNG\r\n\x1a\nfakebytes")

    def boom(*_args, **_kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx.Client, "post", boom)
    adapter = GemmaImageAssessmentAdapter()
    assert adapter.assess(img) is None


def test_adapter_parses_success(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("JALREKHA_MULTIMODAL_VERIFIER_ENABLED", "true")
    img = tmp_path / "x.jpg"
    img.write_bytes(b"\x89PNG\r\n\x1a\nfakebytes")

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "message": {
                    "content": '{"description_es": "Agua cubre el tablero del puente.", "water_visible": true, "infrastructure_at_risk": true, "confidence": 0.8}'
                }
            }

    def fake_post(self, *_a, **_k):
        return FakeResponse()

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    adapter = GemmaImageAssessmentAdapter()
    result = adapter.assess(img)
    assert result is not None
    assert result.water_visible is True
    assert result.infrastructure_at_risk is True
    assert 0.79 < result.confidence < 0.81
    assert "puente" in result.description_es.lower()


def test_adapter_uses_embedded_runtime_when_present(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("JALREKHA_MULTIMODAL_VERIFIER_ENABLED", "true")
    img = tmp_path / "x.jpg"
    img.write_bytes(b"\x89PNG\r\n\x1a\nfakebytes")

    class FakeRuntime:
        model_name = "gemma-4-E2B-it.litertlm"

        def generate_multimodal_json(self, *args, **kwargs):
            return {
                "description_es": "Agua alta sobre el cauce.",
                "water_visible": True,
                "infrastructure_at_risk": False,
                "confidence": 0.74,
            }

    adapter = GemmaImageAssessmentAdapter(runtime=FakeRuntime(), force_embedded=True)
    result = adapter.assess(img)

    assert result is not None
    assert result.model_name == "gemma-4-E2B-it.litertlm"
    assert result.water_visible is True
