from __future__ import annotations

import importlib
import json
import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jalrekha.core.settings import get_settings


_LOGGER = logging.getLogger(__name__)
_LITERT_SEND_MESSAGE_REUSE_ERROR = "litert_lm_conversation_send_message failed"


@dataclass
class LiteRTNodeHealth:
    enabled: bool
    reachable: bool
    provider: str
    backend: str
    model: str
    model_path: str
    detail: str


class LiteRTNodeRuntime:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._lock = threading.RLock()
        self._module = None
        self._engines: dict[str, Any] = {}
        self.last_error_type: str | None = None
        self.last_error_detail: str | None = None
        self.last_response_type: str | None = None
        self.last_response_preview: str | None = None

    @property
    def model_name(self) -> str:
        return self.settings.node_model_path.name

    def health(self) -> LiteRTNodeHealth:
        if self.settings.node_provider != "litert":
            return LiteRTNodeHealth(
                enabled=False,
                reachable=False,
                provider=self.settings.node_provider,
                backend=self.settings.node_backend,
                model=self.model_name,
                model_path=str(self.settings.node_model_path),
                detail="JalRekha Node provider is not litert",
            )

        try:
            self._import_litert_module()
        except Exception as exc:
            return LiteRTNodeHealth(
                enabled=True,
                reachable=False,
                provider="litert",
                backend=self.settings.node_backend,
                model=self.model_name,
                model_path=str(self.settings.node_model_path),
                detail=str(exc),
            )

        if not self.settings.node_model_path.exists():
            return LiteRTNodeHealth(
                enabled=True,
                reachable=False,
                provider="litert",
                backend=self.settings.node_backend,
                model=self.model_name,
                model_path=str(self.settings.node_model_path),
                detail="model file not found",
            )

        return LiteRTNodeHealth(
            enabled=True,
            reachable=True,
            provider="litert",
            backend=self.settings.node_backend,
            model=self.model_name,
            model_path=str(self.settings.node_model_path),
            detail="ready",
        )

    def generate_text(self, system_prompt: str, user_prompt: str, max_tokens: int = 320) -> str | None:
        _ = max_tokens
        message = {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": self._combine_prompts(system_prompt, user_prompt),
                }
            ],
        }
        response = self._send_message(message, max_tokens=max_tokens)
        return self._extract_text(response)

    def generate_json(self, system_prompt: str, user_prompt: str, max_tokens: int = 320) -> dict[str, Any] | None:
        raw = self.generate_text(system_prompt, user_prompt, max_tokens=max_tokens)
        return self._extract_json(raw)

    def generate_multimodal_json(
        self,
        system_prompt: str,
        user_prompt: str,
        image_paths: list[str | Path],
        max_tokens: int = 320,
    ) -> dict[str, Any] | None:
        _ = max_tokens
        parts: list[dict[str, str]] = []
        for path in image_paths:
            path_obj = Path(path)
            if path_obj.exists():
                parts.append({"type": "image", "path": str(path_obj)})
        if not parts:
            return None
        parts.append({"type": "text", "text": self._combine_prompts(system_prompt, user_prompt)})
        response = self._send_message(
            {"role": "user", "content": parts},
            multimodal=True,
            max_tokens=max_tokens,
        )
        return self._extract_json(self._extract_text(response))

    def _send_message(self, message: Any, *, multimodal: bool = False, max_tokens: int = 320) -> Any:
        _ = max_tokens
        self.last_error_type = None
        self.last_error_detail = None
        self.last_response_type = None
        self.last_response_preview = None
        if self.settings.node_provider != "litert":
            return None

        try:
            with self._lock:
                return self._send_message_locked(message, multimodal=multimodal)
        except Exception as exc:
            self.last_error_type = type(exc).__name__
            self.last_error_detail = str(exc)
            if self._is_engine_reuse_error(exc):
                self._discard_engine(multimodal=multimodal)
                try:
                    with self._lock:
                        response = self._send_message_locked(message, multimodal=multimodal)
                    self.last_error_type = None
                    self.last_error_detail = None
                    return response
                except Exception as retry_exc:
                    self.last_error_type = type(retry_exc).__name__
                    self.last_error_detail = str(retry_exc)
                    exc = retry_exc
            _LOGGER.warning(
                "LiteRT node message failed mode=%s backend=%s model=%s error=%s",
                "multimodal" if multimodal else "text",
                self.settings.node_backend,
                self.model_name,
                exc,
            )
            return None

    def _send_message_locked(self, message: Any, *, multimodal: bool = False) -> Any:
        engine = self._ensure_engine(multimodal=multimodal)
        if engine is None:
            return None
        with engine.create_conversation() as conversation:
            response = conversation.send_message(message)
            self.last_response_type = type(response).__name__
            self.last_response_preview = str(response)[:500] if response is not None else None
            return response

    def _discard_engine(self, *, multimodal: bool = False) -> None:
        engine_key = "multimodal" if multimodal else "text"
        self._engines.pop(engine_key, None)

    @staticmethod
    def _is_engine_reuse_error(exc: Exception) -> bool:
        return _LITERT_SEND_MESSAGE_REUSE_ERROR in str(exc)

    def _ensure_engine(self, *, multimodal: bool = False) -> Any:
        engine_key = "multimodal" if multimodal else "text"
        if engine_key in self._engines:
            return self._engines[engine_key]

        litert_lm = self._import_litert_module()
        backend_value = self._resolve_backend(litert_lm, multimodal=multimodal)
        max_num_tokens = (
            self.settings.node_multimodal_max_output_tokens
            if multimodal
            else self.settings.node_max_output_tokens
        )
        kwargs: dict[str, Any] = {
            "backend": backend_value,
            "cache_dir": str(self.settings.node_cache_dir),
            "max_num_tokens": max(1, int(max_num_tokens)),
            "enable_speculative_decoding": self.settings.node_enable_speculative_decoding,
        }
        if multimodal:
            kwargs["vision_backend"] = self._resolve_vision_backend(litert_lm)
        self.settings.node_cache_dir.mkdir(parents=True, exist_ok=True)
        engine = litert_lm.Engine(str(self.settings.node_model_path), **kwargs)
        if hasattr(engine, "__enter__"):
            engine = engine.__enter__()
        self._engines[engine_key] = engine
        return engine

    def _resolve_backend(self, litert_lm: Any, *, multimodal: bool = False) -> Any:
        backend_name = (
            self.settings.node_multimodal_backend
            if multimodal
            else self.settings.node_backend
        ).strip().upper()
        backend = getattr(getattr(litert_lm, "Backend"), backend_name)
        return backend

    def _resolve_vision_backend(self, litert_lm: Any) -> Any:
        backend_name = self.settings.node_multimodal_vision_backend.strip().upper()
        backend = getattr(getattr(litert_lm, "Backend"), backend_name)
        return backend

    def _import_litert_module(self) -> Any:
        if self._module is None:
            self._module = importlib.import_module("litert_lm")
        return self._module

    @staticmethod
    def _combine_prompts(system_prompt: str, user_prompt: str) -> str:
        return f"{system_prompt.strip()}\n\n{user_prompt.strip()}".strip()

    @staticmethod
    def _extract_text(response: Any) -> str | None:
        if response is None:
            return None
        if isinstance(response, dict):
            content = response.get("content")
            if isinstance(content, list):
                text = "".join(
                    str(part.get("text", ""))
                    for part in content
                    if isinstance(part, dict)
                ).strip()
                return LiteRTNodeRuntime._strip_special_tokens(text) or None
        return LiteRTNodeRuntime._strip_special_tokens(str(response).strip()) or None

    @staticmethod
    def _strip_special_tokens(text: str) -> str:
        if not text:
            return text
        cleaned = re.sub(
            r"<(pad|bos|eos|start_of_turn|end_of_turn|unk|s|/s)>",
            "",
            text,
            flags=re.IGNORECASE,
        )
        return cleaned.strip()

    @staticmethod
    def _extract_json(raw: str | None) -> dict[str, Any] | None:
        if not raw:
            return None
        start = raw.find("{")
        if start == -1:
            return None
        end = raw.rfind("}")
        if end == -1 or end < start:
            candidate = raw[start:]
        else:
            candidate = raw[start : end + 1]
        open_braces = candidate.count("{")
        close_braces = candidate.count("}")
        if open_braces > close_braces:
            candidate = f"{candidate}{'}' * (open_braces - close_braces)}"
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return None
