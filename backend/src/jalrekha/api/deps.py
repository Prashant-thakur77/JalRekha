from __future__ import annotations

import json
from datetime import datetime

from sqlmodel import SQLModel, Session, select

from jalrekha.adapters.asr import FasterWhisperASRAdapter
from jalrekha.adapters.image_assessment import GemmaImageAssessmentAdapter
from jalrekha.adapters.litert_node import LiteRTNodeRuntime
from jalrekha.adapters.llm import OpenAICompatibleLLM
from jalrekha.adapters.text_structuring_gemma_fewshot import GemmaFewShotTextStructurer
from jalrekha.adapters.video_assessment import LiteRTGemmaRunner, OllamaGemmaRunner
from jalrekha.core.settings import get_settings
from jalrekha.models.domain import SyncQueueItem
from jalrekha.services.node_assessment import NodeAssessmentEngine, TemporalEvidenceBuilder
from jalrekha.services.external_data import ExternalDataService


def _build_node_runtime_components() -> tuple[object, GemmaImageAssessmentAdapter]:
    settings = get_settings()
    provider = settings.node_provider
    if provider == "litert":
        return (
            LiteRTGemmaRunner(node_runtime),
            GemmaImageAssessmentAdapter(runtime=node_runtime, force_embedded=True),
        )
    if provider == "ollama":
        return (
            OllamaGemmaRunner(llm_client),
            GemmaImageAssessmentAdapter(),
        )
    raise ValueError(
        f"Unsupported JALREKHA_NODE_PROVIDER={provider!r}. Expected 'litert' or 'ollama'."
    )


llm_client = OpenAICompatibleLLM()
node_runtime = LiteRTNodeRuntime()
text_structurer = GemmaFewShotTextStructurer(llm_client)
node_runner, node_image_assessor = _build_node_runtime_components()
image_assessor = GemmaImageAssessmentAdapter()
asr_client = FasterWhisperASRAdapter()
external_data_service = ExternalDataService()
node_engine = NodeAssessmentEngine(
    builder=TemporalEvidenceBuilder(),
    runner=node_runner,
)

is_online = True


def get_decision_runtime() -> OpenAICompatibleLLM | LiteRTNodeRuntime:
    """Central reasoning + actuator runtime.

    Topology: JalRekha Node (fixed-cam Pi) runs the LiteRT vision engine; the central
    backend runs the larger Gemma 4 model via Ollama for fusion reasoning and
    actuator JSON tool selection. Vision and central reasoning are split engines.
    """
    if get_settings().node_provider == "litert":
        return node_runtime
    return llm_client


def enqueue_entity(session: Session, entity_type: str, entity: SQLModel) -> None:
    entity_id = getattr(entity, "id", None)
    if entity_id is None:
        return
    existing = session.exec(
        select(SyncQueueItem)
        .where(SyncQueueItem.entity_type == entity_type)
        .where(SyncQueueItem.entity_id == entity_id)
        .where(SyncQueueItem.status == "pending")
    ).first()
    if existing is not None:
        existing.payload = json.dumps(entity.model_dump(mode="json"), ensure_ascii=True)
        existing.updated_at = datetime.utcnow()
        existing.last_error = None
        session.add(existing)
        return
    queue_item = SyncQueueItem(
        entity_type=entity_type,
        entity_id=entity_id,
        payload=json.dumps(entity.model_dump(mode="json"), ensure_ascii=True),
    )
    session.add(queue_item)

