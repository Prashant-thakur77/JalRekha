from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlparse
from typing import Any

import httpx

from jalrekha.core.settings import get_settings


@dataclass
class LLMHealth:
    enabled: bool
    reachable: bool
    base_url: str
    model: str
    detail: str


class OpenAICompatibleLLM:
    def __init__(self) -> None:
        self.settings = get_settings()

    def health(self) -> LLMHealth:
        if not self.settings.llm_enabled:
            return LLMHealth(False, False, self.settings.llm_base_url, self.settings.llm_model, "disabled by env")

        try:
            with httpx.Client(timeout=min(self.settings.llm_timeout_seconds, 5.0)) as client:
                response = client.get(f"{self.settings.llm_base_url.rstrip('/')}/models")
                response.raise_for_status()
            return LLMHealth(True, True, self.settings.llm_base_url, self.settings.llm_model, "ok")
        except Exception as exc:  # pragma: no cover - network errors are environment dependent
            return LLMHealth(True, False, self.settings.llm_base_url, self.settings.llm_model, str(exc))

    def structure_observation(self, transcript_text: str, site_context: dict[str, Any]) -> dict[str, Any] | None:
        if not self.settings.llm_enabled or not transcript_text.strip():
            return None

        schema_hint = {
            "water_level_category": "low|medium|high|critical|unknown",
            "trend": "rising|falling|stable|unknown",
            "road_status": "open|caution|blocked|unknown",
            "bridge_status": "open|unsafe|closed|unknown",
            "homes_affected": False,
            "urgency": "low|normal|high|critical",
            "summary": "one concise sentence",
            "confidence": 0.0,
        }
        prompt = (
            f"Site context: {json.dumps(site_context, ensure_ascii=True)}\n"
            f"Transcript: {transcript_text}\n"
            f"Return JSON matching this template: {json.dumps(schema_hint, ensure_ascii=True)}"
        )

        native_payload = self._call_ollama_native(prompt)
        if native_payload is not None:
            return native_payload

        messages = [
            {
                "role": "system",
                "content": (
                    "You extract structured flood observations. Return only valid JSON with no markdown, "
                    "no prose, and keys exactly as requested. If data is missing, use conservative unknown values."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ]
        payload = {
            "model": self.settings.llm_model,
            "temperature": 0,
            "max_tokens": 240,
            "messages": messages,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(timeout=self.settings.llm_timeout_seconds) as client:
                response = client.post(
                    f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            return self._extract_json(content)
        except Exception:
            return None

    def generate_text(self, system_prompt: str, user_prompt: str, max_tokens: int = 320) -> str | None:
        """Plain-text generation for reasoning chains. Returns None if LLM unavailable."""
        if not self.settings.llm_enabled:
            return None

        if self._looks_like_ollama():
            try:
                with httpx.Client(timeout=self.settings.llm_timeout_seconds) as client:
                    response = client.post(
                        self._ollama_chat_url(),
                        json={
                            "model": self.settings.llm_model,
                            "stream": False,
                            # Gemma 4 routes output into message.thinking by default;
                            # disable so message.content is populated directly.
                            "think": False,
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt},
                            ],
                            "options": {"temperature": 0.2, "num_predict": max_tokens},
                        },
                    )
                    response.raise_for_status()
                body = response.json()
                content = body.get("message", {}).get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()
            except Exception:
                pass

        try:
            with httpx.Client(timeout=self.settings.llm_timeout_seconds) as client:
                response = client.post(
                    f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.settings.llm_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.settings.llm_model,
                        "temperature": 0.2,
                        "max_tokens": max_tokens,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                    },
                )
                response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
            content = str(content).strip()
            return content or None
        except Exception:
            return None

    def _call_ollama_native(self, prompt: str) -> dict[str, Any] | None:
        if not self._looks_like_ollama():
            return None

        payload = {
            "model": self.settings.llm_model,
            "stream": False,
            "format": "json",
            # Gemma 4 routes output into message.thinking by default;
            # disable so message.content holds the JSON we asked for.
            "think": False,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return only a JSON object. Do not wrap it in markdown. "
                        "Use conservative unknown values when needed."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            "options": {"num_predict": 320},
        }
        try:
            with httpx.Client(timeout=self.settings.llm_timeout_seconds) as client:
                response = client.post(self._ollama_chat_url(), json=payload)
                response.raise_for_status()
            body = response.json()
            content = body.get("message", {}).get("content")
            return self._extract_json(content)
        except Exception:
            return None

    def _looks_like_ollama(self) -> bool:
        parsed = urlparse(self.settings.llm_base_url)
        return parsed.hostname in {"127.0.0.1", "localhost"} and parsed.port == 11434

    def _ollama_chat_url(self) -> str:
        return self.settings.llm_base_url.rstrip("/").removesuffix("/v1") + "/api/chat"

    @staticmethod
    def _extract_json(content: Any) -> dict[str, Any] | None:
        if isinstance(content, list):
            text = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        else:
            text = str(content)
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end < start:
            return None
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
