from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.api.deps import get_video_production_service
from app.schemas.video_production import (
    VideoCreateRequest,
    VideoListResponse,
    VideoPipelineResponse,
    VideoProductionRequest,
    VideoProductionResponse,
    VideoStepRequest,
)
from app.services.video_production import VideoProductionService

router = APIRouter(prefix="/videos", tags=["internal-videos"])


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
    return FileResponse(resolved_path, filename=resolved_path.name)


@router.get("", response_model=VideoListResponse)
async def list_videos(
    limit: int = 20,
    service: VideoProductionService = Depends(get_video_production_service),
) -> VideoListResponse:
    try:
        result = await service.list_recent_videos(limit=limit)
    except ValueError as error:
        _raise_http_error(error)
    return VideoListResponse(items=[VideoPipelineResponse.model_validate(asdict(item)) for item in result])


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
        )
        await _commit_if_available(service)
        get_status = getattr(service, "get_status", None)
        if callable(get_status):
            result = await get_status(video_id=video_id)
            return VideoProductionResponse.model_validate(asdict(result))
    except ValueError as error:
        await _rollback_if_available(service)
        _raise_http_error(error)
    return VideoProductionResponse.model_validate(asdict(produced))


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
    return VideoPipelineResponse.model_validate(asdict(result))


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
    return VideoPipelineResponse.model_validate(asdict(result))


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
    return VideoPipelineResponse.model_validate(asdict(result))


@router.post("/{video_id}/asset", response_model=VideoPipelineResponse)
async def select_asset(
    video_id: int,
    service: VideoProductionService = Depends(get_video_production_service),
) -> VideoPipelineResponse:
    try:
        await service.select_asset(video_id=video_id)
        await _commit_if_available(service)
        result = await service.get_status(video_id=video_id)
    except ValueError as error:
        await _rollback_if_available(service)
        _raise_http_error(error)
    return VideoPipelineResponse.model_validate(asdict(result))


@router.post("/{video_id}/preview", response_model=VideoPipelineResponse)
async def render_preview(
    video_id: int,
    service: VideoProductionService = Depends(get_video_production_service),
) -> VideoPipelineResponse:
    try:
        await service.render_preview(video_id=video_id)
        await _commit_if_available(service)
        result = await service.get_status(video_id=video_id)
    except ValueError as error:
        await _rollback_if_available(service)
        _raise_http_error(error)
    return VideoPipelineResponse.model_validate(asdict(result))


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
    return VideoPipelineResponse.model_validate(asdict(result))


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
    return VideoPipelineResponse.model_validate(asdict(result))


@router.get("/{video_id}/status", response_model=VideoPipelineResponse)
async def get_status(
    video_id: int,
    service: VideoProductionService = Depends(get_video_production_service),
) -> VideoPipelineResponse:
    try:
        result = await service.get_status(video_id=video_id)
    except ValueError as error:
        _raise_http_error(error)
    return VideoPipelineResponse.model_validate(asdict(result))
