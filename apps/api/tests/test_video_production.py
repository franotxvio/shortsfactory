from __future__ import annotations

import subprocess
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import get_async_session, get_video_production_service
from app.core.config import Settings
from app.main import app
from app.models.core import AssetPool, CostLog, Script, Video
from app.models.enums import VideoExecutionMode, VideoStageStatus, WorkflowStatus
from app.schemas.video_production import VideoListResponse
from app.schemas.video_production import VideoPipelineResponse
from app.schemas.video_production import VideoProductionResponse
from app.services.llm_types import LLMResult, LLMUsage
from app.services.openai_client import OpenAIJSONClient
from app.services.script_engine import ScriptEngineService
from app.services.tts_worker import TTSWorker
from app.services.video_production import VideoProductionResult, VideoProductionService
import app.api.routes.internal_videos as internal_videos_routes


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


@pytest.mark.asyncio
async def test_internal_manual_video_pipeline_runs_fake_mode(db_session, temp_database_url: str) -> None:
    async def _override_async_session():
        engine = create_async_engine(temp_database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                yield session
        finally:
            await engine.dispose()

    app.dependency_overrides[get_async_session] = _override_async_session
    try:
        with TestClient(app) as client:
            create_response = client.post(
                "/internal/videos/test",
                json={
                    "topic": "Como aprender Python",
                    "channel_slug": "manual-test",
                    "channel_name": "Manual Test",
                    "video_title": "Teste manual",
                    "execution_mode": "fake",
                },
            )
            assert create_response.status_code == 200
            created = VideoPipelineResponse.model_validate(create_response.json())
            assert created.stage_status == VideoStageStatus.SCRIPT_APPROVED.value
            assert created.script_id is not None

            video_id = created.video_id

            tts_response = client.post(f"/internal/videos/{video_id}/tts", json={"execution_mode": "fake"})
            assert tts_response.status_code == 200
            tts_state = VideoPipelineResponse.model_validate(tts_response.json())
            assert tts_state.stage_status == VideoStageStatus.TTS_DONE.value
            assert Path(tts_state.audio_path or "").exists()

            captions_response = client.post(f"/internal/videos/{video_id}/captions", json={"execution_mode": "fake"})
            assert captions_response.status_code == 200
            captions_state = VideoPipelineResponse.model_validate(captions_response.json())
            assert captions_state.stage_status == VideoStageStatus.CAPTION_DONE.value
            assert Path(captions_state.caption_path or "").exists()

            asset_response = client.post(f"/internal/videos/{video_id}/asset")
            assert asset_response.status_code == 200
            asset_state = VideoPipelineResponse.model_validate(asset_response.json())
            assert asset_state.stage_status == VideoStageStatus.ASSET_READY.value
            assert Path(asset_state.asset_path or "").exists()

            preview_response = client.post(f"/internal/videos/{video_id}/preview")
            assert preview_response.status_code == 200
            preview_state = VideoPipelineResponse.model_validate(preview_response.json())
            assert preview_state.stage_status == VideoStageStatus.PREVIEW_READY.value
            assert Path(preview_state.preview_path or "").exists()

            approve_response = client.post(f"/internal/videos/{video_id}/approve-preview")
            assert approve_response.status_code == 200
            approve_state = VideoPipelineResponse.model_validate(approve_response.json())
            assert approve_state.stage_status == VideoStageStatus.PREVIEW_APPROVED.value
            assert approve_state.preview_approved_at is not None

            final_response = client.post(f"/internal/videos/{video_id}/final")
            assert final_response.status_code == 200
            final_state = VideoPipelineResponse.model_validate(final_response.json())
            assert final_state.stage_status == VideoStageStatus.FINAL_RENDERED.value
            assert Path(final_state.final_path or "").exists()

            status_response = client.get(f"/internal/videos/{video_id}/status")
            assert status_response.status_code == 200
            status_state = VideoPipelineResponse.model_validate(status_response.json())
            assert status_state.stage_status == VideoStageStatus.FINAL_RENDERED.value
            assert status_state.audio_path == tts_state.audio_path
            assert status_state.caption_path == captions_state.caption_path
            assert status_state.preview_path == preview_state.preview_path
            assert status_state.final_path == final_state.final_path
    finally:
        app.dependency_overrides.clear()

    refreshed_video = await db_session.get(Video, video_id)
    assert refreshed_video is not None
    assert refreshed_video.stage_status == VideoStageStatus.FINAL_RENDERED
    assert refreshed_video.audio_path == status_state.audio_path
    assert refreshed_video.caption_path == status_state.caption_path
    assert refreshed_video.preview_path == status_state.preview_path
    assert refreshed_video.final_path == status_state.final_path

    cost_log_count = await db_session.scalar(select(func.count()).select_from(CostLog))
    assert cost_log_count == 0


@pytest.mark.asyncio
async def test_internal_video_list_returns_recent_items(db_session, temp_database_url: str) -> None:
    async def _override_async_session():
        engine = create_async_engine(temp_database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                yield session
        finally:
            await engine.dispose()

    app.dependency_overrides[get_async_session] = _override_async_session
    try:
        with TestClient(app) as client:
            create_response = client.post(
                "/internal/videos/test",
                json={
                    "topic": "Como aprender Python",
                    "channel_slug": "manual-test",
                    "channel_name": "Manual Test",
                    "video_title": "Teste manual",
                    "execution_mode": "fake",
                },
            )
            assert create_response.status_code == 200
            created = VideoPipelineResponse.model_validate(create_response.json())

            produce_response = client.post(
                f"/internal/videos/{created.video_id}/produce",
                json={"auto_approve_preview": True, "execution_mode": "fake"},
            )
            assert produce_response.status_code == 200

            list_response = client.get("/internal/videos")
            assert list_response.status_code == 200
            body = VideoListResponse.model_validate(list_response.json())
    finally:
        app.dependency_overrides.clear()

    assert len(body.items) == 1
    item = body.items[0]
    assert item.video_id == created.video_id
    assert item.stage_status == VideoStageStatus.FINAL_RENDERED.value
    assert item.status == WorkflowStatus.COMPLETED.value
    assert item.audio_path is not None
    assert item.caption_path is not None
    assert item.asset_path is not None
    assert item.preview_path is not None
    assert item.final_path is not None


@pytest.mark.asyncio
async def test_internal_video_produce_is_idempotent_after_completion(db_session, temp_database_url: str) -> None:
    async def _override_async_session():
        engine = create_async_engine(temp_database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                yield session
        finally:
            await engine.dispose()

    app.dependency_overrides[get_async_session] = _override_async_session
    try:
        with TestClient(app) as client:
            create_response = client.post(
                "/internal/videos/test",
                json={
                    "topic": "Como aprender Python",
                    "channel_slug": "manual-test",
                    "channel_name": "Manual Test",
                    "video_title": "Teste manual",
                    "execution_mode": "fake",
                },
            )
            assert create_response.status_code == 200
            created = VideoPipelineResponse.model_validate(create_response.json())

            first_produce = client.post(
                f"/internal/videos/{created.video_id}/produce",
                json={"auto_approve_preview": True, "execution_mode": "fake"},
            )
            assert first_produce.status_code == 200
            first_state = VideoPipelineResponse.model_validate(first_produce.json())
            assert first_state.stage_status == VideoStageStatus.FINAL_RENDERED.value

            second_produce = client.post(
                f"/internal/videos/{created.video_id}/produce",
                json={"auto_approve_preview": True, "execution_mode": "fake"},
            )
            assert second_produce.status_code == 200
            second_state = VideoPipelineResponse.model_validate(second_produce.json())
    finally:
        app.dependency_overrides.clear()

    assert second_state.stage_status == VideoStageStatus.FINAL_RENDERED.value
    assert second_state.status == WorkflowStatus.COMPLETED.value
    assert second_state.audio_path == first_state.audio_path
    assert second_state.caption_path == first_state.caption_path
    assert second_state.preview_path == first_state.preview_path
    assert second_state.final_path == first_state.final_path


def test_internal_manual_video_real_mode_requires_api_key() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/internal/videos/test",
            json={
                "topic": "Como aprender Python",
                "execution_mode": "real",
            },
        )

    assert response.status_code == 400


def test_internal_video_preflight_allows_local_dashboard_origin() -> None:
    with TestClient(app) as client:
        response = client.options(
            "/internal/videos/test",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

    assert response.status_code in {200, 204}
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "POST" in response.headers["access-control-allow-methods"]
    assert "content-type" in response.headers["access-control-allow-headers"].lower()


def test_internal_file_endpoint_serves_valid_storage_mp4_inline(tmp_path, monkeypatch) -> None:
    storage_root = tmp_path / "storage"
    preview_path = storage_root / "renders" / "previews" / "demo.mp4"
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    preview_path.write_bytes(b"fake-mp4-content")

    monkeypatch.setattr(
        internal_videos_routes,
        "get_settings",
        lambda: Settings(local_storage_path=storage_root),
    )

    with TestClient(app) as client:
        response = client.get("/internal/videos/files", params={"path": "storage/renders/previews/demo.mp4"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("video/mp4")
    assert response.headers["content-disposition"].lower().startswith("inline")


def test_internal_file_endpoint_blocks_path_traversal(tmp_path, monkeypatch) -> None:
    storage_root = tmp_path / "storage"
    storage_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        internal_videos_routes,
        "get_settings",
        lambda: Settings(local_storage_path=storage_root),
    )

    with TestClient(app) as client:
        response = client.get("/internal/videos/files", params={"path": "../outside.srt"})

    assert response.status_code == 400
    assert "storage directory" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_fake_pipeline_does_not_instantiate_openai(db_session, tmp_path, monkeypatch) -> None:
    await _create_approved_script(db_session)
    video = await db_session.scalar(select(Video).where(Video.slug.like("como-aprender-python-%")))
    assert video is not None

    def _fail_init(*args, **kwargs):  # noqa: ANN001, ANN003
        raise AssertionError("OpenAIJSONClient should not be instantiated in fake mode")

    monkeypatch.setattr(OpenAIJSONClient, "__init__", _fail_init)

    settings = Settings(
        local_storage_path=tmp_path / "storage",
        asset_pool_path=tmp_path / "storage" / "assets",
        audio_output_path=tmp_path / "storage" / "audio",
        caption_output_path=tmp_path / "storage" / "captions",
        preview_output_path=tmp_path / "storage" / "renders" / "previews",
        final_output_path=tmp_path / "storage" / "renders" / "finals",
        whisper_model_path=tmp_path / "storage" / "models" / "missing.bin",
        ffmpeg_path="ffmpeg",
    )

    service = VideoProductionService(session=db_session, settings=settings)
    result = await service.produce_full_video(video_id=video.id)

    assert Path(result.audio_path).exists()
    assert Path(result.final_path).exists()


@pytest.mark.asyncio
async def test_real_pipeline_without_api_key_fails_clear(db_session, tmp_path) -> None:
    settings = Settings(
        local_storage_path=tmp_path / "storage",
        asset_pool_path=tmp_path / "storage" / "assets",
        audio_output_path=tmp_path / "storage" / "audio",
        caption_output_path=tmp_path / "storage" / "captions",
        preview_output_path=tmp_path / "storage" / "renders" / "previews",
        final_output_path=tmp_path / "storage" / "renders" / "finals",
        whisper_model_path=tmp_path / "storage" / "models" / "missing.bin",
        ffmpeg_path="ffmpeg",
    )
    service = VideoProductionService(session=db_session, settings=settings)

    with pytest.raises(ValueError, match="LLM_API_KEY"):
        await service.create_local_test_video(
            topic="Como aprender Python",
            channel_slug="real-mode-test",
            channel_name="Real Mode Test",
            video_title="Teste real",
            execution_mode=VideoExecutionMode.REAL,
        )


@pytest.mark.asyncio
async def test_real_tts_with_mock_records_cost_log(db_session, tmp_path) -> None:
    await _create_approved_script(db_session)
    video = await db_session.scalar(select(Video).where(Video.slug.like("como-aprender-python-%")))
    assert video is not None

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

    tts_worker = TTSWorker(session=db_session, client=fake_tts_client, settings=settings, record_cost_log=True)
    result = await tts_worker.generate(video_id=video.id)

    assert Path(result.audio_path).exists()

    cost_log = await db_session.scalar(select(CostLog).where(CostLog.video_id == video.id, CostLog.operation == "tts"))
    assert cost_log is not None
    assert cost_log.provider == "openai"
    assert cost_log.operation == "tts"
