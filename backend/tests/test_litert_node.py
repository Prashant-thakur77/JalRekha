from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from jalrekha.core import settings as settings_module


@pytest.fixture(autouse=True)
def clear_settings_cache():
    settings_module.get_settings.cache_clear()
    yield
    settings_module.get_settings.cache_clear()


def test_litert_runtime_health_reports_missing_dependency(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("JALREKHA_NODE_PROVIDER", "litert")
    monkeypatch.setenv("JALREKHA_NODE_MODEL_PATH", str(tmp_path / "gemma-4-E2B-it.litertlm"))

    from jalrekha.adapters.litert_node import LiteRTNodeRuntime

    runtime = LiteRTNodeRuntime()
    monkeypatch.setattr(runtime, "_import_litert_module", lambda: (_ for _ in ()).throw(ModuleNotFoundError("litert_lm")))

    health = runtime.health()

    assert health.enabled is True
    assert health.reachable is False
    assert health.provider == "litert"
    assert "litert_lm" in health.detail


def test_litert_runtime_generate_text_uses_engine(monkeypatch, tmp_path: Path):
    model_path = tmp_path / "gemma-4-E2B-it.litertlm"
    model_path.write_bytes(b"fake-model")

    monkeypatch.setenv("JALREKHA_NODE_PROVIDER", "litert")
    monkeypatch.setenv("JALREKHA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JALREKHA_NODE_MODEL_PATH", str(model_path))
    monkeypatch.setenv("JALREKHA_NODE_BACKEND", "cpu")
    monkeypatch.setenv("JALREKHA_NODE_VISION_BACKEND", "gpu")

    from jalrekha.adapters.litert_node import LiteRTNodeRuntime

    calls: list[dict[str, object]] = []

    class FakeConversation:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def send_message(self, message):
            calls.append({"message": message})
            return {"content": [{"text": "respuesta LiteRT"}]}

    class FakeEngine:
        def __init__(self, model_path, **kwargs):
            calls.append({"model_path": model_path, "kwargs": kwargs})

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def create_conversation(self):
            return FakeConversation()

    fake_module = SimpleNamespace(
        Engine=FakeEngine,
        Backend=SimpleNamespace(CPU="cpu", GPU="gpu"),
    )

    runtime = LiteRTNodeRuntime()
    monkeypatch.setattr(runtime, "_import_litert_module", lambda: fake_module)

    result = runtime.generate_text("system prompt", "user prompt", max_tokens=128)

    assert result == "respuesta LiteRT"
    assert any(entry.get("model_path") == str(model_path) for entry in calls)
    assert any(
        entry.get("kwargs") == {
            "backend": "cpu",
            "cache_dir": str(tmp_path / "litert-cache"),
            "max_num_tokens": 1024,
            "enable_speculative_decoding": True,
        }
        for entry in calls
    )
    assert any("user prompt" in str(entry.get("message")) for entry in calls)


def test_litert_runtime_generate_multimodal_json(monkeypatch, tmp_path: Path):
    model_path = tmp_path / "gemma-4-E2B-it.litertlm"
    model_path.write_bytes(b"fake-model")
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"fake-image")

    monkeypatch.setenv("JALREKHA_NODE_PROVIDER", "litert")
    monkeypatch.setenv("JALREKHA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JALREKHA_NODE_MODEL_PATH", str(model_path))
    monkeypatch.setenv("JALREKHA_NODE_BACKEND", "cpu")
    monkeypatch.setenv("JALREKHA_NODE_VISION_BACKEND", "gpu")

    from jalrekha.adapters.litert_node import LiteRTNodeRuntime

    class FakeConversation:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def send_message(self, message):
            assert isinstance(message, dict)
            assert any(part.get("type") == "image" for part in message["content"])
            return {
                "content": [
                    {
                        "text": '{"description_es":"Agua alta","water_visible":true,"infrastructure_at_risk":true,"confidence":0.8}'
                    }
                ]
            }

    class FakeEngine:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def create_conversation(self):
            return FakeConversation()

    fake_module = SimpleNamespace(
        Engine=FakeEngine,
        Backend=SimpleNamespace(CPU="cpu", GPU="gpu"),
    )

    runtime = LiteRTNodeRuntime()
    monkeypatch.setattr(runtime, "_import_litert_module", lambda: fake_module)

    result = runtime.generate_multimodal_json(
        "system prompt",
        "describe la escena",
        [image_path],
        max_tokens=128,
    )

    assert result is not None
    assert result["description_es"] == "Agua alta"


def test_litert_runtime_uses_separate_multimodal_engine(monkeypatch, tmp_path: Path):
    model_path = tmp_path / "gemma-4-E2B-it.litertlm"
    model_path.write_bytes(b"fake-model")
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"fake-image")

    monkeypatch.setenv("JALREKHA_NODE_PROVIDER", "litert")
    monkeypatch.setenv("JALREKHA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JALREKHA_NODE_MODEL_PATH", str(model_path))
    monkeypatch.setenv("JALREKHA_NODE_BACKEND", "gpu")
    monkeypatch.setenv("JALREKHA_NODE_VISION_BACKEND", "cpu")
    monkeypatch.setenv("JALREKHA_NODE_MULTIMODAL_BACKEND", "cpu")
    monkeypatch.setenv("JALREKHA_NODE_MULTIMODAL_VISION_BACKEND", "cpu")
    monkeypatch.setenv("JALREKHA_NODE_MULTIMODAL_MAX_OUTPUT_TOKENS", "2048")

    from jalrekha.adapters.litert_node import LiteRTNodeRuntime

    calls: list[dict[str, object]] = []

    class FakeConversation:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def send_message(self, _message):
            return {"content": [{"text": '{"status":"ok"}'}]}

    class FakeEngine:
        def __init__(self, model_path, **kwargs):
            calls.append({"model_path": model_path, "kwargs": kwargs})

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def create_conversation(self):
            return FakeConversation()

    fake_module = SimpleNamespace(
        Engine=FakeEngine,
        Backend=SimpleNamespace(CPU="cpu", GPU="gpu"),
    )

    runtime = LiteRTNodeRuntime()
    monkeypatch.setattr(runtime, "_import_litert_module", lambda: fake_module)

    assert runtime.generate_text("system prompt", "user prompt") == '{"status":"ok"}'
    runtime.generate_multimodal_json("system prompt", "user prompt", [image_path])

    assert calls[0]["kwargs"]["backend"] == "gpu"
    assert calls[0]["kwargs"]["max_num_tokens"] == 1024
    assert "vision_backend" not in calls[0]["kwargs"]
    assert calls[1]["kwargs"]["backend"] == "cpu"
    assert calls[1]["kwargs"]["vision_backend"] == "cpu"
    assert calls[1]["kwargs"]["max_num_tokens"] == 2048


def test_litert_runtime_honors_speculative_decoding_override(monkeypatch, tmp_path: Path):
    model_path = tmp_path / "gemma-4-E2B-it.litertlm"
    model_path.write_bytes(b"fake-model")

    monkeypatch.setenv("JALREKHA_NODE_PROVIDER", "litert")
    monkeypatch.setenv("JALREKHA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JALREKHA_NODE_MODEL_PATH", str(model_path))
    monkeypatch.setenv("JALREKHA_NODE_ENABLE_SPECULATIVE_DECODING", "false")

    from jalrekha.adapters.litert_node import LiteRTNodeRuntime

    calls: list[dict[str, object]] = []

    class FakeConversation:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def send_message(self, _message):
            return {"content": [{"text": "ok"}]}

    class FakeEngine:
        def __init__(self, _model_path, **kwargs):
            calls.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def create_conversation(self):
            return FakeConversation()

    fake_module = SimpleNamespace(
        Engine=FakeEngine,
        Backend=SimpleNamespace(CPU="cpu", GPU="gpu"),
    )

    runtime = LiteRTNodeRuntime()
    monkeypatch.setattr(runtime, "_import_litert_module", lambda: fake_module)

    assert runtime.generate_text("system prompt", "user prompt") == "ok"
    assert calls[0]["backend"] == "gpu"
    assert calls[0]["enable_speculative_decoding"] is False


def test_litert_runtime_repairs_truncated_json_object():
    from jalrekha.adapters.litert_node import LiteRTNodeRuntime

    raw = (
        '{"assessment_level":"green",'
        '"critical_evidence":{"confidence":0.8}'
    )

    parsed = LiteRTNodeRuntime._extract_json(raw)

    assert parsed == {
        "assessment_level": "green",
        "critical_evidence": {"confidence": 0.8},
    }


def test_litert_runtime_returns_none_when_dependency_is_missing(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("JALREKHA_NODE_PROVIDER", "litert")
    monkeypatch.setenv("JALREKHA_NODE_MODEL_PATH", str(tmp_path / "gemma-4-E2B-it.litertlm"))

    from jalrekha.adapters.litert_node import LiteRTNodeRuntime

    runtime = LiteRTNodeRuntime()
    monkeypatch.setattr(runtime, "_import_litert_module", lambda: (_ for _ in ()).throw(ModuleNotFoundError("litert_lm")))

    assert runtime.generate_text("system prompt", "user prompt") is None


def test_litert_runtime_exposes_last_send_error(monkeypatch, tmp_path: Path):
    model_path = tmp_path / "gemma-4-E2B-it.litertlm"
    model_path.write_bytes(b"fake-model")

    monkeypatch.setenv("JALREKHA_NODE_PROVIDER", "litert")
    monkeypatch.setenv("JALREKHA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JALREKHA_NODE_MODEL_PATH", str(model_path))

    from jalrekha.adapters.litert_node import LiteRTNodeRuntime

    class FakeConversation:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def send_message(self, _message):
            raise RuntimeError("litert_lm_conversation_send_message failed")

    class FakeEngine:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def create_conversation(self):
            return FakeConversation()

    fake_module = SimpleNamespace(
        Engine=FakeEngine,
        Backend=SimpleNamespace(CPU="cpu", GPU="gpu"),
    )

    runtime = LiteRTNodeRuntime()
    monkeypatch.setattr(runtime, "_import_litert_module", lambda: fake_module)

    assert runtime.generate_text("system prompt", "user prompt") is None
    assert runtime.last_error_type == "RuntimeError"
    assert runtime.last_error_detail == "litert_lm_conversation_send_message failed"


def test_litert_runtime_resets_engine_and_retries_reuse_failure(monkeypatch, tmp_path: Path):
    model_path = tmp_path / "gemma-4-E2B-it.litertlm"
    model_path.write_bytes(b"fake-model")

    monkeypatch.setenv("JALREKHA_NODE_PROVIDER", "litert")
    monkeypatch.setenv("JALREKHA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JALREKHA_NODE_MODEL_PATH", str(model_path))

    from jalrekha.adapters.litert_node import LiteRTNodeRuntime

    calls: list[str] = []

    class FakeConversation:
        def __init__(self, label: str):
            self.label = label

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def send_message(self, _message):
            calls.append(self.label)
            if self.label == "engine-1":
                raise RuntimeError("litert_lm_conversation_send_message failed")
            return {"content": [{"text": "retry ok"}]}

    class FakeEngine:
        counter = 0

        def __init__(self, *_args, **_kwargs):
            type(self).counter += 1
            self.label = f"engine-{type(self).counter}"

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def create_conversation(self):
            return FakeConversation(self.label)

    fake_module = SimpleNamespace(
        Engine=FakeEngine,
        Backend=SimpleNamespace(CPU="cpu", GPU="gpu"),
    )

    runtime = LiteRTNodeRuntime()
    monkeypatch.setattr(runtime, "_import_litert_module", lambda: fake_module)

    assert runtime.generate_text("system prompt", "user prompt") == "retry ok"
    assert calls == ["engine-1", "engine-2"]
    assert FakeEngine.counter == 2
    assert runtime.last_error_type is None
    assert runtime.last_error_detail is None
    assert runtime.last_response_type == "dict"


def test_litert_runtime_returns_none_when_reuse_retry_fails(monkeypatch, tmp_path: Path):
    model_path = tmp_path / "gemma-4-E2B-it.litertlm"
    model_path.write_bytes(b"fake-model")

    monkeypatch.setenv("JALREKHA_NODE_PROVIDER", "litert")
    monkeypatch.setenv("JALREKHA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JALREKHA_NODE_MODEL_PATH", str(model_path))

    from jalrekha.adapters.litert_node import LiteRTNodeRuntime

    class FakeConversation:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def send_message(self, _message):
            raise RuntimeError("litert_lm_conversation_send_message failed")

    class FakeEngine:
        counter = 0

        def __init__(self, *_args, **_kwargs):
            type(self).counter += 1

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def create_conversation(self):
            return FakeConversation()

    fake_module = SimpleNamespace(
        Engine=FakeEngine,
        Backend=SimpleNamespace(CPU="cpu", GPU="gpu"),
    )

    runtime = LiteRTNodeRuntime()
    monkeypatch.setattr(runtime, "_import_litert_module", lambda: fake_module)

    assert runtime.generate_text("system prompt", "user prompt") is None
    assert FakeEngine.counter == 2
    assert runtime.last_error_type == "RuntimeError"
    assert runtime.last_error_detail == "litert_lm_conversation_send_message failed"


def test_litert_runner_parses_json_payload(monkeypatch, tmp_path: Path):
    from datetime import datetime

    from jalrekha.adapters.video_assessment import LiteRTGemmaRunner
    from jalrekha.services.node_assessment import AssessmentArtifactPack, EvidenceFrame, TemporalEvidencePack

    image_path = tmp_path / "synthetic.jpg"
    image_path.write_bytes(b"fake-image")

    class FakeRuntime:
        model_name = "gemma-4-E2B-it.litertlm"

        def generate_multimodal_json(self, *args, **kwargs):
            return {
                "assessment_level": "orange",
                "assessment_score": 0.76,
                "temporal_summary": "El agua ocupa buena parte del cauce.",
                "reasoning_summary": "Se ve agua alta cerca del puente y riesgo moderado sobre infraestructura.",
                "reasoning_steps": ["mirar nivel", "comparar con puente", "escalar"],
                "critical_evidence": {
                    "waterline_ratio": 0.76,
                    "crossed_critical_line": False,
                    "rise_velocity": 0.0,
                    "confidence": 0.82,
                },
            }

    pack = TemporalEvidencePack(
        site_id="test-site",
        site_name="Puente Test",
        site_region="Zona Demo",
        video_path=str(image_path),
        source_type="frame",
        started_at=datetime.utcnow(),
        ended_at=datetime.utcnow(),
        frames_analyzed=1,
        selected_frames=[
            EvidenceFrame(
                frame_path=str(image_path),
                timestamp_s=0.0,
                brightness=-1,
                contrast=-1,
                motion_score=-1,
                edge_strength=-1,
                waterline_ratio_hint=-1,
                waterline_y=-1,
            )
        ],
        evidence_frame_path=str(image_path),
        reference_y=0,
        critical_y=0,
        summary_metrics={"mode": "gemma4-multimodal-only"},
        artifact_pack=AssessmentArtifactPack(
            manifest_path="manifest.json",
            selected_frame_paths=[str(image_path)],
            evidence_frame_path=str(image_path),
        ),
    )

    verdict = LiteRTGemmaRunner(FakeRuntime()).assess(pack)

    assert verdict is not None
    assert verdict.assessment_level == "orange"
    assert 0.75 < verdict.assessment_score < 0.77
    assert verdict.runner_name == "gemma-4-E2B-it.litertlm"
    assert verdict.runner_mode == "litert-multimodal-temporal"


def test_litert_runner_retries_invalid_payload(monkeypatch, tmp_path: Path):
    from datetime import datetime

    from jalrekha.adapters.video_assessment import LiteRTGemmaRunner
    from jalrekha.services.node_assessment import AssessmentArtifactPack, EvidenceFrame, TemporalEvidencePack

    image_path = tmp_path / "synthetic.jpg"
    image_path.write_bytes(b"fake-image")

    class FakeRuntime:
        model_name = "gemma-4-E2B-it.litertlm"

        def __init__(self):
            self.calls = 0

        def generate_multimodal_json(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return None
            return {
                "assessment_level": "yellow",
                "assessment_score": 0.45,
                "temporal_summary": "El agua se ve estable en el cuadro.",
                "reasoning_summary": "La primera respuesta fue invalida, pero el reintento devolvio JSON valido.",
                "reasoning_steps": ["reintentar", "parsear json"],
                "critical_evidence": {"confidence": 0.7},
            }

    pack = TemporalEvidencePack(
        site_id="test-site",
        site_name="Puente Test",
        site_region="Zona Demo",
        video_path=str(image_path),
        source_type="frame",
        started_at=datetime.utcnow(),
        ended_at=datetime.utcnow(),
        frames_analyzed=1,
        selected_frames=[
            EvidenceFrame(
                frame_path=str(image_path),
                timestamp_s=0.0,
                brightness=-1,
                contrast=-1,
                motion_score=-1,
                edge_strength=-1,
                waterline_ratio_hint=-1,
                waterline_y=-1,
            )
        ],
        evidence_frame_path=str(image_path),
        reference_y=0,
        critical_y=0,
        summary_metrics={"mode": "gemma4-multimodal-only"},
        artifact_pack=AssessmentArtifactPack(
            manifest_path="manifest.json",
            selected_frame_paths=[str(image_path)],
            evidence_frame_path=str(image_path),
        ),
    )
    runtime = FakeRuntime()

    verdict = LiteRTGemmaRunner(runtime).assess(pack)

    assert runtime.calls == 2
    assert verdict is not None
    assert verdict.runner_mode == "litert-multimodal-temporal"
