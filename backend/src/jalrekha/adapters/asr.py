"""Audio transcription adapters.

Wraps faster-whisper for on-device ASR of volunteer voice notes. Lazy-loads
the model on first call. All exceptions resolve to ``None`` so an ASR
failure never blocks alert generation; the caller falls back to whatever
``transcript_text`` was supplied.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

from jalrekha.core.settings import get_settings


_LOGGER = logging.getLogger(__name__)


class AudioTranscriptionAdapter(Protocol):
    def transcribe(self, audio_path: str | Path) -> str | None: ...


class FasterWhisperASRAdapter:
    """Faster-Whisper backed ASR. Caches the model on first use."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._model = None
        self._max_seconds = 30.0

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel  # type: ignore
        except Exception as exc:  # pragma: no cover - dep installed in venv
            _LOGGER.warning("faster-whisper not importable: %s", exc)
            return None
        try:
            cache_dir = self.settings.asr_model_cache_dir
            cache_dir.mkdir(parents=True, exist_ok=True)
            self._model = WhisperModel(
                self.settings.asr_model_size,
                device="cpu",
                compute_type="int8",
                download_root=str(cache_dir),
            )
        except Exception as exc:
            _LOGGER.warning("Whisper model load failed: %s", exc)
            self._model = None
        return self._model

    def transcribe(self, audio_path: str | Path) -> str | None:
        if not self.settings.asr_enabled:
            return None
        path = Path(audio_path)
        if not path.exists() or path.stat().st_size == 0:
            return None
        model = self._ensure_model()
        if model is None:
            return None
        try:
            segments, _info = model.transcribe(
                str(path),
                language="es",
                beam_size=1,
                vad_filter=True,
                clip_timestamps=[0.0, self._max_seconds],
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()
            return text or None
        except Exception as exc:
            _LOGGER.warning("Whisper transcribe failed: %s", exc)
            return None
