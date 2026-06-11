from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.deps import get_script_engine_service
from app.main import app
from app.models.core import Channel, CostLog, LLMCache, Script, Video
from app.schemas.script_engine import ScriptEngineTestResponse
from app.services.llm_types import LLMResult, LLMUsage
from app.services.script_engine import ScriptEngineService, ScriptGenerationResult


@dataclass
class FakeOpenAIJSONClient:
    calls: list[tuple[str, str, int, str]]

    async def generate_json(self, *, payload, model: str) -> LLMResult:
        self.calls.append((payload.system_prompt, payload.user_prompt, payload.max_tokens, model))
        lower_prompt = payload.system_prompt.lower()

        if "idea" in lower_prompt:
            content = {"idea": "Explique uma curiosidade simples em formato curto.", "angle": "curiosidade", "title": "Ideia curta"}
        elif "hook" in lower_prompt:
            content = {"hook": "Você já percebeu isso em menos de 10 segundos?", "alt_hook": "Isso vai mudar sua forma de ver o tema."}
        elif "script" in lower_prompt:
            content = {
                "title": "Roteiro enxuto",
                "script": "Abra com a curiosidade, desenvolva em três pontos e feche com uma frase forte.",
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
        )


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
