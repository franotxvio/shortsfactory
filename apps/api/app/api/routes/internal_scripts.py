from dataclasses import asdict

from fastapi import APIRouter, Depends

from app.api.deps import get_script_engine_service
from app.schemas.script_engine import ScriptEngineTestRequest, ScriptEngineTestResponse
from app.services.script_engine import ScriptEngineService

router = APIRouter(prefix="/scripts", tags=["internal-scripts"])


@router.post("/test", response_model=ScriptEngineTestResponse)
async def create_test_script(
    payload: ScriptEngineTestRequest,
    service: ScriptEngineService = Depends(get_script_engine_service),
) -> ScriptEngineTestResponse:
    result = await service.create_test_script(
        topic=payload.topic,
        channel_slug=payload.channel_slug,
        channel_name=payload.channel_name,
        video_title=payload.video_title,
        execution_mode=payload.execution_mode,
    )
    return ScriptEngineTestResponse.model_validate(asdict(result))
