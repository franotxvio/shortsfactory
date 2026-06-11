from __future__ import annotations

import subprocess
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.deps import get_video_production_service
from app.core.config import Settings
from app.main import app
from app.models.core import AssetPool, CostLog, Script, Video
from app.models.enums import VideoStageStatus, WorkflowStatus
from app.schemas.video_production import VideoProductionResponse
from app.services.llm_types import LLMResult, LLMUsage
from app.services.script_engine import ScriptEngineService
from app.services.tts_worker import TTSWorker
from app.services.video_production import VideoProductionResult, VideoProductionService


@dataclass
class FakeOpenAIJSONClient:
    calls: list[tuple[str, str, int, str]]

    async def generate_json(self, *, payload, model: str) -> LLMResult:
        self.calls.append((payload.system_prompt, payload.user_prompt, payload.max_tokens, model))
        lower_prompt = payload.system_prompt.lower()

        if "idea" in lower_prompt:
            content = {"idea": "Explique uma curiosidade simples em formato curto.", "angle": "curiosidade", "title": "Ideia curta"}
        elif "hook" in lower_prompt:
            content = {"hook": "Voce ja percebeu isso em menos de 10 segundos?", "alt_hook": "Isso vai mudar sua forma de ver o tema."}
        elif "script" in lower_prompt:
            content = {
                "title": "Roteiro enxuto",
                "script": "Abra com a curiosidade, desenvolva em tres pontos e feche com uma frase forte.",
                "beats": ["hook", "explicacao", "fecho"],
            }
        else:
            content = {
                "risk_score": 0.23,
                "decision": "approved",
                "reasons": ["Tema seguro", "Sem sinais de risco"],
                "allowed_topics": ["educacao"],
            }

        return LLMResult(
            content=content,
            model=model,
            request_id="req_test",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=20),
            raw_content='{"ok": true}',
        )


@dataclass
class FakeTTSClient:
    audio_bytes: bytes

    async def generate_tts_audio(self, *, text: str, model: str, voice: str) -> tuple[bytes, str]:
        return self.audio_bytes, "tts_req_1"


@dataclass
class FakeVideoProductionService:
    async def produce_full_video(self, *, video_id: int, auto_approve_preview: bool = True) -> VideoProductionResult:
        return VideoProductionResult(
            video_id=video_id,
            audio_path="storage/audio/fake.mp3",
            caption_path="storage/captions/fake.srt",
            preview_path="storage/renders/previews/fake.mp4",
            final_path="storage/renders/finals/fake.mp4",
            asset_path="storage/assets/system-default-background.png",
        )


def _build_mp3_bytes(tmp_path: Path) -> bytes:
    mp3_path = tmp_path / "tts.mp3"
    command = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=44100:cl=mono",
        "-t",
        "2",
        "-q:a",
        "9",
        "-acodec",
        "libmp3lame",
        str(mp3_path),
    ]
    subprocess.run(command, capture_output=True, text=True, check=True)
    return mp3_path.read_bytes()


async def _create_approved_script(db_session) -> Video:
    fake_llm = FakeOpenAIJSONClient(calls=[])
    service = ScriptEngineService(session=db_session, llm_client=fake_llm)
    result = await service.create_test_script(
        topic="Como aprender Python",
        channel_slug="test-channel",
        channel_name="Test Channel",
        video_title="Teste 1",
    )
    video = await db_session.get(Video, result.video_id)
    assert video is not None
    assert video.stage_status == VideoStageStatus.SCRIPT_APPROVED
    return video


@pytest.mark.asyncio
async def test_full_video_pipeline_generates_local_artifacts(db_session, tmp_path) -> None:
    await _create_approved_script(db_session)
    audio_bytes = _build_mp3_bytes(tmp_path)
    fake_tts_client = FakeTTSClient(audio_bytes=audio_bytes)

    settings = Settings(
        local_storage_path=tmp_path / "storage",
        asset_pool_path=tmp_path / "storage" / "assets",
        audio_output_path=tmp_path / "storage" / "audio",
        caption_output_path=tmp_path / "storage" / "captions",
        preview_output_path=tmp_path / "storage" / "renders" / "previews",
        final_output_path=tmp_path / "storage" / "renders" / "finals",
        whisper_model_path=tmp_path / "storage" / "models" / "missing.bin",
        ffmpeg_path="ffmpeg",
        openai_api_key="sk-test",
    )

    tts_worker = TTSWorker(session=db_session, client=fake_tts_client, settings=settings)
    production_service = VideoProductionService(session=db_session, settings=settings, tts_worker=tts_worker)

    video = await db_session.scalar(select(Video).where(Video.slug.like("como-aprender-python-%")))
    assert video is not None

    result = await production_service.produce_full_video(video_id=video.id)

    assert Path(result.audio_path).exists()
    assert Path(result.caption_path).exists()
    assert Path(result.preview_path).exists()
    assert Path(result.final_path).exists()
    assert Path(result.asset_path).exists()

    refreshed_video = await db_session.get(Video, video.id)
    assert refreshed_video is not None
    assert refreshed_video.stage_status == VideoStageStatus.FINAL_RENDERED
    assert refreshed_video.status == WorkflowStatus.COMPLETED
    assert refreshed_video.preview_approved_at is not None
    assert refreshed_video.audio_path == result.audio_path
    assert refreshed_video.caption_path == result.caption_path
    assert refreshed_video.preview_path == result.preview_path
    assert refreshed_video.final_path == result.final_path

    asset_count = await db_session.scalar(select(func.count()).select_from(AssetPool))
    cost_log_count = await db_session.scalar(select(func.count()).select_from(CostLog))
    script_count = await db_session.scalar(select(func.count()).select_from(Script))

    assert asset_count == 1
    assert cost_log_count == 5
    assert script_count == 1


def test_internal_video_route_returns_response() -> None:
    app.dependency_overrides[get_video_production_service] = lambda: FakeVideoProductionService()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/internal/videos/123/produce",
                json={"auto_approve_preview": True},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = VideoProductionResponse.model_validate(response.json())
    assert body.video_id == 123
    assert body.final_path.endswith("fake.mp4")
