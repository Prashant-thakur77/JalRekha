from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from jalrekha.adapters.video_assessment import OllamaGemmaRunner
from jalrekha.core import settings as settings_module
from jalrekha.models.domain import Site, SiteCalibration
from jalrekha.services.node_assessment import (
    NodeAssessmentEngine,
    AssessmentArtifactPack,
    EvidenceFrame,
    TemporalEvidenceBuilder,
    TemporalEvidencePack,
    _run_ffmpeg_extract,
)
_NUMPY_AVAILABLE = True  # firewall now runs in a subprocess; main process never imports numpy


@pytest.fixture(autouse=True)
def isolated_upload_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JALREKHA_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("JALREKHA_MULTIMODAL_MAX_FRAMES", "1")
    monkeypatch.setenv("JALREKHA_MULTIMODAL_IMAGE_MAX_SIDE", "512")
    settings_module.get_settings.cache_clear()
    yield
    settings_module.get_settings.cache_clear()


def _build_test_image(path: Path) -> None:
    image = Image.new("RGB", (320, 240), (200, 210, 220))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 132, 319, 239), fill=(90, 70, 40))
    draw.line((0, 95, 319, 95), fill=(245, 245, 245), width=2)
    image.save(path, format="JPEG")


def _site() -> Site:
    return Site(id="test-site", name="Puente Test", region="Zona Demo", lat=-32.95, lng=-60.64)


def _calibration() -> SiteCalibration:
    return SiteCalibration(
        site_id="test-site",
        roi_polygon="[[0, 40], [320, 40], [320, 220], [0, 220]]",
        critical_line="[[0, 95], [320, 95]]",
        reference_line="[[0, 155], [320, 155]]",
        notes="synthetic calibration",
    )


def test_multimodal_evidence_builder_curates_image(tmp_path: Path):
    image_path = tmp_path / "synthetic.jpg"
    _build_test_image(image_path)

    builder = TemporalEvidenceBuilder()
    pack, ratio_hint, rise_velocity_hint, crossed_hint, confidence, trace = builder.build(
        site=_site(),
        video_path=str(image_path),
        calibration=_calibration(),
        source_type="frame",
    )

    assert pack.frames_analyzed == 1
    assert len(pack.selected_frames) == 1
    assert Path(pack.selected_frames[0].frame_path).exists()
    assert Path(pack.evidence_frame_path).exists()
    if _NUMPY_AVAILABLE:
        # No gauge calibration on this site, so the OpenCV pipeline does not run;
        # only the PIL firewall baseline does.
        assert pack.summary_metrics["opencv_used"] is False
        assert pack.summary_metrics["deterministic_prefilter"]["cv_backend"] == "pil-pure-python"
        assert pack.summary_metrics["deterministic_prefilter"]["water_level"] in {"low", "elevated", "critical"}
        assert ratio_hint >= 0
        assert crossed_hint in (True, False)
    else:
        assert ratio_hint == 0
        assert rise_velocity_hint == 0
        assert crossed_hint is False
        assert confidence == 0
        assert pack.summary_metrics["opencv_used"] is False
    assert trace


def test_ffmpeg_extract_uses_png_sequence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    video_path = tmp_path / "sample.mp4"
    video_path.write_bytes(b"video")
    output_dir = tmp_path / "frames"
    output_dir.mkdir()
    captured: list[str] = []

    class Result:
        returncode = 0
        stderr = ""
        stdout = ""

    def fake_run(command, capture_output, text, check):
        captured.extend(command)
        (output_dir / "node-frame-001.png").write_bytes(b"png")
        return Result()

    monkeypatch.setattr("jalrekha.services.node_assessment.shutil.which", lambda _value: "/usr/bin/ffmpeg")
    monkeypatch.setattr("jalrekha.services.node_assessment.subprocess.run", fake_run)

    extracted = _run_ffmpeg_extract(video_path, output_dir, max_frames=1, sample_seconds=15, max_side=512)

    assert extracted == [output_dir / "node-frame-001.png"]
    assert captured[-1].endswith("node-frame-%03d.png")
    assert "-q:v" not in captured


def test_ffmpeg_extract_falls_back_to_first_frame(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    video_path = tmp_path / "sample.mp4"
    video_path.write_bytes(b"video")
    output_dir = tmp_path / "frames"
    output_dir.mkdir()
    commands: list[list[str]] = []

    class Result:
        returncode = 0
        stderr = ""
        stdout = ""

    def fake_run(command, capture_output, text, check):
        commands.append(list(command))
        if len(commands) == 2:
            (output_dir / "node-frame-001.png").write_bytes(b"png")
        return Result()

    monkeypatch.setattr("jalrekha.services.node_assessment.shutil.which", lambda _value: "/usr/bin/ffmpeg")
    monkeypatch.setattr("jalrekha.services.node_assessment.subprocess.run", fake_run)

    extracted = _run_ffmpeg_extract(video_path, output_dir, max_frames=1, sample_seconds=300, max_side=512)

    assert extracted == [output_dir / "node-frame-001.png"]
    assert len(commands) == 2
    assert any(part.startswith("fps=1/300,") for part in commands[0])
    assert any(part.startswith("scale=") for part in commands[1])


def test_assessment_engine_falls_back_when_runner_unavailable(tmp_path: Path):
    image_path = tmp_path / "synthetic.jpg"
    _build_test_image(image_path)

    class NullRunner:
        def assess(self, pack: TemporalEvidencePack):
            return None

    engine = NodeAssessmentEngine(builder=TemporalEvidenceBuilder(), runner=NullRunner())
    result = engine.assess_video(_site(), str(image_path), _calibration(), source_type="frame")

    assert result.verdict.fallback_used is True
    assert result.verdict.runner_mode == "multimodal-unavailable-fallback"
    assert result.verdict.assessment_level == "yellow"
    assert Path(result.evidence_pack.artifact_pack.manifest_path).exists()


def test_ollama_runner_multimodal_mode_parses_json_payload(monkeypatch, tmp_path: Path):
    image_path = tmp_path / "synthetic.jpg"
    _build_test_image(image_path)
    monkeypatch.setenv("JALREKHA_LLM_ENABLED", "true")
    monkeypatch.setenv("JALREKHA_MULTIMODAL_ENABLED", "true")
    monkeypatch.setenv("JALREKHA_MULTIMODAL_MODEL", "gemma4:e2b")
    monkeypatch.setenv("JALREKHA_MULTIMODAL_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("JALREKHA_MULTIMODAL_IMAGE_MAX_SIDE", "512")
    monkeypatch.setenv("JALREKHA_MULTIMODAL_NUM_CTX", "1024")
    monkeypatch.setenv("JALREKHA_MULTIMODAL_NUM_PREDICT", "192")
    monkeypatch.setenv("JALREKHA_MULTIMODAL_TIMEOUT_SECONDS", "30")
    settings_module.get_settings.cache_clear()

    class FakeLLM:
        @staticmethod
        def _extract_json(content):
            import json

            return json.loads(content)

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "message": {
                    "content": (
                        '{"assessment_level":"orange","assessment_score":0.76,'
                        '"temporal_summary":"La imagen muestra agua alta junto al puente.",'
                        '"reasoning_summary":"Gemma detecta ocupacion del cauce y riesgo sobre infraestructura.",'
                        '"reasoning_steps":["mirar linea de agua","comparar con puente","escalar"],'
                        '"critical_evidence":{"waterline_ratio":0.76,"crossed_critical_line":false,'
                        '"rise_velocity":0.0,"confidence":0.82,"visual_cues":["agua alta"]}}'
                    )
                }
            }

    def fake_post(self, *_a, **_k):
        return FakeResponse()

    import httpx

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    runner = OllamaGemmaRunner(FakeLLM())
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

    verdict = runner.assess(pack)

    assert verdict is not None
    assert verdict.assessment_level == "orange"
    assert 0.75 < verdict.assessment_score < 0.77
    assert verdict.runner_mode == "ollama-multimodal-temporal"
    assert verdict.fallback_used is False
