from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import get_async_session, get_video_production_service
from app.core.config import Settings
from app.main import app
from app.models.core import AssetPool, Channel, CostLog, Script, Video
from app.models.enums import LifecycleStatus, LLMProvider, VideoExecutionMode, VideoStageStatus, WorkflowStatus
from app.schemas.video_production import AssetListResponse
from app.schemas.video_production import AssetResponse
from app.schemas.video_production import VideoPerformanceListResponse
from app.schemas.video_production import VideoPerformanceResponse
from app.schemas.video_production import VideoListResponse
from app.schemas.video_production import VideoPipelineResponse
from app.schemas.video_production import VideoProductionResponse
from app.services.llm_types import LLMResult, LLMUsage
from app.services.openai_client import OpenAIJSONClient
from app.services.openai_client import LLMJSONClient
from app.services.video_job_queue import VideoJobQueueService, get_video_job_queue_service
from app.services.script_engine import ScriptEngineService
from app.services.tts_worker import TTSWorker
from app.services.video_production import VideoProductionResult, VideoProductionService
from app.services.youtube_publish_service import get_youtube_auth_status
from app.schemas.video_production import VideoJobResponse
import app.api.routes.internal_videos as internal_videos_routes
import app.services.render_worker as render_worker_module
import app.workers.video_jobs_worker as video_jobs_worker


@dataclass
class FakeOpenAIJSONClient:
    calls: list[tuple[str, str, int, str]]

    async def generate_json(self, *, payload, model: str) -> LLMResult:
        self.calls.append((payload.system_prompt, payload.user_prompt, payload.max_tokens, model))
        lower_prompt = payload.system_prompt.lower()

        if "idea" in lower_prompt:
            content = {
                "idea": "Explique uma curiosidade simples em formato curto.",
                "angle": "curiosidade",
                "title": "Ideia curta",
            }
        elif "hook" in lower_prompt:
            content = {
                "hook": "Voce ja percebeu isso em menos de 10 segundos?",
                "alt_hook": "Isso vai mudar sua forma de ver o tema.",
            }
        elif "script" in lower_prompt:
            hook = "Voce ja viu esse tema por este angulo?"
            body_blocks = [
                "Primeiro, simplifique a ideia central para ganhar atencao rapido.",
                "Depois, mostre um exemplo curto para deixar o assunto pratico.",
                "Em seguida, destaque o ganho direto para manter o ritmo.",
            ]
            call_to_action = "Se isso te ajudou, salva o video e compartilha com alguem."
            content = {
                "title": "Roteiro enxuto",
                "hook": hook,
                "body_blocks": body_blocks,
                "call_to_action": call_to_action,
                "estimated_duration_seconds": 36,
                "style_tone": "didatico e direto",
                "script": "\n\n".join([hook, *body_blocks, call_to_action]),
                "beats": ["hook", "body_1", "body_2", "body_3", "cta"],
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
            raw_content=json.dumps(content),
        )


@dataclass
class FakeTTSClient:
    audio_bytes: bytes

    async def generate_tts_audio(self, *, text: str, model: str, voice: str) -> tuple[bytes, str]:
        return self.audio_bytes, "tts_req_1"


@dataclass
class FakeVideoProductionService:
    async def produce_full_video(
        self,
        *,
        video_id: int,
        auto_approve_preview: bool = True,
        visual_template: str | None = None,
    ) -> VideoProductionResult:
        return VideoProductionResult(
            video_id=video_id,
            audio_path="storage/audio/fake.mp3",
            caption_path="storage/captions/fake.srt",
            preview_path="storage/renders/previews/fake.mp4",
            final_path="storage/renders/finals/fake.mp4",
            asset_path="storage/assets/system-default-background.png",
        )


class FakeRedis:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.values: dict[str, str] = {}
        self.queues: dict[str, list[str]] = {}

    async def hset(self, key: str, mapping: dict[str, str]) -> None:
        self.hashes[key] = dict(mapping)

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    async def set(self, key: str, value: str) -> None:
        self.values[key] = str(value)

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def lpush(self, key: str, value: str) -> None:
        self.queues.setdefault(key, []).insert(0, str(value))

    async def blpop(self, key: str, timeout: int = 0):  # noqa: ANN001
        queue = self.queues.get(key, [])
        if queue:
            return key, queue.pop()
        return None


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


async def _create_video_ready_for_preview(db_session, *, slug_suffix: str = "template") -> Video:
    channel = Channel(name="Template Channel", slug=f"template-{slug_suffix}")
    asset = AssetPool(
        asset_type="background_image",
        name="Template Asset",
        slug=f"template-asset-{slug_suffix}",
        source_url="local",
        source_path=f"storage/assets/manual/template-{slug_suffix}.png",
        license_name="generated-local",
        license_url=None,
        status=LifecycleStatus.ACTIVE,
    )
    video = Video(
        channel=channel,
        title="Template Video",
        slug=f"template-video-{slug_suffix}",
        status=WorkflowStatus.APPROVED,
        stage_status=VideoStageStatus.ASSET_READY,
        asset=asset,
        audio_path=f"storage/audio/template-{slug_suffix}.mp3",
        caption_path=f"storage/captions/template-{slug_suffix}.srt",
    )
    db_session.add_all([channel, asset, video])
    await db_session.commit()
    await db_session.refresh(video)
    await db_session.refresh(asset)
    return video


async def _create_video_with_optional_assets(
    db_session,
    *,
    slug_suffix: str = "regen",
    with_audio: bool = True,
    with_caption: bool = True,
    with_asset: bool = True,
) -> Video:
    channel = Channel(name="Regenerate Channel", slug=f"regen-{slug_suffix}")
    asset = (
        AssetPool(
            asset_type="background_image",
            name="Regenerate Asset",
            slug=f"regen-asset-{slug_suffix}",
            source_url="local",
            source_path=f"storage/assets/manual/regen-{slug_suffix}.png",
            license_name="generated-local",
            license_url=None,
            status=LifecycleStatus.ACTIVE,
        )
        if with_asset
        else None
    )
    video = Video(
        channel=channel,
        title="Regenerate Video",
        slug=f"regen-video-{slug_suffix}",
        status=WorkflowStatus.APPROVED,
        stage_status=VideoStageStatus.ASSET_READY,
        asset=asset,
        audio_path=f"storage/audio/regen-{slug_suffix}.mp3" if with_audio else None,
        caption_path=f"storage/captions/regen-{slug_suffix}.srt" if with_caption else None,
    )
    db_session.add(channel)
    if asset is not None:
        db_session.add(asset)
    db_session.add(video)
    await db_session.commit()
    await db_session.refresh(video)
    if asset is not None:
        await db_session.refresh(asset)
    return video


async def _prepare_video_for_youtube_upload(
    db_session,
    tmp_path,
    *,
    slug_suffix: str = "upload",
) -> tuple[Video, Settings, VideoProductionService]:
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
    )
    tts_worker = TTSWorker(session=db_session, client=fake_tts_client, settings=settings)
    production_service = VideoProductionService(session=db_session, settings=settings, tts_worker=tts_worker)
    video = await db_session.scalar(select(Video).where(Video.slug.like("como-aprender-python-%")))
    assert video is not None
    result = await production_service.produce_full_video(video_id=video.id)
    assert Path(result.final_path).exists()
    await db_session.commit()
    await production_service.create_export_package(video_id=video.id)
    await production_service.create_youtube_publish_prep(
        video_id=video.id,
        title="Titulo pronto",
        description="Descricao pronta",
        tags=["shorts", "python", "ready"],
        visibility="private",
        made_for_kids=False,
    )
    await db_session.commit()
    return video, settings, production_service


def _build_preset_settings(tmp_path: Path) -> Settings:
    storage_root = tmp_path / "storage"
    return Settings(
        local_storage_path=storage_root,
        asset_pool_path=storage_root / "assets",
        audio_output_path=storage_root / "audio",
        caption_output_path=storage_root / "captions",
        preview_output_path=storage_root / "renders" / "previews",
        final_output_path=storage_root / "renders" / "finals",
        whisper_model_path=storage_root / "models" / "missing.bin",
        ffmpeg_path="ffmpeg",
    )


def _build_job_settings(tmp_path: Path, *, database_url: str) -> Settings:
    storage_root = tmp_path / "storage"
    return Settings(
        local_storage_path=storage_root,
        asset_pool_path=storage_root / "assets",
        audio_output_path=storage_root / "audio",
        caption_output_path=storage_root / "captions",
        preview_output_path=storage_root / "renders" / "previews",
        final_output_path=storage_root / "renders" / "finals",
        whisper_model_path=storage_root / "models" / "missing.bin",
        ffmpeg_path="ffmpeg",
        database_url=database_url,
    )


def _build_content_brain_settings(tmp_path: Path, *, database_url: str) -> Settings:
    storage_root = tmp_path / "storage"
    return Settings(
        local_storage_path=storage_root,
        asset_pool_path=storage_root / "assets",
        audio_output_path=storage_root / "audio",
        caption_output_path=storage_root / "captions",
        preview_output_path=storage_root / "renders" / "previews",
        final_output_path=storage_root / "renders" / "finals",
        whisper_model_path=storage_root / "models" / "missing.bin",
        ffmpeg_path="ffmpeg",
        database_url=database_url,
    )


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

    async def _override_video_production_service(session=Depends(get_async_session)):
        worker = TTSWorker(session=session, client=fake_tts_client, settings=settings)
        return VideoProductionService(session=session, settings=settings, tts_worker=worker)

    video = await db_session.scalar(select(Video).where(Video.slug.like("como-aprender-python-%")))
    assert video is not None

    result = await production_service.produce_full_video(video_id=video.id)

    assert Path(result.audio_path).exists()
    assert Path(result.caption_path).exists()
    assert Path(result.preview_path).exists()
    assert Path(result.final_path).exists()
    assert (tmp_path / result.asset_path).exists()

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
            assert created.hook is not None
            assert created.call_to_action is not None
            assert created.estimated_duration_seconds is not None

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
            assert final_state.hook == created.hook
            assert final_state.call_to_action == created.call_to_action

            status_response = client.get(f"/internal/videos/{video_id}/status")
            assert status_response.status_code == 200
            status_state = VideoPipelineResponse.model_validate(status_response.json())
            assert status_state.stage_status == VideoStageStatus.FINAL_RENDERED.value
            assert status_state.audio_path == tts_state.audio_path
            assert status_state.caption_path == captions_state.caption_path
            assert status_state.preview_path == preview_state.preview_path
            assert status_state.final_path == final_state.final_path
            assert status_state.hook == created.hook
            assert status_state.call_to_action == created.call_to_action
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
async def test_channel_preset_list_and_upsert_roundtrip(db_session, tmp_path) -> None:
    settings = _build_preset_settings(tmp_path)
    service = VideoProductionService(session=db_session, settings=settings)

    preset = await service.upsert_channel_preset(
        channel_slug="manual-test",
        channel_name="Manual Test",
        default_topic_style="educativo e caloroso",
        default_visual_template="dark_overlay",
        default_asset_slug="preset-asset",
        default_cta="CTA do preset",
        target_duration_seconds=42,
    )
    presets = await service.list_channel_presets()

    assert preset.channel_slug == "manual-test"
    assert preset.channel_name == "Manual Test"
    assert preset.default_topic_style == "educativo e caloroso"
    assert preset.default_visual_template == "dark_overlay"
    assert preset.default_asset_slug == "preset-asset"
    assert preset.default_cta == "CTA do preset"
    assert preset.target_duration_seconds == 42
    assert len(presets) == 1
    assert presets[0].channel_slug == "manual-test"
    assert (settings.local_storage_path / "config" / "channel-presets" / "manual-test.json").exists()


@pytest.mark.asyncio
async def test_create_local_test_video_applies_channel_preset_defaults(db_session, tmp_path) -> None:
    settings = _build_preset_settings(tmp_path)
    service = VideoProductionService(session=db_session, settings=settings)

    asset = AssetPool(
        asset_type="background_image",
        name="Preset Asset",
        slug="preset-asset",
        source_url="local",
        source_path="storage/assets/manual/preset-asset.png",
        license_name="generated-local",
        license_url=None,
        status=LifecycleStatus.ACTIVE,
    )
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)

    await service.upsert_channel_preset(
        channel_slug="manual-test",
        channel_name="Manual Test",
        default_topic_style="educativo e caloroso",
        default_visual_template="dark_overlay",
        default_asset_slug="preset-asset",
        default_cta="CTA do preset",
        target_duration_seconds=42,
    )

    result = await service.create_local_test_video(
        topic="Como aprender Python",
        channel_slug="manual-test",
        channel_name="Manual Test",
        video_title="Teste preset",
        execution_mode=VideoExecutionMode.FAKE,
    )

    assert result.stage_status == VideoStageStatus.SCRIPT_APPROVED.value
    assert result.target_duration_seconds == 42
    assert result.visual_template == "dark_overlay"
    assert result.style_tone == "educativo e caloroso"
    assert result.call_to_action == "CTA do preset"
    assert result.asset_id == asset.id
    assert result.asset_slug == "preset-asset"
    assert result.asset_path == "storage/assets/manual/preset-asset.png"
    assert result.asset_name == "Preset Asset"
    assert result.estimated_duration_seconds == 42

    refreshed_video = await db_session.get(Video, result.video_id)
    assert refreshed_video is not None
    assert refreshed_video.target_duration_seconds == 42
    assert refreshed_video.asset_id == asset.id


@pytest.mark.asyncio
async def test_create_local_test_video_supports_viral_micro_short_mode(db_session, tmp_path) -> None:
    settings = _build_preset_settings(tmp_path)
    service = VideoProductionService(session=db_session, settings=settings)

    result = await service.create_local_test_video(
        topic="Programador iniciante vs tester",
        channel_slug="viral-channel",
        channel_name="Viral Channel",
        video_title="Teste viral",
        execution_mode=VideoExecutionMode.FAKE,
        style_tone="viral_micro_short",
        target_duration_seconds=12,
    )

    assert result.stage_status == VideoStageStatus.SCRIPT_APPROVED.value
    assert result.style_tone == "viral_micro_short"
    assert result.target_duration_seconds == 12
    assert result.estimated_duration_seconds is not None
    assert result.estimated_duration_seconds <= 15
    assert result.body_blocks is not None
    assert len(result.body_blocks) == 4
    assert result.call_to_action == ""
    assert result.hook is not None and len(result.hook) <= 40 and result.hook.endswith(":")
    assert "na pratica" not in (result.script_text or "")


@pytest.mark.asyncio
async def test_create_local_test_video_falls_back_without_preset(db_session, tmp_path) -> None:
    settings = _build_preset_settings(tmp_path)
    service = VideoProductionService(session=db_session, settings=settings)

    result = await service.create_local_test_video(
        topic="Como aprender Python",
        channel_slug="no-preset-channel",
        channel_name="No Preset Channel",
        video_title="Teste sem preset",
        execution_mode=VideoExecutionMode.FAKE,
    )

    assert result.stage_status == VideoStageStatus.SCRIPT_APPROVED.value
    assert result.target_duration_seconds is None
    assert result.visual_template == "default"
    assert result.asset_id is None
    assert result.asset_path is None
    assert result.style_tone == "didatico e direto"


@pytest.mark.asyncio
async def test_internal_video_preview_defaults_to_default_template(
    db_session,
    temp_database_url: str,
    monkeypatch,
) -> None:
    async def _override_async_session():
        engine = create_async_engine(temp_database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                yield session
        finally:
            await engine.dispose()

    commands: list[list[str]] = []

    def _fake_run_command(command: list[str]) -> None:
        commands.append(command)

    monkeypatch.setattr(render_worker_module, "run_command", _fake_run_command)

    video = await _create_video_ready_for_preview(db_session, slug_suffix="no-preset")

    app.dependency_overrides[get_async_session] = _override_async_session
    try:
        with TestClient(app) as client:
            preview_response = client.post(f"/internal/videos/{video.id}/preview")
            assert preview_response.status_code == 200
            preview_state = VideoPipelineResponse.model_validate(preview_response.json())
            assert preview_state.stage_status == VideoStageStatus.PREVIEW_READY.value
            assert preview_state.visual_template == "default"

            status_response = client.get(f"/internal/videos/{video.id}/status")
            assert status_response.status_code == 200
            status_state = VideoPipelineResponse.model_validate(status_response.json())
    finally:
        app.dependency_overrides.clear()

    assert status_state.visual_template == "default"
    assert commands
    assert "FontSize=28" in " ".join(commands[0])


@pytest.mark.asyncio
async def test_internal_video_export_package_creates_files_and_metadata(
    db_session,
    temp_database_url: str,
    tmp_path,
) -> None:
    async def _override_async_session():
        engine = create_async_engine(temp_database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                yield session
        finally:
            await engine.dispose()

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
    )
    tts_worker = TTSWorker(session=db_session, client=fake_tts_client, settings=settings)
    production_service = VideoProductionService(session=db_session, settings=settings, tts_worker=tts_worker)

    async def _override_video_production_service(session=Depends(get_async_session)):
        worker = TTSWorker(session=session, client=fake_tts_client, settings=settings)
        return VideoProductionService(session=session, settings=settings, tts_worker=worker)

    video = await db_session.scalar(select(Video).where(Video.slug.like("como-aprender-python-%")))
    assert video is not None

    result = await production_service.produce_full_video(video_id=video.id)
    assert Path(result.final_path).exists()
    await db_session.commit()

    app.dependency_overrides[get_async_session] = _override_async_session
    app.dependency_overrides[get_video_production_service] = _override_video_production_service
    original_get_settings = internal_videos_routes.get_settings
    internal_videos_routes.get_settings = lambda: settings
    try:
        with TestClient(app) as client:
            export_response = client.post(f"/internal/videos/{video.id}/export-package")
            assert export_response.status_code == 200, export_response.text
            exported = VideoPipelineResponse.model_validate(export_response.json())
            assert exported.export_metadata_path is not None
            assert exported.export_final_path is not None
            assert exported.export_caption_path is not None
            assert exported.export_preview_path is not None

            metadata_response = client.get("/internal/videos/files", params={"path": exported.export_metadata_path})
            assert metadata_response.status_code == 200
            assert metadata_response.headers["content-type"].startswith("application/json")
            assert metadata_response.headers["content-disposition"].lower().startswith("inline")
            metadata = json.loads(metadata_response.text)
    finally:
        internal_videos_routes.get_settings = original_get_settings
        app.dependency_overrides.clear()

    export_root = tmp_path / "storage" / "exports" / video.slug
    assert (export_root / "final.mp4").exists()
    assert (export_root / "captions.srt").exists()
    assert (export_root / "metadata.json").exists()
    assert metadata["video_id"] == video.id
    assert metadata["slug"] == video.slug
    assert metadata["title"] == video.title
    assert metadata["script"]["hook"] == exported.hook
    assert metadata["script"]["body_blocks"] == exported.body_blocks
    assert metadata["script"]["call_to_action"] == exported.call_to_action
    assert metadata["visual_template"] == exported.visual_template
    assert metadata["paths"]["final_path"] == result.final_path
    assert metadata["paths"]["export_final_path"] == exported.export_final_path
    assert metadata["content_brain"]["performance_label"] == exported.performance_label


@pytest.mark.asyncio
async def test_internal_video_export_package_blocks_without_final_render(
    temp_database_url: str,
) -> None:
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

            export_response = client.post(f"/internal/videos/{created.video_id}/export-package")
    finally:
        app.dependency_overrides.clear()

    assert export_response.status_code == 400
    assert "final render" in export_response.json()["detail"].lower(), export_response.json()


@pytest.mark.asyncio
async def test_internal_video_youtube_prep_creates_json_and_metadata(
    db_session,
    temp_database_url: str,
    tmp_path,
) -> None:
    async def _override_async_session():
        engine = create_async_engine(temp_database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                yield session
        finally:
            await engine.dispose()

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
    )
    tts_worker = TTSWorker(session=db_session, client=fake_tts_client, settings=settings)
    production_service = VideoProductionService(session=db_session, settings=settings, tts_worker=tts_worker)

    async def _override_video_production_service(session=Depends(get_async_session)):
        worker = TTSWorker(session=session, client=fake_tts_client, settings=settings)
        return VideoProductionService(session=session, settings=settings, tts_worker=worker)

    video = await db_session.scalar(select(Video).where(Video.slug.like("como-aprender-python-%")))
    assert video is not None

    result = await production_service.produce_full_video(video_id=video.id)
    assert Path(result.final_path).exists()
    await db_session.commit()

    app.dependency_overrides[get_async_session] = _override_async_session
    app.dependency_overrides[get_video_production_service] = _override_video_production_service
    original_get_settings = internal_videos_routes.get_settings
    internal_videos_routes.get_settings = lambda: settings
    try:
        with TestClient(app) as client:
            prep_response = client.post(
                f"/internal/videos/{video.id}/youtube-prep",
                json={
                    "title": "Titulo sugerido manual",
                    "description": "Descricao sugerida manual",
                    "tags": ["shorts", "python", "manual"],
                    "visibility": "private",
                    "made_for_kids": False,
                },
            )
            assert prep_response.status_code == 200, prep_response.text
            prepared = VideoPipelineResponse.model_validate(prep_response.json())
            assert prepared.youtube_publish_path is not None
            assert prepared.youtube_publish_title == "Titulo sugerido manual"
            assert prepared.youtube_publish_description == "Descricao sugerida manual"
            assert prepared.youtube_publish_tags == ["shorts", "python", "manual"]
            assert prepared.youtube_publish_visibility == "private"
            assert prepared.youtube_publish_made_for_kids is False

            json_response = client.get("/internal/videos/files", params={"path": prepared.youtube_publish_path})
            assert json_response.status_code == 200, json_response.text
            assert json_response.headers["content-type"].startswith("application/json")
            assert json_response.headers["content-disposition"].lower().startswith("inline")
            payload = json.loads(json_response.text)
    finally:
        internal_videos_routes.get_settings = original_get_settings
        app.dependency_overrides.clear()

    publish_root = tmp_path / "storage" / "exports" / video.slug
    assert (publish_root / "youtube_publish.json").exists()
    assert payload["video_id"] == video.id
    assert payload["slug"] == video.slug
    assert payload["title"] == "Titulo sugerido manual"
    assert payload["description"] == "Descricao sugerida manual"
    assert payload["tags"] == ["shorts", "python", "manual"]
    assert payload["visibility"] == "private"
    assert payload["made_for_kids"] is False
    assert payload["final_mp4_path"] == prepared.export_final_path
    assert payload["captions_path"] == prepared.export_caption_path
    assert payload["metadata_path"] == prepared.export_metadata_path


@pytest.mark.asyncio
async def test_internal_video_youtube_prep_blocks_without_final_render(
    temp_database_url: str,
) -> None:
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

            prep_response = client.post(
                f"/internal/videos/{created.video_id}/youtube-prep",
                json={"title": "Titulo manual"},
            )
    finally:
        app.dependency_overrides.clear()

    assert prep_response.status_code == 400
    assert "final render" in prep_response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_internal_video_publish_readiness_ready_when_all_artifacts_exist(
    db_session,
    temp_database_url: str,
    tmp_path,
) -> None:
    async def _override_async_session():
        engine = create_async_engine(temp_database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                yield session
        finally:
            await engine.dispose()

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
    )
    tts_worker = TTSWorker(session=db_session, client=fake_tts_client, settings=settings)
    production_service = VideoProductionService(session=db_session, settings=settings, tts_worker=tts_worker)

    async def _override_video_production_service(session=Depends(get_async_session)):
        worker = TTSWorker(session=session, client=fake_tts_client, settings=settings)
        return VideoProductionService(session=session, settings=settings, tts_worker=worker)

    video = await db_session.scalar(select(Video).where(Video.slug.like("como-aprender-python-%")))
    assert video is not None

    result = await production_service.produce_full_video(video_id=video.id)
    assert Path(result.final_path).exists()
    await db_session.commit()

    app.dependency_overrides[get_async_session] = _override_async_session
    app.dependency_overrides[get_video_production_service] = _override_video_production_service
    original_get_settings = internal_videos_routes.get_settings
    internal_videos_routes.get_settings = lambda: settings
    try:
        with TestClient(app) as client:
            export_response = client.post(f"/internal/videos/{video.id}/export-package")
            assert export_response.status_code == 200, export_response.text

            prep_response = client.post(
                f"/internal/videos/{video.id}/youtube-prep",
                json={
                    "title": "Titulo pronto",
                    "description": "Descricao pronta",
                    "tags": ["shorts", "python", "ready"],
                    "visibility": "private",
                    "made_for_kids": False,
                },
            )
            assert prep_response.status_code == 200, prep_response.text

            readiness_response = client.get(f"/internal/videos/{video.id}/publish-readiness")
            assert readiness_response.status_code == 200, readiness_response.text
            payload = readiness_response.json()
    finally:
        internal_videos_routes.get_settings = original_get_settings
        app.dependency_overrides.clear()

    assert payload["overall_status"] == "ready"
    assert payload["ready"] is True
    assert payload["missing_items"] == []
    assert [item["key"] for item in payload["items"]] == [
        "final_path",
        "export_package",
        "export_metadata",
        "captions",
        "youtube_publish",
        "title",
        "description",
        "tags",
        "visibility",
        "made_for_kids",
        "content_brain_label",
    ]
    assert all(item["ready"] for item in payload["items"])


@pytest.mark.asyncio
async def test_internal_video_publish_readiness_missing_when_youtube_json_missing(
    db_session,
    temp_database_url: str,
    tmp_path,
) -> None:
    async def _override_async_session():
        engine = create_async_engine(temp_database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                yield session
        finally:
            await engine.dispose()

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
    )
    tts_worker = TTSWorker(session=db_session, client=fake_tts_client, settings=settings)
    production_service = VideoProductionService(session=db_session, settings=settings, tts_worker=tts_worker)

    async def _override_video_production_service(session=Depends(get_async_session)):
        worker = TTSWorker(session=session, client=fake_tts_client, settings=settings)
        return VideoProductionService(session=session, settings=settings, tts_worker=worker)

    video = await db_session.scalar(select(Video).where(Video.slug.like("como-aprender-python-%")))
    assert video is not None

    result = await production_service.produce_full_video(video_id=video.id)
    assert Path(result.final_path).exists()
    await db_session.commit()

    app.dependency_overrides[get_async_session] = _override_async_session
    app.dependency_overrides[get_video_production_service] = _override_video_production_service
    original_get_settings = internal_videos_routes.get_settings
    internal_videos_routes.get_settings = lambda: settings
    try:
        with TestClient(app) as client:
            export_response = client.post(f"/internal/videos/{video.id}/export-package")
            assert export_response.status_code == 200, export_response.text

            readiness_response = client.get(f"/internal/videos/{video.id}/publish-readiness")
            assert readiness_response.status_code == 200, readiness_response.text
            payload = readiness_response.json()
    finally:
        internal_videos_routes.get_settings = original_get_settings
        app.dependency_overrides.clear()

    assert payload["overall_status"] == "missing_items"
    assert payload["ready"] is False
    assert "youtube_publish" in payload["missing_items"]
    items = {item["key"]: item for item in payload["items"]}
    assert items["youtube_publish"]["ready"] is False
    assert items["content_brain_label"]["ready"] is True


@pytest.mark.asyncio
async def test_internal_video_publish_readiness_blocks_without_final_render(
    temp_database_url: str,
) -> None:
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

            readiness_response = client.get(f"/internal/videos/{created.video_id}/publish-readiness")
    finally:
        app.dependency_overrides.clear()

    assert readiness_response.status_code == 400
    assert "final render" in readiness_response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_internal_video_youtube_upload_blocks_when_disabled(
    db_session,
    temp_database_url: str,
    tmp_path,
    monkeypatch,
) -> None:
    async def _override_async_session():
        engine = create_async_engine(temp_database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                yield session
        finally:
            await engine.dispose()

    video, settings, _ = await _prepare_video_for_youtube_upload(db_session, tmp_path)
    settings.youtube_client_secrets_path = tmp_path / "client_secrets.json"
    settings.youtube_client_secrets_path.write_text("{}", encoding="utf-8")
    settings.youtube_token_path = tmp_path / "token.json"
    settings.youtube_token_path.write_text("{}", encoding="utf-8")
    settings.youtube_upload_enabled = False

    monkeypatch.setattr(internal_videos_routes, "get_settings", lambda: settings)

    app.dependency_overrides[get_async_session] = _override_async_session
    async def _override_video_production_service(session=Depends(get_async_session)):
        return VideoProductionService(session=session, settings=settings)

    app.dependency_overrides[get_video_production_service] = _override_video_production_service
    try:
        with TestClient(app) as client:
            response = client.post(f"/internal/videos/{video.id}/youtube/upload")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["upload_status"] == "ready_but_disabled"
    assert payload["youtube_video_id"] is None
    assert "desativado" in payload["message"].lower()


@pytest.mark.asyncio
async def test_internal_video_youtube_upload_blocks_when_readiness_missing(
    db_session,
    temp_database_url: str,
    tmp_path,
    monkeypatch,
) -> None:
    async def _override_async_session():
        engine = create_async_engine(temp_database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                yield session
        finally:
            await engine.dispose()

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
        youtube_upload_enabled=True,
    )
    settings.youtube_client_secrets_path = tmp_path / "client_secrets.json"
    settings.youtube_client_secrets_path.write_text("{}", encoding="utf-8")
    settings.youtube_token_path = tmp_path / "token.json"
    settings.youtube_token_path.write_text("{}", encoding="utf-8")

    production_service = VideoProductionService(
        session=db_session,
        settings=settings,
        tts_worker=TTSWorker(session=db_session, client=fake_tts_client, settings=settings),
    )
    video = await db_session.scalar(select(Video).where(Video.slug.like("como-aprender-python-%")))
    assert video is not None
    result = await production_service.produce_full_video(video_id=video.id)
    assert Path(result.final_path).exists()
    await db_session.commit()

    monkeypatch.setattr(internal_videos_routes, "get_settings", lambda: settings)
    app.dependency_overrides[get_async_session] = _override_async_session
    async def _override_video_production_service(session=Depends(get_async_session)):
        return VideoProductionService(session=session, settings=settings)

    app.dependency_overrides[get_video_production_service] = _override_video_production_service
    try:
        with TestClient(app) as client:
            response = client.post(f"/internal/videos/{video.id}/youtube/upload")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["upload_status"] == "blocked"
    assert "pronto para publicação" in payload["message"].lower() or "pronto para publicacao" in payload["message"].lower()


@pytest.mark.asyncio
async def test_internal_video_youtube_upload_blocks_when_auth_not_ready(
    db_session,
    temp_database_url: str,
    tmp_path,
    monkeypatch,
) -> None:
    async def _override_async_session():
        engine = create_async_engine(temp_database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                yield session
        finally:
            await engine.dispose()

    video, settings, _ = await _prepare_video_for_youtube_upload(db_session, tmp_path)
    settings.youtube_upload_enabled = True

    monkeypatch.setattr(internal_videos_routes, "get_settings", lambda: settings)
    app.dependency_overrides[get_async_session] = _override_async_session
    async def _override_video_production_service(session=Depends(get_async_session)):
        return VideoProductionService(session=session, settings=settings)

    app.dependency_overrides[get_video_production_service] = _override_video_production_service
    try:
        with TestClient(app) as client:
            response = client.post(f"/internal/videos/{video.id}/youtube/upload")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["upload_status"] == "blocked"
    assert "autentica" in payload["message"].lower() or "publicacao" in payload["message"].lower()


@pytest.mark.asyncio
async def test_internal_video_youtube_upload_simulated_when_ready(
    db_session,
    temp_database_url: str,
    tmp_path,
    monkeypatch,
) -> None:
    async def _override_async_session():
        engine = create_async_engine(temp_database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                yield session
        finally:
            await engine.dispose()

    video, settings, _ = await _prepare_video_for_youtube_upload(db_session, tmp_path)
    settings.youtube_client_secrets_path = tmp_path / "client_secrets.json"
    settings.youtube_client_secrets_path.write_text("{}", encoding="utf-8")
    settings.youtube_token_path = tmp_path / "token.json"
    settings.youtube_token_path.write_text("{}", encoding="utf-8")
    settings.youtube_upload_enabled = True

    monkeypatch.setattr(internal_videos_routes, "get_settings", lambda: settings)
    app.dependency_overrides[get_async_session] = _override_async_session
    async def _override_video_production_service(session=Depends(get_async_session)):
        return VideoProductionService(session=session, settings=settings)

    app.dependency_overrides[get_video_production_service] = _override_video_production_service
    try:
        with TestClient(app) as client:
            response = client.post(f"/internal/videos/{video.id}/youtube/upload")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["upload_status"] == "simulated"
    assert payload["youtube_video_id"] is None
    assert "simulado" in payload["message"].lower()


@pytest.mark.asyncio
async def test_internal_video_preview_rejects_unknown_template(
    db_session,
    temp_database_url: str,
) -> None:
    async def _override_async_session():
        engine = create_async_engine(temp_database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                yield session
        finally:
            await engine.dispose()

    video = await _create_video_ready_for_preview(db_session, slug_suffix="invalid")

    app.dependency_overrides[get_async_session] = _override_async_session
    try:
        with TestClient(app) as client:
            preview_response = client.post(
                f"/internal/videos/{video.id}/preview",
                json={"visual_template": "neon_mist"},
            )
    finally:
        app.dependency_overrides.clear()

    assert preview_response.status_code == 400
    assert "Unknown visual template" in preview_response.json()["detail"]


@pytest.mark.asyncio
async def test_internal_video_preview_dark_overlay_changes_render_parameters(
    db_session,
    temp_database_url: str,
    monkeypatch,
) -> None:
    async def _override_async_session():
        engine = create_async_engine(temp_database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                yield session
        finally:
            await engine.dispose()

    commands: list[list[str]] = []

    def _fake_run_command(command: list[str]) -> None:
        commands.append(command)

    monkeypatch.setattr(render_worker_module, "run_command", _fake_run_command)

    video = await _create_video_ready_for_preview(db_session, slug_suffix="dark")

    app.dependency_overrides[get_async_session] = _override_async_session
    try:
        with TestClient(app) as client:
            preview_response = client.post(
                f"/internal/videos/{video.id}/preview",
                json={"visual_template": "dark_overlay"},
            )
            assert preview_response.status_code == 200
            preview_state = VideoPipelineResponse.model_validate(preview_response.json())
    finally:
        app.dependency_overrides.clear()

    assert preview_state.visual_template == "dark_overlay"
    assert commands
    command_text = " ".join(commands[0])
    assert "color=c=black@0.32" in command_text
    assert "FontSize=30" in command_text


@pytest.mark.asyncio
async def test_internal_video_preview_regenerate_replaces_approval_and_asset(
    db_session,
    temp_database_url: str,
    monkeypatch,
) -> None:
    async def _override_async_session():
        engine = create_async_engine(temp_database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                yield session
        finally:
            await engine.dispose()

    commands: list[list[str]] = []

    def _fake_run_command(command: list[str]) -> None:
        commands.append(command)
        output_path = Path(command[-1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake-render")

    monkeypatch.setattr(render_worker_module, "run_command", _fake_run_command)

    video = await _create_video_ready_for_preview(db_session, slug_suffix="regen")
    replacement_asset = AssetPool(
        asset_type="background_image",
        name="Replacement Asset",
        slug="replacement-asset",
        source_url="local",
        source_path="storage/assets/manual/replacement-asset.png",
        license_name="generated-local",
        license_url=None,
        status=LifecycleStatus.ACTIVE,
    )
    db_session.add(replacement_asset)
    await db_session.commit()
    await db_session.refresh(replacement_asset)

    app.dependency_overrides[get_async_session] = _override_async_session
    try:
        with TestClient(app) as client:
            preview_response = client.post(f"/internal/videos/{video.id}/preview")
            assert preview_response.status_code == 200
            preview_state = VideoPipelineResponse.model_validate(preview_response.json())
            assert preview_state.stage_status == VideoStageStatus.PREVIEW_READY.value
            assert Path(preview_state.preview_path or "").exists()

            approve_response = client.post(f"/internal/videos/{video.id}/approve-preview")
            assert approve_response.status_code == 200
            approved_state = VideoPipelineResponse.model_validate(approve_response.json())
            assert approved_state.preview_approved_at is not None

            regenerate_response = client.post(
                f"/internal/videos/{video.id}/preview/regenerate",
                json={
                    "asset_id": replacement_asset.id,
                    "visual_template": "big_captions",
                },
            )
            assert regenerate_response.status_code == 200
            regenerated_state = VideoPipelineResponse.model_validate(regenerate_response.json())
            assert regenerated_state.stage_status == VideoStageStatus.PREVIEW_READY.value
            assert regenerated_state.preview_approved_at is None
            assert regenerated_state.asset_id == replacement_asset.id
            assert regenerated_state.visual_template == "big_captions"
            assert regenerated_state.preview_path == preview_state.preview_path

            status_response = client.get(f"/internal/videos/{video.id}/status")
            assert status_response.status_code == 200
            status_state = VideoPipelineResponse.model_validate(status_response.json())
    finally:
        app.dependency_overrides.clear()

    assert status_state.stage_status == VideoStageStatus.PREVIEW_READY.value
    assert status_state.preview_approved_at is None
    assert status_state.asset_id == replacement_asset.id
    assert status_state.visual_template == "big_captions"
    assert commands
    assert "FontSize=38" in " ".join(commands[-1])


@pytest.mark.asyncio
async def test_internal_video_preview_regenerate_blocks_after_final_rendered(
    db_session,
    temp_database_url: str,
    monkeypatch,
) -> None:
    async def _override_async_session():
        engine = create_async_engine(temp_database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                yield session
        finally:
            await engine.dispose()

    def _fake_run_command(command: list[str]) -> None:
        output_path = Path(command[-1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake-render")

    monkeypatch.setattr(render_worker_module, "run_command", _fake_run_command)

    video = await _create_video_ready_for_preview(db_session, slug_suffix="finalized")

    app.dependency_overrides[get_async_session] = _override_async_session
    try:
        with TestClient(app) as client:
            preview_response = client.post(f"/internal/videos/{video.id}/preview")
            assert preview_response.status_code == 200

            approve_response = client.post(f"/internal/videos/{video.id}/approve-preview")
            assert approve_response.status_code == 200

            final_response = client.post(f"/internal/videos/{video.id}/final")
            assert final_response.status_code == 200
            final_state = VideoPipelineResponse.model_validate(final_response.json())
            assert final_state.stage_status == VideoStageStatus.FINAL_RENDERED.value

            regenerate_response = client.post(f"/internal/videos/{video.id}/preview/regenerate")
    finally:
        app.dependency_overrides.clear()

    assert regenerate_response.status_code == 400
    assert "after final render" in regenerate_response.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("with_audio", "with_caption", "with_asset", "expected_detail"),
    [
        (False, True, True, "Audio is required before regenerating preview"),
        (True, False, True, "Captions are required before regenerating preview"),
        (True, True, False, "Video asset is required before regenerating preview"),
    ],
)
async def test_internal_video_preview_regenerate_blocks_missing_inputs(
    db_session,
    temp_database_url: str,
    with_audio: bool,
    with_caption: bool,
    with_asset: bool,
    expected_detail: str,
) -> None:
    async def _override_async_session():
        engine = create_async_engine(temp_database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                yield session
        finally:
            await engine.dispose()

    video = await _create_video_with_optional_assets(
        db_session,
        slug_suffix=f"{int(with_audio)}-{int(with_caption)}-{int(with_asset)}",
        with_audio=with_audio,
        with_caption=with_caption,
        with_asset=with_asset,
    )

    app.dependency_overrides[get_async_session] = _override_async_session
    try:
        with TestClient(app) as client:
            regenerate_response = client.post(f"/internal/videos/{video.id}/preview/regenerate")
    finally:
        app.dependency_overrides.clear()

    assert regenerate_response.status_code == 400
    assert expected_detail in regenerate_response.json()["detail"]


@pytest.mark.asyncio
async def test_internal_video_script_update_before_tts_updates_structure(db_session, temp_database_url: str) -> None:
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

            update_response = client.patch(
                f"/internal/videos/{created.video_id}/script",
                json={
                    "script_text": "Hook novo\n\nBloco um revisado.\n\nBloco dois revisado.\n\nCTA nova para a audiencia.",
                },
            )
            assert update_response.status_code == 200
            updated = VideoPipelineResponse.model_validate(update_response.json())
    finally:
        app.dependency_overrides.clear()

    assert updated.stage_status == VideoStageStatus.SCRIPT_APPROVED.value
    assert updated.script_text == "Hook novo\n\nBloco um revisado.\n\nBloco dois revisado.\n\nCTA nova para a audiencia."
    assert updated.hook == "Hook novo"
    assert updated.body_blocks == ["Bloco um revisado.", "Bloco dois revisado."]
    assert updated.call_to_action == "CTA nova para a audiencia."
    assert updated.estimated_duration_seconds is not None


@pytest.mark.asyncio
async def test_internal_video_script_update_after_tts_is_blocked(db_session, temp_database_url: str) -> None:
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

            tts_response = client.post(f"/internal/videos/{created.video_id}/tts", json={"execution_mode": "fake"})
            assert tts_response.status_code == 200

            update_response = client.patch(
                f"/internal/videos/{created.video_id}/script",
                json={
                    "script_text": "Hook novo\n\nBloco um revisado.\n\nBloco dois revisado.\n\nCTA nova para a audiencia.",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert update_response.status_code == 400
    assert "before TTS" in update_response.json()["detail"]


@pytest.mark.asyncio
async def test_internal_video_performance_signals_update_and_list(
    db_session,
    temp_database_url: str,
    tmp_path,
) -> None:
    async def _override_async_session():
        engine = create_async_engine(temp_database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                yield VideoProductionService(session=session, settings=settings)
        finally:
            await engine.dispose()

    settings = _build_content_brain_settings(tmp_path, database_url=temp_database_url)

    app.dependency_overrides[get_video_production_service] = _override_async_session
    try:
        with TestClient(app) as client:
            winning_response = client.post(
                "/internal/videos/test",
                json={
                    "topic": "Como aprender Python",
                    "channel_slug": "brain-channel",
                    "channel_name": "Brain Channel",
                    "video_title": "Winning video",
                    "execution_mode": "fake",
                },
            )
            weak_response = client.post(
                "/internal/videos/test",
                json={
                    "topic": "Como aprender Python",
                    "channel_slug": "brain-channel",
                    "channel_name": "Brain Channel",
                    "video_title": "Weak video",
                    "execution_mode": "fake",
                },
            )
            assert winning_response.status_code == 200
            assert weak_response.status_code == 200
            winning_video = VideoPipelineResponse.model_validate(winning_response.json())
            weak_video = VideoPipelineResponse.model_validate(weak_response.json())

            winning_update = client.patch(
                f"/internal/videos/{winning_video.video_id}/performance",
                json={
                    "performance_label": "winning",
                    "notes": "Hook muito forte e direto.",
                    "reason_tags": ["hook", "cta"],
                },
            )
            weak_update = client.patch(
                f"/internal/videos/{weak_video.video_id}/performance",
                json={
                    "performance_label": "weak",
                    "notes": "Introducao longa demais.",
                    "reason_tags": ["tempo", "intro"],
                },
            )
            signals_response = client.get(
                "/internal/videos/content-brain/signals",
                params={"channel_slug": "brain-channel", "topic": "python"},
            )
    finally:
        app.dependency_overrides.clear()

    assert winning_update.status_code == 200
    assert weak_update.status_code == 200
    winning_state = VideoPipelineResponse.model_validate(winning_update.json())
    weak_state = VideoPipelineResponse.model_validate(weak_update.json())
    assert winning_state.performance_label == "winning"
    assert winning_state.performance_notes == "Hook muito forte e direto."
    assert winning_state.performance_reason_tags == ["hook", "cta"]
    assert weak_state.performance_label == "weak"
    assert weak_state.performance_reason_tags == ["tempo", "intro"]

    assert signals_response.status_code == 200
    signals = VideoPerformanceListResponse.model_validate(signals_response.json())
    labels = {item.performance_label for item in signals.items}
    assert labels == {"winning", "weak"}
    assert any(item.notes == "Hook muito forte e direto." for item in signals.items)
    assert any(item.notes == "Introducao longa demais." for item in signals.items)


@pytest.mark.asyncio
async def test_script_engine_receives_content_brain_context(
    db_session,
    temp_database_url: str,
    tmp_path,
) -> None:
    fake_llm = FakeOpenAIJSONClient(calls=[])
    settings = _build_content_brain_settings(tmp_path, database_url=temp_database_url)
    service = ScriptEngineService(session=db_session, llm_client=fake_llm, settings=settings)

    result = await service.create_test_script(
        topic="Como aprender Python",
        channel_slug="brain-channel",
        channel_name="Brain Channel",
        video_title="Script context test",
        execution_mode=VideoExecutionMode.FAKE,
        content_brain_context={
            "channel_slug": "brain-channel",
            "topic": "python",
            "winning_patterns": [{"video_id": 1, "notes": "hook curto", "reason_tags": ["curiosidade"]}],
            "weak_patterns": [{"video_id": 2, "notes": "muito longo", "reason_tags": ["genérico"]}],
            "winning_signals_count": 1,
            "weak_signals_count": 1,
        },
    )

    assert result.script_status == "approved"
    assert result.content_brain_context_used is True
    assert result.winning_signals_count == 1
    assert result.weak_signals_count == 1
    assert "curiosidade" in (result.applied_reason_tags or [])
    assert any("winning_patterns" in user_prompt and "weak_patterns" in user_prompt for _, user_prompt, _, _ in fake_llm.calls)


@pytest.mark.asyncio
async def test_script_engine_fake_uses_content_brain_winning_signals(
    db_session,
    temp_database_url: str,
    tmp_path,
) -> None:
    settings = _build_content_brain_settings(tmp_path, database_url=temp_database_url)
    service = ScriptEngineService(session=db_session, settings=settings)

    result = await service.create_test_script(
        topic="Como aprender Python",
        channel_slug="brain-channel",
        channel_name="Brain Channel",
        video_title="Script winning context",
        execution_mode=VideoExecutionMode.FAKE,
        content_brain_context={
            "channel_slug": "brain-channel",
            "topic": "python",
            "winning_patterns": [
                {"video_id": 1, "notes": "hook curto e curioso", "reason_tags": ["curiosidade", "hook"]},
            ],
            "weak_patterns": [
                {"video_id": 2, "notes": "intro genérica demais", "reason_tags": ["genérico"]},
            ],
            "winning_signals_count": 1,
            "weak_signals_count": 1,
        },
    )

    assert result.content_brain_context_used is True
    assert result.winning_signals_count == 1
    assert result.weak_signals_count == 1
    assert "curiosidade" in (result.applied_reason_tags or [])
    assert "curiosidade" in (result.hook or "").lower()
    assert any("padrao vencedor" in block.lower() for block in result.body_blocks or [])


@pytest.mark.asyncio
async def test_script_engine_fake_avoids_generic_weak_signals(
    db_session,
    temp_database_url: str,
    tmp_path,
) -> None:
    settings = _build_content_brain_settings(tmp_path, database_url=temp_database_url)
    service = ScriptEngineService(session=db_session, settings=settings)

    result = await service.create_test_script(
        topic="Como aprender Python",
        channel_slug="brain-channel",
        channel_name="Brain Channel",
        video_title="Script weak context",
        execution_mode=VideoExecutionMode.FAKE,
        content_brain_context={
            "channel_slug": "brain-channel",
            "topic": "python",
            "winning_patterns": [],
            "weak_patterns": [
                {"video_id": 2, "notes": "intro muito genérica", "reason_tags": ["genérico"]},
            ],
            "winning_signals_count": 0,
            "weak_signals_count": 1,
        },
    )

    assert result.content_brain_context_used is True
    assert result.winning_signals_count == 0
    assert result.weak_signals_count == 1
    assert "genérico" in (result.applied_reason_tags or [])
    assert any("exemplo concreto" in block.lower() for block in result.body_blocks or [])
    assert any("generica" in block.lower() or "genérica" in block.lower() for block in result.body_blocks or [])


@pytest.mark.asyncio
async def test_script_engine_real_prompt_receives_content_brain_context(
    db_session,
    temp_database_url: str,
    tmp_path,
    monkeypatch,
) -> None:
    prompts: list[str] = []

    async def _fake_generate_json(self, *, payload, model: str) -> LLMResult:  # noqa: ANN001
        prompts.append(payload.user_prompt)
        lower_prompt = payload.system_prompt.lower()
        if "idea" in lower_prompt:
            content = {
                "idea": "Explique uma curiosidade simples em formato curto.",
                "angle": "curiosidade",
                "title": "Ideia curta",
            }
        elif "hook" in lower_prompt:
            content = {
                "hook": "Voce ja percebeu isso em menos de 10 segundos?",
                "alt_hook": "Isso vai mudar sua forma de ver o tema.",
            }
        elif "script" in lower_prompt:
            hook = "Voce ja viu esse tema por este angulo?"
            body_blocks = [
                "Primeiro, simplifique a ideia central para ganhar atencao rapido.",
                "Depois, mostre um exemplo curto para deixar o assunto pratico.",
                "Em seguida, destaque o ganho direto para manter o ritmo.",
            ]
            call_to_action = "Se isso te ajudou, salva o video e compartilha com alguem."
            content = {
                "title": "Roteiro enxuto",
                "hook": hook,
                "body_blocks": body_blocks,
                "call_to_action": call_to_action,
                "estimated_duration_seconds": 36,
                "style_tone": "didatico e direto",
                "script": "\n\n".join([hook, *body_blocks, call_to_action]),
                "beats": ["hook", "body_1", "body_2", "body_3", "cta"],
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
            raw_content=json.dumps(content),
        )

    monkeypatch.setattr(LLMJSONClient, "generate_json", _fake_generate_json)
    settings = _build_content_brain_settings(tmp_path, database_url=temp_database_url)
    settings.llm_provider = LLMProvider.OPENAI
    settings.llm_api_key = "test-key"
    service = ScriptEngineService(session=db_session, settings=settings)

    result = await service.create_test_script(
        topic="Como aprender Python",
        channel_slug="brain-channel",
        channel_name="Brain Channel",
        video_title="Script real context test",
        execution_mode=VideoExecutionMode.REAL,
        content_brain_context={
            "channel_slug": "brain-channel",
            "topic": "python",
            "winning_patterns": [
                {"video_id": 1, "notes": "hook curto e curioso", "reason_tags": ["curiosidade"]},
            ],
            "weak_patterns": [
                {"video_id": 2, "notes": "intro muito genérica", "reason_tags": ["genérico"]},
            ],
            "winning_signals_count": 1,
            "weak_signals_count": 1,
        },
    )

    assert result.content_brain_context_used is True
    assert any("winning_patterns" in user_prompt and "weak_patterns" in user_prompt for user_prompt in prompts)
    assert any("Use winning patterns as positive examples" in user_prompt for user_prompt in prompts)


@pytest.mark.asyncio
async def test_internal_asset_registration_and_listing(
    db_session,
    temp_database_url: str,
    tmp_path,
    monkeypatch,
) -> None:
    async def _override_service():
        engine = create_async_engine(temp_database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                yield VideoProductionService(session=session, settings=settings)
        finally:
            await engine.dispose()

    asset_root = tmp_path / "storage" / "assets"
    asset_file = asset_root / "manual" / "hero.png"
    asset_file.parent.mkdir(parents=True, exist_ok=True)
    asset_file.write_bytes(b"fake-png")

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

    app.dependency_overrides[get_video_production_service] = _override_service
    try:
        with TestClient(app) as client:
            register_response = client.post(
                "/internal/videos/assets/register-local",
                json={
                    "file_path": "storage/assets/manual/hero.png",
                    "name": "Hero image",
                    "slug": "hero-image",
                    "asset_type": "background_image",
                    "license_name": "generated-local",
                    "channel_slug": "manual-test",
                    "topic": "python",
                    "tags": ["education", "local"],
                },
            )
            assert register_response.status_code == 200
            registered = AssetResponse.model_validate(register_response.json())

            list_response = client.get("/internal/videos/assets")
            assert list_response.status_code == 200
            assets = AssetListResponse.model_validate(list_response.json())
    finally:
        app.dependency_overrides.clear()

    assert registered.asset_id > 0
    assert registered.source_path == "storage/assets/manual/hero.png"
    assert registered.channel_slug == "manual-test"
    assert registered.topic == "python"
    assert registered.tags == ["education", "local"]
    assert any(item.asset_id == registered.asset_id for item in assets.items)
    assert any(item.is_default for item in assets.items)


@pytest.mark.asyncio
async def test_internal_asset_upload_registers_file_inside_storage(
    db_session,
    temp_database_url: str,
    tmp_path,
) -> None:
    async def _override_service():
        engine = create_async_engine(temp_database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                yield VideoProductionService(session=session, settings=settings)
        finally:
            await engine.dispose()

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

    app.dependency_overrides[get_video_production_service] = _override_service
    try:
        with TestClient(app) as client:
            response = client.post(
                "/internal/videos/assets/upload",
                params={
                    "filename": "Python BG.PNG",
                    "name": "Python Background",
                    "slug": "python-background",
                    "license_name": "generated-local",
                    "channel_slug": "manual-test",
                    "topic": "python",
                    "tags": "education,local",
                },
                content=b"fake-png",
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    uploaded = AssetResponse.model_validate(response.json())
    assert uploaded.source_path is not None
    assert uploaded.source_path.startswith("storage/assets/uploads/")
    saved_file = tmp_path / uploaded.source_path
    assert saved_file.exists()
    assert saved_file.read_bytes() == b"fake-png"


@pytest.mark.asyncio
async def test_internal_asset_upload_blocks_invalid_extension(
    db_session,
    temp_database_url: str,
    tmp_path,
) -> None:
    async def _override_service():
        engine = create_async_engine(temp_database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                yield VideoProductionService(session=session, settings=settings)
        finally:
            await engine.dispose()

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

    app.dependency_overrides[get_video_production_service] = _override_service
    try:
        with TestClient(app) as client:
            response = client.post(
                "/internal/videos/assets/upload",
                params={"filename": "bad.txt", "license_name": "generated-local"},
                content=b"nope",
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "unsupported" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_internal_asset_upload_blocks_mp4(
    db_session,
    temp_database_url: str,
    tmp_path,
) -> None:
    async def _override_service():
        engine = create_async_engine(temp_database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                yield VideoProductionService(session=session, settings=settings)
        finally:
            await engine.dispose()

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

    app.dependency_overrides[get_video_production_service] = _override_service
    try:
        with TestClient(app) as client:
            response = client.post(
                "/internal/videos/assets/upload",
                params={"filename": "clip.mp4", "license_name": "generated-local"},
                content=b"fake-mp4",
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "mp4" in response.json()["detail"].lower()
    assert "not supported" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_internal_asset_registration_blocks_traversal(
    db_session,
    temp_database_url: str,
    tmp_path,
    monkeypatch,
) -> None:
    async def _override_service():
        engine = create_async_engine(temp_database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                yield VideoProductionService(session=session, settings=settings)
        finally:
            await engine.dispose()

    asset_root = tmp_path / "storage" / "assets"
    asset_root.mkdir(parents=True, exist_ok=True)

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

    app.dependency_overrides[get_video_production_service] = _override_service
    try:
        with TestClient(app) as client:
            response = client.post(
                "/internal/videos/assets/register-local",
                json={
                    "relative_path": "../outside.png",
                    "name": "Bad asset",
                    "license_name": "generated-local",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "storage/assets" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_internal_asset_registration_blocks_files_outside_storage_assets(
    db_session,
    temp_database_url: str,
    tmp_path,
    monkeypatch,
) -> None:
    async def _override_service():
        engine = create_async_engine(temp_database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                yield VideoProductionService(session=session, settings=settings)
        finally:
            await engine.dispose()

    outside_root = tmp_path / "storage" / "other"
    outside_file = outside_root / "hero.png"
    outside_file.parent.mkdir(parents=True, exist_ok=True)
    outside_file.write_bytes(b"fake-png")

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

    app.dependency_overrides[get_video_production_service] = _override_service
    try:
        with TestClient(app) as client:
            response = client.post(
                "/internal/videos/assets/register-local",
                json={
                    "file_path": "storage/assets/../other/hero.png",
                    "name": "Outside asset",
                    "license_name": "generated-local",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "storage/assets" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_internal_asset_registration_blocks_mp4_backgrounds(
    db_session,
    temp_database_url: str,
    tmp_path,
    monkeypatch,
) -> None:
    async def _override_service():
        engine = create_async_engine(temp_database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                yield VideoProductionService(session=session, settings=settings)
        finally:
            await engine.dispose()

    asset_root = tmp_path / "storage" / "assets"
    asset_file = asset_root / "manual" / "clip.mp4"
    asset_file.parent.mkdir(parents=True, exist_ok=True)
    asset_file.write_bytes(b"fake-mp4")

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

    app.dependency_overrides[get_video_production_service] = _override_service
    try:
        with TestClient(app) as client:
            response = client.post(
                "/internal/videos/assets/register-local",
                json={
                    "file_path": "storage/assets/manual/clip.mp4",
                    "name": "Clip de fundo",
                    "license_name": "generated-local",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "mp4" in response.json()["detail"].lower()
    assert "not supported" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_internal_asset_selection_and_preview_block_mp4_backgrounds(
    db_session,
    temp_database_url: str,
    tmp_path,
    monkeypatch,
) -> None:
    async def _override_async_session():
        engine = create_async_engine(temp_database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                yield session
        finally:
            await engine.dispose()

    asset_root = tmp_path / "storage" / "assets"
    asset_file = asset_root / "manual" / "clip.mp4"
    asset_file.parent.mkdir(parents=True, exist_ok=True)
    asset_file.write_bytes(b"fake-mp4")

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

    mp4_asset = AssetPool(
        asset_type="background_video",
        name="Clip de fundo",
        slug="clip-de-fundo",
        source_url="local",
        source_path=str(asset_file.resolve()),
        license_name="generated-local",
        license_url=None,
        status=LifecycleStatus.ACTIVE,
    )
    db_session.add(mp4_asset)
    await db_session.commit()
    await db_session.refresh(mp4_asset)

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

            tts_response = client.post(f"/internal/videos/{created.video_id}/tts", json={"execution_mode": "fake"})
            assert tts_response.status_code == 200

            captions_response = client.post(f"/internal/videos/{created.video_id}/captions", json={"execution_mode": "fake"})
            assert captions_response.status_code == 200

            asset_response = client.post(
                f"/internal/videos/{created.video_id}/asset",
                json={"asset_id": mp4_asset.id},
            )
            assert asset_response.status_code == 400
            assert "mp4" in asset_response.json()["detail"].lower()

            video = await db_session.get(Video, created.video_id)
            assert video is not None
            video.asset_id = mp4_asset.id
            video.stage_status = VideoStageStatus.ASSET_READY
            await db_session.commit()

            preview_response = client.post(f"/internal/videos/{created.video_id}/preview")
            assert preview_response.status_code == 400
            assert "mp4" in preview_response.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_internal_asset_selection_before_preview_uses_manual_asset(
    db_session,
    temp_database_url: str,
    tmp_path,
    monkeypatch,
) -> None:
    async def _override_service():
        engine = create_async_engine(temp_database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                yield VideoProductionService(session=session, settings=settings)
        finally:
            await engine.dispose()

    asset_root = tmp_path / "storage" / "assets"
    asset_file = asset_root / "manual" / "hero.png"
    asset_file.parent.mkdir(parents=True, exist_ok=True)
    asset_file.write_bytes(b"fake-png")

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

    app.dependency_overrides[get_video_production_service] = _override_service
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

            register_response = client.post(
                "/internal/videos/assets/register-local",
                json={
                    "file_path": "storage/assets/manual/hero.png",
                    "name": "Hero image",
                    "slug": "hero-image",
                    "asset_type": "background_image",
                    "license_name": "generated-local",
                    "channel_slug": "manual-test",
                    "topic": "python",
                    "tags": ["education", "local"],
                },
            )
            assert register_response.status_code == 200
            registered = AssetResponse.model_validate(register_response.json())

            tts_response = client.post(f"/internal/videos/{created.video_id}/tts", json={"execution_mode": "fake"})
            assert tts_response.status_code == 200

            captions_response = client.post(f"/internal/videos/{created.video_id}/captions", json={"execution_mode": "fake"})
            assert captions_response.status_code == 200

            asset_response = client.post(
                f"/internal/videos/{created.video_id}/asset",
                json={"asset_id": registered.asset_id},
            )
            assert asset_response.status_code == 200
            asset_state = VideoPipelineResponse.model_validate(asset_response.json())
    finally:
        app.dependency_overrides.clear()

    assert asset_state.stage_status == VideoStageStatus.ASSET_READY.value
    assert asset_state.asset_id == registered.asset_id
    assert asset_state.asset_path == "storage/assets/manual/hero.png"
    assert asset_state.asset_name == "Hero image"


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
    assert item.hook is not None
    assert item.call_to_action is not None
    assert item.estimated_duration_seconds is not None
    assert item.is_demo is True


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


def test_demo_cleanup_endpoint_blocks_production(tmp_path, monkeypatch) -> None:
    storage_root = tmp_path / "storage"
    storage_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        internal_videos_routes,
        "get_settings",
        lambda: Settings(local_storage_path=storage_root, app_env="production"),
    )

    app.dependency_overrides[get_video_production_service] = lambda: FakeVideoProductionService()
    try:
        with TestClient(app) as client:
            response = client.post("/internal/videos/demo/reset", json={"confirm": True})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_demo_cleanup_endpoint_removes_demo_videos(temp_database_url: str, monkeypatch) -> None:
    async def _override_async_session():
        engine = create_async_engine(temp_database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                yield session
        finally:
            await engine.dispose()

    monkeypatch.setattr(
        internal_videos_routes,
        "get_settings",
        lambda: Settings(app_env="development"),
    )

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
            assert created.is_demo is True

            cleanup_response = client.post("/internal/videos/demo/reset", json={"confirm": True})
            assert cleanup_response.status_code == 200
            cleanup_body = cleanup_response.json()
    finally:
        app.dependency_overrides.clear()

    assert cleanup_body["deleted_videos"] >= 1
    assert cleanup_body["deleted_scripts"] >= 1


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


@pytest.mark.asyncio
async def test_background_full_pipeline_job_enqueues_and_completes(
    db_session,
    temp_database_url: str,
    tmp_path,
) -> None:
    async def _override_async_session():
        engine = create_async_engine(temp_database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                yield session
        finally:
            await engine.dispose()

    fake_redis = FakeRedis()
    queue_service = VideoJobQueueService(
        settings=_build_job_settings(tmp_path, database_url=temp_database_url),
        redis_client=fake_redis,
    )

    app.dependency_overrides[get_async_session] = _override_async_session
    app.dependency_overrides[get_video_job_queue_service] = lambda: queue_service
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

            enqueue_response = client.post(
                f"/internal/videos/{created.video_id}/jobs/produce",
                json={"visual_template": "default"},
            )
            assert enqueue_response.status_code == 200
            job = VideoJobResponse.model_validate(enqueue_response.json())
            assert job.status == "queued"
            assert job.job_type == "full_pipeline_fake"

            latest_response = client.get(f"/internal/videos/{created.video_id}/jobs/latest")
            assert latest_response.status_code == 200
            latest_job = VideoJobResponse.model_validate(latest_response.json())
            assert latest_job.job_id == job.job_id
            assert latest_job.status == "queued"
    finally:
        app.dependency_overrides.clear()

    completed_job = await queue_service.run_job_now(job.job_id)
    assert completed_job.status == "succeeded"

    app.dependency_overrides[get_async_session] = _override_async_session
    app.dependency_overrides[get_video_job_queue_service] = lambda: queue_service
    try:
        with TestClient(app) as client:
            job_status_response = client.get(f"/internal/videos/jobs/{job.job_id}")
            assert job_status_response.status_code == 200
            job_status = VideoJobResponse.model_validate(job_status_response.json())
            assert job_status.status == "succeeded"

            video_status_response = client.get(f"/internal/videos/{created.video_id}/status")
            assert video_status_response.status_code == 200
            video_status = VideoPipelineResponse.model_validate(video_status_response.json())
    finally:
        app.dependency_overrides.clear()

    refreshed_video = await db_session.get(Video, created.video_id)
    assert refreshed_video is not None
    assert refreshed_video.stage_status == VideoStageStatus.FINAL_RENDERED
    assert video_status.stage_status == VideoStageStatus.FINAL_RENDERED.value
    assert video_status.final_path is not None


@pytest.mark.asyncio
async def test_background_step_job_enqueues_and_completes(
    db_session,
    temp_database_url: str,
    tmp_path,
) -> None:
    async def _override_async_session():
        engine = create_async_engine(temp_database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                yield session
        finally:
            await engine.dispose()

    fake_redis = FakeRedis()
    queue_service = VideoJobQueueService(
        settings=_build_job_settings(tmp_path, database_url=temp_database_url),
        redis_client=fake_redis,
    )

    app.dependency_overrides[get_async_session] = _override_async_session
    app.dependency_overrides[get_video_job_queue_service] = lambda: queue_service
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

            enqueue_response = client.post(
                f"/internal/videos/{created.video_id}/jobs/tts",
                json={"visual_template": "default"},
            )
            assert enqueue_response.status_code == 200
            job = VideoJobResponse.model_validate(enqueue_response.json())
            assert job.status == "queued"
            assert job.job_type == "tts"
    finally:
        app.dependency_overrides.clear()

    completed_job = await queue_service.run_job_now(job.job_id)
    assert completed_job.status == "succeeded"

    refreshed_video = await db_session.get(Video, created.video_id)
    assert refreshed_video is not None
    assert refreshed_video.stage_status == VideoStageStatus.TTS_DONE
    assert refreshed_video.audio_path is not None


@pytest.mark.asyncio
async def test_background_job_failure_records_error(
    db_session,
    temp_database_url: str,
    tmp_path,
    monkeypatch,
) -> None:
    async def _override_async_session():
        engine = create_async_engine(temp_database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                yield session
        finally:
            await engine.dispose()

    async def _fail_produce(self, **kwargs):  # noqa: ANN001
        raise ValueError("boom")

    monkeypatch.setattr(VideoProductionService, "produce_full_video", _fail_produce)

    fake_redis = FakeRedis()
    queue_service = VideoJobQueueService(
        settings=_build_job_settings(tmp_path, database_url=temp_database_url),
        redis_client=fake_redis,
    )

    app.dependency_overrides[get_async_session] = _override_async_session
    app.dependency_overrides[get_video_job_queue_service] = lambda: queue_service
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

            enqueue_response = client.post(
                f"/internal/videos/{created.video_id}/jobs/produce",
                json={"visual_template": "default"},
            )
            assert enqueue_response.status_code == 200
            job = VideoJobResponse.model_validate(enqueue_response.json())
    finally:
        app.dependency_overrides.clear()

    with pytest.raises(ValueError, match="boom"):
        await queue_service.run_job_now(job.job_id)

    failed_job = await queue_service.get_job(job.job_id)
    assert failed_job is not None
    assert failed_job.status == "failed"
    assert failed_job.error_message == "boom"


def test_video_jobs_worker_configures_selector_policy_on_windows(monkeypatch) -> None:
    class FakePolicy:
        pass

    calls: list[object] = []
    monkeypatch.setattr(video_jobs_worker.sys, "platform", "win32")
    monkeypatch.setattr(video_jobs_worker.asyncio, "WindowsSelectorEventLoopPolicy", FakePolicy, raising=False)
    monkeypatch.setattr(
        video_jobs_worker.asyncio,
        "set_event_loop_policy",
        lambda policy: calls.append(policy),
    )

    video_jobs_worker._configure_event_loop_policy()

    assert len(calls) == 1
    assert isinstance(calls[0], FakePolicy)


def test_youtube_auth_status_disabled_by_default(tmp_path) -> None:
    settings = Settings(local_storage_path=tmp_path / "storage")

    status = get_youtube_auth_status(settings)

    assert status["enabled"] is False
    assert status["client_secrets_configured"] is False
    assert status["token_configured"] is False
    assert status["ready_for_upload"] is False
    assert any("disabled" in warning.lower() for warning in status["warnings"])


def test_youtube_auth_status_partial_config_returns_warnings(tmp_path) -> None:
    storage_root = tmp_path / "storage"
    client_secrets = tmp_path / "client_secrets.json"
    client_secrets.write_text("{}", encoding="utf-8")

    settings = Settings(
        local_storage_path=storage_root,
        youtube_client_secrets_path=client_secrets,
        youtube_upload_enabled=True,
    )

    status = get_youtube_auth_status(settings)

    assert status["enabled"] is True
    assert status["client_secrets_configured"] is True
    assert status["token_configured"] is False
    assert status["ready_for_upload"] is False
    assert any("token" in warning.lower() for warning in status["warnings"])


def test_youtube_auth_status_endpoint_reports_ready_only_when_enabled(tmp_path, monkeypatch) -> None:
    storage_root = tmp_path / "storage"
    storage_root.mkdir(parents=True, exist_ok=True)
    client_secrets = tmp_path / "client_secrets.json"
    client_secrets.write_text("{}", encoding="utf-8")
    token_path = tmp_path / "token.json"
    token_path.write_text("{}", encoding="utf-8")

    settings = Settings(
        local_storage_path=storage_root,
        youtube_client_secrets_path=client_secrets,
        youtube_token_path=token_path,
        youtube_upload_enabled=True,
    )
    monkeypatch.setattr(internal_videos_routes, "get_settings", lambda: settings)

    with TestClient(app) as client:
        response = client.get("/internal/videos/youtube/auth-status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["client_secrets_configured"] is True
    assert payload["token_configured"] is True
    assert payload["ready_for_upload"] is True
    assert payload["warnings"] == []
