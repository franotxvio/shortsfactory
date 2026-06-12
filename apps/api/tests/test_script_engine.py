from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.deps import get_script_engine_service
from app.core.config import Settings
from app.main import app
from app.models.core import Channel, CostLog, LLMCache, Script, Video
from app.models.enums import LLMProvider, VideoExecutionMode
from app.schemas.script_engine import ScriptEngineTestResponse
from app.services.llm_types import LLMResult, LLMUsage
from app.services.openai_client import LLMJSONClient
from app.services.script_engine import ScriptEngineService, ScriptGenerationResult


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


class FakeScriptEngineService:
    async def create_test_script(self, **_: object) -> ScriptGenerationResult:
        return ScriptGenerationResult(
            channel_id=1,
            video_id=2,
            script_id=3,
            video_slug="topic-1234",
            script_status="approved",
            policy_decision="approved",
            policy_risk_score=Decimal("0.2300"),
            cache_hits={"idea": True, "hook": True, "script": True, "policy": True},
            hook="Voce ja viu esse tema por este angulo?",
            body_blocks=[
                "Primeiro, simplifique a ideia central para ganhar atencao rapido.",
                "Depois, mostre um exemplo curto para deixar o assunto pratico.",
                "Em seguida, destaque o ganho direto para manter o ritmo.",
            ],
            call_to_action="Se isso te ajudou, salva o video e compartilha com alguem.",
            estimated_duration_seconds=36,
            style_tone="didatico e direto",
            script_text=(
                "Voce ja viu esse tema por este angulo?\n\n"
                "Primeiro, simplifique a ideia central para ganhar atencao rapido.\n\n"
                "Depois, mostre um exemplo curto para deixar o assunto pratico.\n\n"
                "Em seguida, destaque o ganho direto para manter o ritmo.\n\n"
                "Se isso te ajudou, salva o video e compartilha com alguem."
            ),
        )


@dataclass
class FakeLLMMessage:
    content: str | None


@dataclass
class FakeLLMChoice:
    message: FakeLLMMessage


@dataclass
class FakeLLMUsageData:
    prompt_tokens: int
    completion_tokens: int


class FakeAsyncOpenAI:
    last_init_kwargs: dict[str, str | None] | None = None
    last_chat_kwargs: dict[str, object] | None = None
    response_usage: FakeLLMUsageData | None = None
    response_model: str = "deepseek-chat"
    response_request_id: str = "req-deepseek"

    def __init__(self, **kwargs: object) -> None:
        FakeAsyncOpenAI.last_init_kwargs = {"api_key": kwargs.get("api_key"), "base_url": kwargs.get("base_url")}
        self.chat = self._Chat()

    class _Chat:
        def __init__(self) -> None:
            self.completions = self._Completions()

        class _Completions:
            async def create(self, **kwargs: object):
                FakeAsyncOpenAI.last_chat_kwargs = kwargs
                messages = kwargs.get("messages", [])
                system_prompt = ""
                user_prompt = ""
                if isinstance(messages, list):
                    for message in messages:
                        if not isinstance(message, dict):
                            continue
                        if message.get("role") == "system":
                            system_prompt = str(message.get("content") or "")
                        elif message.get("role") == "user":
                            user_prompt = str(message.get("content") or "")

                lower_prompt = system_prompt.lower()
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
                    import re

                    topic_match = re.search(r'about "(.+?)"', user_prompt)
                    topic = topic_match.group(1).strip() if topic_match else "o tema"
                    hook = f"Voce ja viu {topic} por este angulo?"
                    body_blocks = [
                        f"Primeiro, simplifique {topic} em uma ideia central que a pessoa entenda sem esforco.",
                        "Depois, mostre um passo pratico para transformar a explicacao em acao imediata.",
                        "Em seguida, destaque o ganho direto para deixar claro por que isso importa agora.",
                    ]
                    call_to_action = "Se isso te ajudou, salva o video e compartilha com alguem que precisa simplificar isso."
                    content = {
                        "title": f"Roteiro curto: {topic}",
                        "hook": hook,
                        "body_blocks": body_blocks,
                        "call_to_action": call_to_action,
                        "estimated_duration_seconds": 42,
                        "style_tone": "didatico e direto",
                        "script": "\n\n".join([hook, *body_blocks, call_to_action]),
                        "beats": ["hook", "body_1", "body_2", "body_3", "cta"],
                    }
                else:
                    content = {
                        "risk_score": 0.19,
                        "decision": "approved",
                        "reasons": ["ok"],
                        "allowed_topics": ["educacao"],
                    }

                return type(
                    "FakeResponse",
                    (),
                    {
                        "choices": [FakeLLMChoice(message=FakeLLMMessage(content=json.dumps(content)))],
                        "model": FakeAsyncOpenAI.response_model,
                        "id": FakeAsyncOpenAI.response_request_id,
                        "usage": FakeAsyncOpenAI.response_usage,
                    },
                )()


@pytest.mark.asyncio
async def test_script_engine_uses_cache_and_logs_costs(db_session) -> None:
    fake_client = FakeOpenAIJSONClient(calls=[])
    service = ScriptEngineService(session=db_session, llm_client=fake_client)

    first = await service.create_test_script(
        topic="Como aprender Python",
        channel_slug="test-channel",
        channel_name="Test Channel",
        video_title="Teste 1",
    )
    second = await service.create_test_script(
        topic="Como aprender Python",
        channel_slug="test-channel",
        channel_name="Test Channel",
        video_title="Teste 2",
    )

    assert first.cache_hits == {"idea": False, "hook": False, "script": False, "policy": False}
    assert second.cache_hits == {"idea": True, "hook": True, "script": True, "policy": True}
    assert len(fake_client.calls) == 4
    assert first.hook is not None
    assert first.body_blocks is not None
    assert len(first.body_blocks) >= 3
    assert first.call_to_action is not None
    assert first.estimated_duration_seconds is not None
    assert first.style_tone == "didatico e direto"
    assert "Primeiro, simplifique" in (first.script_text or "")

    channel_count = await db_session.scalar(select(func.count()).select_from(Channel))
    video_count = await db_session.scalar(select(func.count()).select_from(Video))
    script_count = await db_session.scalar(select(func.count()).select_from(Script))
    cost_log_count = await db_session.scalar(select(func.count()).select_from(CostLog))
    cache_count = await db_session.scalar(select(func.count()).select_from(LLMCache))

    assert channel_count == 1
    assert video_count == 2
    assert script_count == 2
    assert cost_log_count == 4
    assert cache_count == 4

    latest_script = await db_session.scalar(select(Script).order_by(Script.id.desc()))
    assert latest_script is not None
    assert latest_script.topic == "Como aprender Python"
    assert latest_script.policy_risk_score == Decimal("0.2300")
    assert latest_script.policy_decision == "approved"
    assert latest_script.generation_payload is not None
    assert latest_script.generation_payload["script"]["hook"] == first.hook
    assert latest_script.generation_payload["script"]["body_blocks"] == first.body_blocks


def test_internal_script_route_returns_response() -> None:
    app.dependency_overrides[get_script_engine_service] = lambda: FakeScriptEngineService()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/internal/scripts/test",
                json={
                    "topic": "Como aprender Python",
                    "channel_slug": "test-channel",
                    "channel_name": "Test Channel",
                    "video_title": "Teste 1",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = ScriptEngineTestResponse.model_validate(response.json())
    assert body.script_status == "approved"
    assert body.cache_hits == {"idea": True, "hook": True, "script": True, "policy": True}
    assert body.hook is not None
    assert body.call_to_action is not None
    assert body.estimated_duration_seconds == 36


@pytest.mark.asyncio
async def test_fake_script_engine_does_not_instantiate_provider(db_session, monkeypatch) -> None:
    def _fail_init(*args, **kwargs):  # noqa: ANN001, ANN003
        raise AssertionError("LLMJSONClient should not be instantiated in fake mode")

    monkeypatch.setattr(LLMJSONClient, "__init__", _fail_init)

    service = ScriptEngineService(session=db_session)
    result = await service.create_test_script(
        topic="Como aprender Python",
        channel_slug="test-channel",
        channel_name="Test Channel",
        video_title="Teste 1",
    )

    assert result.script_status == "approved"
    assert result.hook is not None
    cost_log_count = await db_session.scalar(select(func.count()).select_from(CostLog))
    assert cost_log_count == 0


@pytest.mark.asyncio
async def test_fake_script_engine_applies_preset_defaults(db_session) -> None:
    service = ScriptEngineService(session=db_session)
    result = await service.create_test_script(
        topic="Como aprender Python",
        channel_slug="preset-channel",
        channel_name="Preset Channel",
        video_title="Teste com preset",
        style_tone="educativo e caloroso",
        default_call_to_action="CTA do preset",
        target_duration_seconds=48,
    )

    assert result.script_status == "approved"
    assert result.style_tone == "educativo e caloroso"
    assert result.call_to_action == "CTA do preset"
    assert result.estimated_duration_seconds == 48
    assert "CTA do preset" in (result.script_text or "")


@pytest.mark.asyncio
async def test_fake_script_engine_supports_viral_micro_short_mode(db_session) -> None:
    service = ScriptEngineService(session=db_session)
    result = await service.create_test_script(
        topic="Programador iniciante vs tester",
        channel_slug="viral-channel",
        channel_name="Viral Channel",
        video_title="Teste viral",
        style_tone="viral_micro_short",
        target_duration_seconds=12,
    )

    assert result.script_status == "approved"
    assert result.style_tone == "viral_micro_short"
    assert result.estimated_duration_seconds is not None
    assert result.estimated_duration_seconds <= 15
    assert result.body_blocks is not None
    assert len(result.body_blocks) <= 5
    assert len(result.body_blocks) == 4
    assert result.hook is not None and len(result.hook) <= 40 and result.hook.endswith(":")
    assert result.call_to_action in {None, "", " "}
    assert "na pratica" not in (result.script_text or "")
    assert "quebra tudo" in (result.script_text or "")


@pytest.mark.asyncio
async def test_real_script_engine_without_api_key_fails_clear(db_session) -> None:
    service = ScriptEngineService(session=db_session, settings=Settings(llm_provider=LLMProvider.OPENAI))

    with pytest.raises(ValueError, match="LLM_API_KEY"):
        await service.create_test_script(
            topic="Como aprender Python",
            channel_slug="test-channel",
            channel_name="Test Channel",
            video_title="Teste 1",
            execution_mode=VideoExecutionMode.REAL,
        )


@pytest.mark.asyncio
async def test_deepseek_provider_uses_config_and_logs_costs(db_session, monkeypatch) -> None:
    monkeypatch.setattr("app.services.openai_client.AsyncOpenAI", FakeAsyncOpenAI)
    FakeAsyncOpenAI.last_init_kwargs = None
    FakeAsyncOpenAI.last_chat_kwargs = None
    FakeAsyncOpenAI.response_usage = FakeLLMUsageData(prompt_tokens=12, completion_tokens=34)
    FakeAsyncOpenAI.response_model = "deepseek-chat"

    settings = Settings(
        llm_provider=LLMProvider.DEEPSEEK,
        llm_api_key="sk-deepseek",
        llm_base_url="https://api.deepseek.com/v1",
        llm_model="deepseek-chat",
    )
    service = ScriptEngineService(session=db_session, settings=settings)

    result = await service.create_test_script(
        topic="Como aprender Python",
        channel_slug="deepseek-test",
        channel_name="DeepSeek Test",
        video_title="Teste DeepSeek",
        execution_mode=VideoExecutionMode.REAL,
        style_tone="educativo e caloroso",
        default_call_to_action="CTA do preset",
        target_duration_seconds=54,
    )

    assert result.script_status == "approved"
    assert result.hook is not None
    assert FakeAsyncOpenAI.last_init_kwargs == {
        "api_key": "sk-deepseek",
        "base_url": "https://api.deepseek.com/v1",
    }
    assert FakeAsyncOpenAI.last_chat_kwargs is not None
    assert FakeAsyncOpenAI.last_chat_kwargs["model"] == "deepseek-chat"
    assert result.style_tone == "educativo e caloroso"
    assert result.call_to_action == "CTA do preset"
    assert result.estimated_duration_seconds == 54

    cost_log = await db_session.scalar(select(CostLog).order_by(CostLog.id.desc()))
    assert cost_log is not None
    assert cost_log.provider == "deepseek"
    assert cost_log.model == "deepseek-chat"
    assert cost_log.estimated is False


@pytest.mark.asyncio
async def test_real_script_engine_marks_estimated_cost_when_usage_missing(db_session, monkeypatch) -> None:
    monkeypatch.setattr("app.services.openai_client.AsyncOpenAI", FakeAsyncOpenAI)
    FakeAsyncOpenAI.last_init_kwargs = None
    FakeAsyncOpenAI.last_chat_kwargs = None
    FakeAsyncOpenAI.response_usage = None
    FakeAsyncOpenAI.response_model = "deepseek-chat"

    settings = Settings(
        llm_provider=LLMProvider.DEEPSEEK,
        llm_api_key="sk-deepseek",
        llm_base_url="https://api.deepseek.com/v1",
        llm_model="deepseek-chat",
    )
    service = ScriptEngineService(session=db_session, settings=settings)

    await service.create_test_script(
        topic="Como aprender Python",
        channel_slug="deepseek-estimated-test",
        channel_name="DeepSeek Estimated Test",
        video_title="Teste DeepSeek Estimated",
        execution_mode=VideoExecutionMode.REAL,
    )

    cost_log = await db_session.scalar(select(CostLog).order_by(CostLog.id.desc()))
    assert cost_log is not None
    assert cost_log.provider == "deepseek"
    assert cost_log.model == "deepseek-chat"
    assert cost_log.estimated is True
