from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.api.deps import get_video_production_service
from app.models.core import Channel, Video
from app.schemas.video_production import (
    AssetListResponse,
    AssetRegisterRequest,
    AssetResponse,
    ChannelPresetListResponse,
    ChannelPresetResponse,
    ChannelPresetUpsertRequest,
    VideoJobEnqueueRequest,
    VideoJobResponse,
    VideoCreateRequest,
    VideoAssetSelectionRequest,
    VideoListResponse,
    VideoPipelineResponse,
    VideoPreviewRequest,
    VideoPreviewRegenerateRequest,
    VideoScriptUpdateRequest,
    VideoProductionRequest,
    VideoProductionResponse,
    VideoStepRequest,
)
from app.services.video_production import VideoProductionService
from app.services.video_job_queue import VideoJobQueueService, get_video_job_queue_service

router = APIRouter(prefix="/videos", tags=["internal-videos"])
DEMO_CHANNEL_SLUGS = {"internal-test", "manual-test"}


def _raise_http_error(error: ValueError) -> None:
    message = str(error)
    status_code = 404 if "not found" in message.lower() else 400
    raise HTTPException(status_code=status_code, detail=message)


async def _commit_if_available(service: VideoProductionService) -> None:
    session = getattr(service, "session", None)
    if session is not None:
        await session.commit()


async def _rollback_if_available(service: VideoProductionService) -> None:
    session = getattr(service, "session", None)
    if session is not None:
        await session.rollback()


def _is_production_env() -> bool:
    return get_settings().app_env.lower() == "production"


def _ensure_jobs_allowed() -> None:
    if _is_production_env():
        raise HTTPException(status_code=403, detail="Background jobs are disabled in production")


async def _is_demo_video(service: VideoProductionService, *, video_id: int) -> bool:
    session = getattr(service, "session", None)
    if session is None:
        return False
    statement = (
        select(Video)
        .options(selectinload(Video.channel))
        .where(Video.id == video_id)
    )
    video = await session.scalar(statement)
    if video is None or video.channel is None:
        return False
    channel_slug = video.channel.slug.lower()
    return channel_slug in DEMO_CHANNEL_SLUGS or channel_slug.endswith("-demo") or channel_slug.endswith("-test")


async def _with_demo_flag(
    service: VideoProductionService,
    payload: VideoPipelineResponse | VideoProductionResponse,
) -> VideoPipelineResponse | VideoProductionResponse:
    return payload.model_copy(update={"is_demo": await _is_demo_video(service, video_id=payload.video_id)})


def _asset_response_from_record(record) -> AssetResponse:
    return AssetResponse.model_validate(asdict(record))


def _channel_preset_response_from_record(record) -> ChannelPresetResponse:
    return ChannelPresetResponse.model_validate(asdict(record))


def _job_response_from_record(record) -> VideoJobResponse:
    return VideoJobResponse.model_validate(asdict(record))


def _resolve_storage_file_path(path_value: str) -> Path:
    if not path_value:
        raise HTTPException(status_code=400, detail="Path is required")

    requested_path = Path(path_value)
    if requested_path.is_absolute():
        raise HTTPException(status_code=400, detail="Only relative storage paths are allowed")

    settings = get_settings()
    storage_root = settings.local_storage_path.resolve()
    storage_base = storage_root.parent
    resolved_path = (storage_base / requested_path).resolve()
    try:
        resolved_path.relative_to(storage_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Path must stay within the configured storage directory") from exc

    if not resolved_path.exists() or not resolved_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    allowed_suffixes = {".mp4", ".srt", ".png", ".jpg", ".jpeg", ".webp"}
    if resolved_path.suffix.lower() not in allowed_suffixes:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    return resolved_path


@router.get("/files")
async def get_storage_file(path: str) -> FileResponse:
    resolved_path = _resolve_storage_file_path(path)
    suffix = resolved_path.suffix.lower()
    media_types = {
        ".mp4": "video/mp4",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".srt": "text/plain; charset=utf-8",
    }
    content_disposition_type = "inline" if suffix in {".mp4", ".png", ".jpg", ".jpeg", ".webp", ".srt"} else "attachment"
    return FileResponse(
        resolved_path,
        filename=resolved_path.name,
        media_type=media_types.get(suffix, "application/octet-stream"),
        content_disposition_type=content_disposition_type,
    )


@router.post("/demo/reset")
async def reset_demo_videos(
    confirm: bool = Body(default=False, embed=True),
    service: VideoProductionService = Depends(get_video_production_service),
) -> dict[str, int]:
    if _is_production_env():
        raise HTTPException(status_code=403, detail="Demo cleanup is disabled in production")
    if not confirm:
        raise HTTPException(status_code=400, detail="Explicit confirm=true is required")

    session = getattr(service, "session", None)
    if session is None:
        raise HTTPException(status_code=500, detail="Database session unavailable")

    statement = (
        select(Video)
        .options(selectinload(Video.channel), selectinload(Video.scripts))
        .join(Video.channel)
        .where(Channel.slug.in_(DEMO_CHANNEL_SLUGS))
    )
    videos = (await session.scalars(statement)).unique().all()
    deleted_videos = 0
    deleted_scripts = 0
    for video in videos:
        deleted_videos += 1
        deleted_scripts += len(video.scripts)
        await session.delete(video)
    await session.flush()
    await _commit_if_available(service)
    return {"deleted_videos": deleted_videos, "deleted_scripts": deleted_scripts}


@router.get("/assets", response_model=AssetListResponse)
async def list_assets(
    channel_slug: str | None = None,
    topic: str | None = None,
    tags: list[str] | None = Query(default=None),
    service: VideoProductionService = Depends(get_video_production_service),
) -> AssetListResponse:
    try:
        assets = await service.list_assets(channel_slug=channel_slug, topic=topic, tags=tags)
    except ValueError as error:
        _raise_http_error(error)
    return AssetListResponse(items=[_asset_response_from_record(asset) for asset in assets])


@router.post("/assets/register-local", response_model=AssetResponse)
async def register_local_asset(
    payload: AssetRegisterRequest,
    service: VideoProductionService = Depends(get_video_production_service),
) -> AssetResponse:
    try:
        asset = await service.register_local_asset(
            relative_path=payload.file_path,
            name=payload.name,
            slug=payload.slug,
            asset_type=payload.asset_type,
            license_name=payload.license_name,
            license_url=payload.license_url,
            channel_slug=payload.channel_slug,
            topic=payload.topic,
            tags=payload.tags,
        )
        await _commit_if_available(service)
    except ValueError as error:
        await _rollback_if_available(service)
        _raise_http_error(error)
    return _asset_response_from_record(asset)


@router.get("/channel-presets", response_model=ChannelPresetListResponse)
async def list_channel_presets(
    service: VideoProductionService = Depends(get_video_production_service),
) -> ChannelPresetListResponse:
    try:
        presets = await service.list_channel_presets()
    except ValueError as error:
        _raise_http_error(error)
    return ChannelPresetListResponse(items=[_channel_preset_response_from_record(item) for item in presets])


@router.post("/channel-presets", response_model=ChannelPresetResponse)
async def upsert_channel_preset(
    payload: ChannelPresetUpsertRequest,
    service: VideoProductionService = Depends(get_video_production_service),
) -> ChannelPresetResponse:
    try:
        preset = await service.upsert_channel_preset(
            channel_slug=payload.channel_slug,
            channel_name=payload.channel_name,
            default_topic_style=payload.default_topic_style,
            default_visual_template=payload.default_visual_template,
            default_asset_slug=payload.default_asset_slug,
            default_cta=payload.default_cta,
            target_duration_seconds=payload.target_duration_seconds,
        )
    except ValueError as error:
        _raise_http_error(error)
    return _channel_preset_response_from_record(preset)


@router.get("/{video_id}/jobs/latest", response_model=VideoJobResponse)
async def get_latest_video_job(
    video_id: int,
    service: VideoProductionService = Depends(get_video_production_service),
    queue_service: VideoJobQueueService = Depends(get_video_job_queue_service),
) -> VideoJobResponse:
    _ensure_jobs_allowed()
    try:
        await service.get_status(video_id=video_id)
        job = await queue_service.get_latest_job_for_video(video_id=video_id)
    except ValueError as error:
        _raise_http_error(error)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_response_from_record(job)


@router.get("/jobs/{job_id}", response_model=VideoJobResponse)
async def get_job_status(
    job_id: str,
    queue_service: VideoJobQueueService = Depends(get_video_job_queue_service),
) -> VideoJobResponse:
    _ensure_jobs_allowed()
    job = await queue_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_response_from_record(job)


@router.post("/{video_id}/jobs/produce", response_model=VideoJobResponse)
async def enqueue_full_pipeline_job(
    video_id: int,
    payload: VideoJobEnqueueRequest,
    service: VideoProductionService = Depends(get_video_production_service),
    queue_service: VideoJobQueueService = Depends(get_video_job_queue_service),
) -> VideoJobResponse:
    _ensure_jobs_allowed()
    try:
        await service.get_status(video_id=video_id)
        job = await queue_service.enqueue_full_pipeline_fake(video_id=video_id, visual_template=payload.visual_template)
    except ValueError as error:
        _raise_http_error(error)
    return _job_response_from_record(job)


@router.post("/{video_id}/jobs/{job_type}", response_model=VideoJobResponse)
async def enqueue_step_job(
    video_id: int,
    job_type: str,
    payload: VideoJobEnqueueRequest,
    service: VideoProductionService = Depends(get_video_production_service),
    queue_service: VideoJobQueueService = Depends(get_video_job_queue_service),
) -> VideoJobResponse:
    _ensure_jobs_allowed()
    try:
        await service.get_status(video_id=video_id)
        job = await queue_service.enqueue_step(video_id=video_id, job_type=job_type, visual_template=payload.visual_template)
    except ValueError as error:
        _raise_http_error(error)
    return _job_response_from_record(job)


@router.get("", response_model=VideoListResponse)
async def list_videos(
    limit: int = 20,
    service: VideoProductionService = Depends(get_video_production_service),
) -> VideoListResponse:
    try:
        result = await service.list_recent_videos(limit=limit)
    except ValueError as error:
        _raise_http_error(error)
    items = []
    for item in result:
        response = VideoPipelineResponse.model_validate(asdict(item))
        response = await _with_demo_flag(service, response)
        items.append(response)
    return VideoListResponse(items=items)


@router.post("/{video_id}/produce", response_model=VideoProductionResponse)
async def produce_video(
    video_id: int,
    payload: VideoProductionRequest,
    service: VideoProductionService = Depends(get_video_production_service),
) -> VideoProductionResponse:
    try:
        produced = await service.produce_full_video(
            video_id=video_id,
            auto_approve_preview=payload.auto_approve_preview,
            visual_template=payload.visual_template,
        )
        await _commit_if_available(service)
        get_status = getattr(service, "get_status", None)
        if callable(get_status):
            result = await get_status(video_id=video_id)
            response = VideoProductionResponse.model_validate(asdict(result))
            response = await _with_demo_flag(service, response)
            return response
    except ValueError as error:
        await _rollback_if_available(service)
        _raise_http_error(error)
    response = VideoProductionResponse.model_validate(asdict(produced))
    response = await _with_demo_flag(service, response)
    return response


@router.patch("/{video_id}/script", response_model=VideoPipelineResponse)
async def update_video_script(
    video_id: int,
    payload: VideoScriptUpdateRequest,
    service: VideoProductionService = Depends(get_video_production_service),
) -> VideoPipelineResponse:
    try:
        updated = await service.update_script(
            video_id=video_id,
            script_text=payload.script_text,
            hook=payload.hook,
            body_blocks=payload.body_blocks,
            call_to_action=payload.call_to_action,
            estimated_duration_seconds=payload.estimated_duration_seconds,
            style_tone=payload.style_tone,
        )
        await _commit_if_available(service)
    except ValueError as error:
        await _rollback_if_available(service)
        _raise_http_error(error)
    response = VideoPipelineResponse.model_validate(asdict(updated))
    return await _with_demo_flag(service, response)


@router.post("/test", response_model=VideoPipelineResponse)
async def create_test_video(
    payload: VideoCreateRequest,
    service: VideoProductionService = Depends(get_video_production_service),
) -> VideoPipelineResponse:
    try:
        result = await service.create_local_test_video(
            topic=payload.topic,
            channel_slug=payload.channel_slug,
            channel_name=payload.channel_name,
            video_title=payload.video_title,
            execution_mode=payload.execution_mode,
        )
        await _commit_if_available(service)
    except ValueError as error:
        await _rollback_if_available(service)
        _raise_http_error(error)
    response = VideoPipelineResponse.model_validate(asdict(result))
    return await _with_demo_flag(service, response)


@router.post("/{video_id}/tts", response_model=VideoPipelineResponse)
async def run_tts(
    video_id: int,
    payload: VideoStepRequest,
    service: VideoProductionService = Depends(get_video_production_service),
) -> VideoPipelineResponse:
    try:
        await service.run_tts(video_id=video_id, execution_mode=payload.execution_mode)
        await _commit_if_available(service)
        result = await service.get_status(video_id=video_id)
    except ValueError as error:
        await _rollback_if_available(service)
        _raise_http_error(error)
    response = VideoPipelineResponse.model_validate(asdict(result))
    return await _with_demo_flag(service, response)


@router.post("/{video_id}/captions", response_model=VideoPipelineResponse)
async def run_captions(
    video_id: int,
    payload: VideoStepRequest,
    service: VideoProductionService = Depends(get_video_production_service),
) -> VideoPipelineResponse:
    try:
        await service.generate_captions(video_id=video_id, execution_mode=payload.execution_mode)
        await _commit_if_available(service)
        result = await service.get_status(video_id=video_id)
    except ValueError as error:
        await _rollback_if_available(service)
        _raise_http_error(error)
    response = VideoPipelineResponse.model_validate(asdict(result))
    return await _with_demo_flag(service, response)


@router.post("/{video_id}/asset", response_model=VideoPipelineResponse)
async def select_asset(
    video_id: int,
    payload: VideoAssetSelectionRequest | None = Body(default=None),
    service: VideoProductionService = Depends(get_video_production_service),
) -> VideoPipelineResponse:
    try:
        await service.select_asset(
            video_id=video_id,
            asset_id=payload.asset_id if payload is not None else None,
            asset_slug=payload.asset_slug if payload is not None else None,
            channel_slug=payload.channel_slug if payload is not None else None,
            topic=payload.topic if payload is not None else None,
            tags=payload.tags if payload is not None else None,
        )
        await _commit_if_available(service)
        result = await service.get_status(video_id=video_id)
    except ValueError as error:
        await _rollback_if_available(service)
        _raise_http_error(error)
    response = VideoPipelineResponse.model_validate(asdict(result))
    return await _with_demo_flag(service, response)


@router.post("/{video_id}/preview", response_model=VideoPipelineResponse)
async def render_preview(
    video_id: int,
    payload: VideoPreviewRequest | None = Body(default=None),
    service: VideoProductionService = Depends(get_video_production_service),
) -> VideoPipelineResponse:
    try:
        await service.render_preview(
            video_id=video_id,
            visual_template=payload.visual_template if payload is not None else None,
        )
        await _commit_if_available(service)
        result = await service.get_status(video_id=video_id)
    except ValueError as error:
        await _rollback_if_available(service)
        _raise_http_error(error)
    response = VideoPipelineResponse.model_validate(asdict(result))
    return await _with_demo_flag(service, response)


@router.post("/{video_id}/preview/regenerate", response_model=VideoPipelineResponse)
async def regenerate_preview(
    video_id: int,
    payload: VideoPreviewRegenerateRequest | None = Body(default=None),
    service: VideoProductionService = Depends(get_video_production_service),
) -> VideoPipelineResponse:
    try:
        result = await service.regenerate_preview(
            video_id=video_id,
            asset_id=payload.asset_id if payload is not None else None,
            visual_template=payload.visual_template if payload is not None else None,
        )
        await _commit_if_available(service)
    except ValueError as error:
        await _rollback_if_available(service)
        _raise_http_error(error)
    response = VideoPipelineResponse.model_validate(asdict(result))
    return await _with_demo_flag(service, response)


@router.post("/{video_id}/approve-preview", response_model=VideoPipelineResponse)
async def approve_preview(
    video_id: int,
    service: VideoProductionService = Depends(get_video_production_service),
) -> VideoPipelineResponse:
    try:
        await service.approve_preview(video_id=video_id)
        await _commit_if_available(service)
        result = await service.get_status(video_id=video_id)
    except ValueError as error:
        await _rollback_if_available(service)
        _raise_http_error(error)
    response = VideoPipelineResponse.model_validate(asdict(result))
    return await _with_demo_flag(service, response)


@router.post("/{video_id}/final", response_model=VideoPipelineResponse)
async def render_final(
    video_id: int,
    service: VideoProductionService = Depends(get_video_production_service),
) -> VideoPipelineResponse:
    try:
        await service.render_final(video_id=video_id)
        await _commit_if_available(service)
        result = await service.get_status(video_id=video_id)
    except ValueError as error:
        await _rollback_if_available(service)
        _raise_http_error(error)
    response = VideoPipelineResponse.model_validate(asdict(result))
    return await _with_demo_flag(service, response)


@router.get("/{video_id}/status", response_model=VideoPipelineResponse)
async def get_status(
    video_id: int,
    service: VideoProductionService = Depends(get_video_production_service),
) -> VideoPipelineResponse:
    try:
        result = await service.get_status(video_id=video_id)
    except ValueError as error:
        _raise_http_error(error)
    response = VideoPipelineResponse.model_validate(asdict(result))
    return await _with_demo_flag(service, response)
