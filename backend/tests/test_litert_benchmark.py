from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


def _load_benchmark_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "litert_benchmark.py"
    spec = importlib.util.spec_from_file_location("litert_benchmark", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_benchmark_record_marks_unobservable_token_metrics(monkeypatch, tmp_path: Path):
    module = _load_benchmark_module()

    model_path = tmp_path / "gemma-4-E2B-it.litertlm"
    model_path.write_bytes(b"fake-model")

    settings = SimpleNamespace(
        node_provider="litert",
        node_model_path=model_path,
        node_backend="gpu",
        node_multimodal_backend="cpu",
        node_multimodal_vision_backend="cpu",
        node_enable_speculative_decoding=True,
        node_max_output_tokens=1024,
        node_multimodal_max_output_tokens=2048,
    )

    class FakeRuntime:
        model_name = model_path.name

        def __init__(self):
            self.settings = settings

        def health(self):
            return SimpleNamespace(reachable=True, detail="ready")

        def generate_text(self, _system_prompt, _user_prompt, max_tokens=320):
            return "respuesta LiteRT"

    monkeypatch.setattr(module, "LiteRTNodeRuntime", FakeRuntime)
    monkeypatch.setattr(module, "_rss_mb", lambda: 321.0)

    records = module.run_benchmark_modes(["text"], repeats=2)

    assert [record["run_temperature"] for record in records] == ["cold", "warm"]
    assert all(record["pass"] is True for record in records)
    assert all(record["model"] == "gemma-4-E2B-it.litertlm" for record in records)
    assert all(record["backend"] == "gpu" for record in records)
    assert all(record["multimodal_backend"] == "cpu" for record in records)
    assert all(record["vision_backend"] == "cpu" for record in records)
    assert all(record["speculative_decoding_enabled"] is True for record in records)
    assert all(record["rss_peak_mb"] == 321.0 for record in records)
    assert all(record["output_token_count"] is None for record in records)
    assert all(record["decode_tok_s"] is None for record in records)
    assert all(record["ttft_seconds"] is None for record in records)
    assert all("not exposed" in record["token_count_detail"] for record in records)
    assert all("no streaming" in record["ttft_detail"] for record in records)


def test_benchmark_record_reports_multimodal_missing_image(tmp_path: Path):
    module = _load_benchmark_module()

    records = module.run_benchmark_modes(["image"], image_path=tmp_path / "missing.jpg")

    assert len(records) == 1
    record = records[0]
    assert record["mode"] == "image"
    assert record["pass"] is False
    assert "image path does not exist" in record["error_detail"]


def test_benchmark_records_runtime_error_detail(monkeypatch, tmp_path: Path):
    module = _load_benchmark_module()

    model_path = tmp_path / "gemma-4-E2B-it.litertlm"
    model_path.write_bytes(b"fake-model")
    settings = SimpleNamespace(
        node_provider="litert",
        node_model_path=model_path,
        node_backend="gpu",
        node_multimodal_backend="cpu",
        node_multimodal_vision_backend="cpu",
        node_enable_speculative_decoding=True,
        node_max_output_tokens=1024,
        node_multimodal_max_output_tokens=2048,
    )

    class FakeRuntime:
        model_name = model_path.name

        def __init__(self):
            self.settings = settings
            self.last_error_type = "RuntimeError"
            self.last_error_detail = "engine conversation closed"
            self.last_response_type = None
            self.last_response_preview = None

        def health(self):
            return SimpleNamespace(reachable=True, detail="ready")

        def generate_text(self, _system_prompt, _user_prompt, max_tokens=320):
            return None

    monkeypatch.setattr(module, "LiteRTNodeRuntime", FakeRuntime)

    record = module.run_benchmark_modes(["text"], repeats=1)[0]

    assert record["pass"] is False
    assert "RuntimeError" in record["error_detail"]
    assert "engine conversation closed" in record["error_detail"]


def test_benchmark_can_use_fresh_runtime_per_run(monkeypatch, tmp_path: Path):
    module = _load_benchmark_module()

    model_path = tmp_path / "gemma-4-E2B-it.litertlm"
    model_path.write_bytes(b"fake-model")
    settings = SimpleNamespace(
        node_provider="litert",
        node_model_path=model_path,
        node_backend="gpu",
        node_multimodal_backend="cpu",
        node_multimodal_vision_backend="cpu",
        node_enable_speculative_decoding=True,
        node_max_output_tokens=1024,
        node_multimodal_max_output_tokens=2048,
    )
    init_count = 0

    class FakeRuntime:
        model_name = model_path.name

        def __init__(self):
            nonlocal init_count
            init_count += 1
            self.settings = settings
            self.last_error_type = None
            self.last_error_detail = None
            self.last_response_type = None
            self.last_response_preview = None

        def health(self):
            return SimpleNamespace(reachable=True, detail="ready")

        def generate_text(self, _system_prompt, _user_prompt, max_tokens=320):
            return "ok"

    monkeypatch.setattr(module, "LiteRTNodeRuntime", FakeRuntime)

    records = module.run_benchmark_modes(["text"], repeats=2, fresh_runtime_per_run=True)

    assert init_count == 2
    assert [record["runtime_reuse_mode"] for record in records] == ["fresh-per-run", "fresh-per-run"]
    assert [record["run_temperature"] for record in records] == ["cold", "cold"]
