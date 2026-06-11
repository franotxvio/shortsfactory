from dataclasses import asdict

from fastapi import APIRouter, Depends

from app.api.deps import get_video_production_service
from app.schemas.video_production import VideoProductionRequest, VideoProductionResponse
from app.services.video_production import VideoProductionService

router = APIRouter(prefix="/videos", tags=["internal-videos"])


@router.post("/{video_id}/produce", response_model=VideoProductionResponse)
async def produce_video(
    video_id: int,
    payload: VideoProductionRequest,
    service: VideoProductionService = Depends(get_video_production_service),
) -> VideoProductionResponse:
    result = await service.produce_full_video(
        video_id=video_id,
        auto_approve_preview=payload.auto_approve_preview,
    )
    return VideoProductionResponse.model_validate(asdict(result))
