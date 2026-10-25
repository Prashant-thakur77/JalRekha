"""AWS adapters (Bedrock, Polly, SNS, CloudWatch) with offline fallbacks.

Everything here is optional. ``NADISAATHI_AWS_ENABLED=1`` turns the cloud
calls on (the Graviton deployment sets it). With it off, or when boto3 or a
service is unavailable, each function returns a labelled fallback and the
agent keeps working: that is the "cloud down" path in the autonomy policy.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from jalrekha.services.storage import get_upload_dir

_LOGGER = logging.getLogger(__name__)

# Estimated on-demand prices, USD per 1,000 tokens (Amazon Nova Lite, us-east-1).
# Used only to label trace costs as estimates; see docs/COOL.md for the source.
NOVA_LITE_IN_PER_1K = 0.00006
NOVA_LITE_OUT_PER_1K = 0.00024


def aws_enabled() -> bool:
    return os.environ.get("NADISAATHI_AWS_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}


def region_name() -> str:
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"


@lru_cache(maxsize=8)
def client(service: str):
    if not aws_enabled():
        return None
    try:
        import boto3  # noqa: PLC0415
        from botocore.config import Config  # noqa: PLC0415

        return boto3.client(service, region_name=region_name(), config=Config(retries={"max_attempts": 2}, connect_timeout=3, read_timeout=20))
    except Exception as exc:  # boto3 missing or no credentials
        _LOGGER.warning("aws client %s unavailable: %s", service, exc)
        return None


# --------------------------------------------------------------------- metrics
def put_metrics(values: dict[str, float], site_id: str | None = None) -> None:
    """Fire-and-forget CloudWatch custom metrics in namespace NadiSaathi."""
    cw = client("cloudwatch")
    if cw is None:
        return

    def _send() -> None:
        try:
            data = []
            for name, v in values.items():
                dims = [{"Name": "Service", "Value": "agent"}]
                data.append({"MetricName": name, "Value": float(v), "Dimensions": dims})
            cw.put_metric_data(Namespace="NadiSaathi", MetricData=data)
        except Exception as exc:
            _LOGGER.debug("put_metric_data failed: %s", exc)

    threading.Thread(target=_send, daemon=True).start()


# ------------------------------------------------------------------------ VLM
class VLMUnavailable(RuntimeError):
    pass


@dataclass
class VLMAnswer:
    raw_text: str
    model: str
    latency_ms: float
    input_tokens: int = 0
    output_tokens: int = 0
    scripted: bool = False

    @property
    def cost_usd_est(self) -> float:
        return round(self.input_tokens / 1000 * NOVA_LITE_IN_PER_1K + self.output_tokens / 1000 * NOVA_LITE_OUT_PER_1K, 6)


GAUGE_PROMPT = (
    "You are checking a river staff-gauge camera image. The gauge marks are labelled in metres "
    "from {lo:.1f} m at the bottom to {hi:.1f} m at the top. Read where the water surface meets the gauge. "
    'Reply with JSON only: {{"stage_m": <number or null>, "confidence": <0..1>, "visible": <true|false>}}. '
    "If you cannot see the waterline, use null."
)


class BedrockVLM:
    """Amazon Bedrock Converse with an image (Nova Lite by default)."""

    def __init__(self, model_id: str | None = None) -> None:
        self.model_id = model_id or os.environ.get("NADISAATHI_BEDROCK_MODEL", "us.amazon.nova-lite-v1:0")

    @property
    def name(self) -> str:
        return f"bedrock:{self.model_id}"

    def ask_gauge(self, jpeg: bytes, lo_m: float, hi_m: float) -> VLMAnswer:
        br = client("bedrock-runtime")
        if br is None:
            raise VLMUnavailable("bedrock disabled or no credentials (NADISAATHI_AWS_ENABLED!=1)")
        t0 = time.perf_counter()
        try:
            resp = br.converse(
                modelId=self.model_id,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"image": {"format": "jpeg", "source": {"bytes": jpeg}}},
                            {"text": GAUGE_PROMPT.format(lo=lo_m, hi=hi_m)},
                        ],
                    }
                ],
                inferenceConfig={"maxTokens": 120, "temperature": 0.0},
            )
        except Exception as exc:
            raise VLMUnavailable(f"bedrock call failed: {type(exc).__name__}: {str(exc)[:160]}") from exc
        text = "".join(c.get("text", "") for c in resp["output"]["message"]["content"])
        usage = resp.get("usage", {})
        return VLMAnswer(text, self.name, (time.perf_counter() - t0) * 1000, usage.get("inputTokens", 0), usage.get("outputTokens", 0))


class ScriptedVLM:
    """A fixed reply, used by scenario replays and tests (always labelled scripted)."""

    def __init__(self, reply: str, name: str = "scripted-test-vlm") -> None:
        self.reply = reply
        self.name = name

    def ask_gauge(self, jpeg: bytes, lo_m: float, hi_m: float) -> VLMAnswer:
        return VLMAnswer(self.reply, self.name, 0.0, scripted=True)


class UnavailableVLM:
    name = "none"

    def ask_gauge(self, jpeg: bytes, lo_m: float, hi_m: float) -> VLMAnswer:
        raise VLMUnavailable("no VLM configured")


_JSON_OBJ = re.compile(r"\{[^{}]*\}", re.S)


def parse_gauge_answer(text: str) -> dict[str, Any]:
    """Strict parse: one JSON object with the three allowed keys, nothing else trusted.

    Instructions inside the reply are ignored by construction (only these
    fields are read); extra prose is reported so the trace shows it.
    """
    m = _JSON_OBJ.search(text or "")
    out: dict[str, Any] = {"ok": False, "stage_m": None, "confidence": 0.0, "visible": False, "extra_text": False, "reason": ""}
    if not m:
        out["reason"] = "no_json_object"
        return out
    leftover = (text[: m.start()] + text[m.end():]).strip()
    out["extra_text"] = bool(leftover)
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        out["reason"] = "invalid_json"
        return out
    if not isinstance(obj, dict) or set(obj) - {"stage_m", "confidence", "visible"}:
        out["reason"] = "unexpected_keys"
        return out
    stage = obj.get("stage_m")
    if stage is not None and not isinstance(stage, (int, float)):
        out["reason"] = "stage_not_numeric"
        return out
    conf = obj.get("confidence", 0.0)
    out.update(
        ok=True,
        stage_m=None if stage is None else float(stage),
        confidence=float(conf) if isinstance(conf, (int, float)) else 0.0,
        visible=bool(obj.get("visible", stage is not None)),
        reason="parsed",
    )
    return out


def default_vlm():
    return BedrockVLM() if aws_enabled() else UnavailableVLM()


# ------------------------------------------------------------------------ TTS
def tts_enabled() -> bool:
    return os.environ.get("NADISAATHI_TTS_ENABLED", "1" if aws_enabled() else "0").strip().lower() in {"1", "true", "yes", "on"}


def synthesize(text: str, tts: dict[str, Any] | None) -> dict[str, Any]:
    """Audio for one alert text. Returns {url, provider, note} or {url: None, ...}."""
    if not tts or not tts_enabled():
        return {"url": None, "provider": None, "note": "voice disabled on this host"}
    audio_dir = get_upload_dir() / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(f"{tts}|{text}".encode()).hexdigest()[:20]
    provider = tts.get("provider")
    if provider == "polly":
        out = audio_dir / f"{key}.mp3"
        if not out.exists():
            polly = client("polly")
            if polly is None:
                return _espeak(text, "hi", audio_dir, key, note="Polly unavailable; offline voice used")
            try:
                resp = polly.synthesize_speech(
                    Text=text, OutputFormat="mp3", VoiceId=tts.get("voice", "Kajal"),
                    Engine=tts.get("engine", "neural"), LanguageCode=tts.get("language_code", "hi-IN"),
                )
                out.write_bytes(resp["AudioStream"].read())
            except Exception as exc:
                _LOGGER.warning("polly failed: %s", exc)
                return _espeak(text, "hi", audio_dir, key, note=f"Polly failed ({type(exc).__name__}); offline voice used")
        return {"url": f"/uploads/audio/{out.name}", "provider": f"polly:{tts.get('voice')}:{tts.get('language_code')}", "note": tts.get("note")}
    if provider == "espeak-ng":
        return _espeak(text, tts.get("voice", "ne"), audio_dir, key, note=tts.get("note"))
    return {"url": None, "provider": None, "note": "no TTS for this language"}


def _espeak(text: str, voice: str, audio_dir: Path, key: str, note: str | None = None) -> dict[str, Any]:
    exe = shutil.which("espeak-ng")
    if exe is None:
        return {"url": None, "provider": None, "note": "espeak-ng not installed; text only"}
    out = audio_dir / f"{key}-{voice}.wav"
    if not out.exists():
        subprocess.run([exe, "-v", voice, "-s", "140", "-w", str(out), text], capture_output=True, timeout=30, check=False)
    if not out.exists():
        return {"url": None, "provider": None, "note": "espeak-ng failed; text only"}
    return {"url": f"/uploads/audio/{out.name}", "provider": f"espeak-ng:{voice}", "note": note}


# ------------------------------------------------------------------------ SMS
def sms_recipients() -> list[str]:
    """Verified test numbers only (SNS sandbox); never real community lists in the pilot."""
    raw = os.environ.get("NADISAATHI_SMS_TEST_NUMBERS", "")
    return [n.strip() for n in raw.split(",") if re.fullmatch(r"\+\d{8,15}", n.strip())]


def send_sms(text: str) -> dict[str, Any]:
    nums = sms_recipients()
    sns = client("sns")
    if sns is None or not nums:
        return {"channel": "sms", "status": "simulated", "note": "no SNS or no verified test numbers configured; message logged only"}
    results = []
    for n in nums:
        try:
            r = sns.publish(PhoneNumber=n, Message=text, MessageAttributes={"AWS.SNS.SMS.SMSType": {"DataType": "String", "StringValue": "Transactional"}})
            results.append({"to": n[:-4] + "****", "message_id": r.get("MessageId")})
        except Exception as exc:
            results.append({"to": n[:-4] + "****", "error": type(exc).__name__})
    ok = any("message_id" in r for r in results)
    return {"channel": "sms", "status": "sent" if ok else "failed", "results": results}


def notify_operators(subject: str, message: str) -> dict[str, Any]:
    topic = os.environ.get("NADISAATHI_SNS_TOPIC_ARN")
    sns = client("sns")
    if sns is None or not topic:
        return {"channel": "operator_topic", "status": "simulated"}
    try:
        sns.publish(TopicArn=topic, Subject=subject[:99], Message=message)
        return {"channel": "operator_topic", "status": "sent"}
    except Exception as exc:
        return {"channel": "operator_topic", "status": "failed", "error": type(exc).__name__}


def image_b64(jpeg: bytes) -> str:
    return base64.b64encode(jpeg).decode()


# ----------------------------------------------------------- escalation (SFN)
def start_escalation(approval_id: int, title: str, wait_s: int = 900) -> dict[str, Any]:
    """Start the Step Functions timer that re-notifies operators while an approval waits."""
    sfn = client("stepfunctions")
    stack = os.environ.get("NADISAATHI_STACK")
    topic = os.environ.get("NADISAATHI_SNS_TOPIC_ARN", "")
    if sfn is None or not stack or topic.count(":") < 5:
        return {"status": "skipped", "note": "Step Functions not configured on this host"}
    account = topic.split(":")[4]
    arn = f"arn:aws:states:{region_name()}:{account}:stateMachine:{stack}-approval-escalation"
    try:
        r = sfn.start_execution(stateMachineArn=arn, name=f"approval-{approval_id}-{int(time.time())}",
                                input=json.dumps({"approval_id": approval_id, "title": title[:200], "wait_s": wait_s, "attempt": 0}))
        return {"status": "started", "execution": r["executionArn"].split(":")[-1]}
    except Exception as exc:
        return {"status": "failed", "error": type(exc).__name__}
