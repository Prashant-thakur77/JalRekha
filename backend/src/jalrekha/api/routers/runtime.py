from __future__ import annotations

from fastapi import APIRouter

from jalrekha.api import deps
from jalrekha.core.settings import get_settings
from jalrekha.schemas.api import ConnectivityStatus, RuntimeStatus


router = APIRouter(tags=["runtime"])


@router.get("/health")
async def health() -> dict[str, object]:
    settings = get_settings()
    from jalrekha.adapters import claude

    # In the cloud the language model is Claude; the older flag covers the on-device model only.
    return {
        "status": "ok",
        "node_profile": settings.node_profile,
        "llm_enabled": settings.llm_enabled or claude.available(),
        "llm": f"claude:{claude.MODEL}" if claude.available() else ("on-device" if settings.llm_enabled else None),
        "hydromet_enabled": settings.hydromet_enabled,
    }


@router.get("/settings/runtime", response_model=RuntimeStatus)
async def get_runtime_status() -> RuntimeStatus:
    settings = get_settings()
    llm_status = deps.llm_client.health()
    node_status = deps.node_runtime.health()
    hydromet_status = deps.external_data_service.health()
    node_engine_ready = node_status.reachable
    node_engine_detail = node_status.detail
    if settings.node_provider == "ollama":
        node_engine_ready = llm_status.reachable
        node_engine_detail = (
            f"Ollama development runtime for JalRekha Node. "
            f"LLM detail: {llm_status.detail}"
        )
    p1_runtime_ready = settings.node_provider == "litert" and node_engine_ready
    return RuntimeStatus(
        is_online=deps.is_online,
        llm={
            "enabled": llm_status.enabled,
            "reachable": llm_status.reachable,
            "base_url": llm_status.base_url,
            "model": llm_status.model,
            "detail": llm_status.detail,
        },
        node={
            "node_profile": settings.node_profile,
            "provider": node_status.provider,
            "backend": node_status.backend,
            "vision_backend": settings.node_vision_backend,
            "multimodal_backend": settings.node_multimodal_backend,
            "multimodal_vision_backend": settings.node_multimodal_vision_backend,
            "speculative_decoding": settings.node_enable_speculative_decoding,
            "max_output_tokens": settings.node_max_output_tokens,
            "multimodal_max_output_tokens": settings.node_multimodal_max_output_tokens,
            "engine_ready": node_engine_ready,
            "engine_detail": node_engine_detail,
            "counts_for_p1": p1_runtime_ready,
            "p1_runtime_ready": p1_runtime_ready,
            "p1_evidence_required": (
                "Runtime readiness only. Benchmark evidence requires a completed "
                "JalRekha Node analysis with runner.mode=litert-multimodal-temporal."
            ),
            "model_path": node_status.model_path,
            "cache_dir": str(settings.node_cache_dir),
            "data_dir": str(settings.data_dir),
            "ffmpeg_bin": settings.ffmpeg_bin,
            "multimodal_enabled": settings.node_multimodal_enabled,
            "multimodal_verifier_enabled": settings.node_multimodal_verifier_enabled,
            "multimodal_base_url": settings.node_multimodal_base_url,
            "multimodal_model": settings.node_multimodal_model,
            "multimodal_min_interval_seconds": settings.node_multimodal_min_interval_seconds,
            "multimodal_score_threshold": settings.node_multimodal_score_threshold,
            "multimodal_confidence_threshold": settings.node_multimodal_confidence_threshold,
            "multimodal_image_max_side": settings.node_multimodal_image_max_side,
            "multimodal_max_frames": settings.node_multimodal_max_frames,
            "multimodal_frame_sample_seconds": settings.node_multimodal_frame_sample_seconds,
            "multimodal_num_ctx": settings.node_multimodal_num_ctx,
            "multimodal_timeout_seconds": settings.node_multimodal_timeout_seconds,
            "max_curated_frames": settings.node_max_curated_frames,
            "artifact_retention_days": settings.node_artifact_retention_days,
        },
        hydromet={
            "enabled": hydromet_status.enabled,
            "reachable": hydromet_status.reachable,
            "detail": hydromet_status.detail,
        },
    )


@router.get("/settings/connectivity")
async def get_connectivity() -> ConnectivityStatus:
    return ConnectivityStatus(is_online=deps.is_online)


@router.post("/settings/connectivity")
async def set_connectivity(payload: ConnectivityStatus) -> ConnectivityStatus:
    deps.is_online = payload.is_online
    return ConnectivityStatus(is_online=deps.is_online)
