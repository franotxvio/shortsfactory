from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.core import Channel, CostLog, LLMCache, Script, Video
from app.models.enums import LifecycleStatus, WorkflowStatus
from app.services.llm_types import LLMResult, LLMUsage
from app.services.openai_client import OpenAIChatPayload, OpenAIJSONClient


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "script"


def _json_dumps(data: dict[str, object]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def _hash_content(*parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


@dataclass(slots=True)
class ScriptGenerationResult:
    channel_id: int
    video_id: int
    script_id: int
    video_slug: str
    script_status: str
    policy_decision: str
    policy_risk_score: Decimal
    cache_hits: dict[str, bool]


class ScriptEngineService:
    def __init__(
        self,
        session: AsyncSession,
        llm_client: OpenAIJSONClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.llm_client = llm_client or OpenAIJSONClient(self.settings)

    async def create_test_script(
        self,
        *,
        topic: str,
        channel_slug: str,
        channel_name: str,
        video_title: str | None = None,
    ) -> ScriptGenerationResult:
        async with self.session.begin():
            channel = await self._get_or_create_channel(channel_slug=channel_slug, channel_name=channel_name)

            idea = await self._generate_idea(topic=topic)
            hook = await self._generate_hook(topic=topic, idea=idea)
            script = await self._generate_script(topic=topic, idea=idea, hook=hook)
            policy = await self._policy_check(topic=topic, script=script)

            video_slug = f"{_slugify(topic)}-{uuid4().hex[:8]}"
            video = Video(
                channel_id=channel.id,
                title=video_title or str(script.content.get("title") or topic),
                slug=video_slug,
                status=WorkflowStatus.DRAFT,
            )
            self.session.add(video)
            await self.session.flush()

            script_status = WorkflowStatus.APPROVED if policy.content["decision"] == "approved" else WorkflowStatus.REJECTED
            generated_payload = {
                "topic": topic,
                "idea": idea.content,
                "hook": hook.content,
                "script": script.content,
                "policy": policy.content,
            }
            script_row = Script(
                video_id=video.id,
                version=1,
                status=script_status,
                topic=topic,
                idea=str(idea.content.get("idea") or ""),
                hook=str(hook.content.get("hook") or ""),
                content=str(script.content.get("script") or ""),
                notes=_build_policy_notes(policy.content),
                policy_risk_score=Decimal(str(policy.content["risk_score"])),
                policy_decision=str(policy.content["decision"]),
                generation_payload=generated_payload,
                llm_model=self.settings.openai_llm_model,
                llm_cache_key=script.content.get("cache_key"),
                llm_input_hash=script.content.get("input_hash"),
            )
            self.session.add(script_row)
            await self.session.flush()

            return ScriptGenerationResult(
                channel_id=channel.id,
                video_id=video.id,
                script_id=script_row.id,
                video_slug=video.slug,
                script_status=script_row.status.value,
                policy_decision=script_row.policy_decision or "rejected",
                policy_risk_score=script_row.policy_risk_score or Decimal("0"),
                cache_hits={
                    "idea": bool(idea.content.get("cache_hit")),
                    "hook": bool(hook.content.get("cache_hit")),
                    "script": bool(script.content.get("cache_hit")),
                    "policy": bool(policy.content.get("cache_hit")),
                },
            )

    async def _get_or_create_channel(self, *, channel_slug: str, channel_name: str) -> Channel:
        result = await self.session.execute(select(Channel).where(Channel.slug == channel_slug))
        channel = result.scalar_one_or_none()
        if channel is not None:
            return channel

        channel = Channel(name=channel_name, slug=channel_slug, status=LifecycleStatus.ACTIVE)
        self.session.add(channel)
        await self.session.flush()
        return channel

    async def _generate_idea(self, *, topic: str) -> LLMResult:
        return await self._generate_operation(
            operation="idea",
            topic=topic,
            prompt_context={"topic": topic},
            system_prompt="You generate one concise video idea in JSON.",
            user_prompt=f'Create one short video idea about "{topic}". Return JSON with keys idea, angle, title.',
            max_tokens=self.settings.openai_idea_max_tokens,
        )

    async def _generate_hook(self, *, topic: str, idea: LLMResult) -> LLMResult:
        idea_text = str(idea.content.get("idea") or "")
        return await self._generate_operation(
            operation="hook",
            topic=topic,
            prompt_context={"topic": topic, "idea": idea_text},
            system_prompt="You generate a hook for a short-form video in JSON.",
            user_prompt=(
                f'Create a strong hook for a short video about "{topic}" using this idea: {idea_text!r}. '
                "Return JSON with keys hook and alt_hook."
            ),
            max_tokens=self.settings.openai_hook_max_tokens,
        )

    async def _generate_script(self, *, topic: str, idea: LLMResult, hook: LLMResult) -> LLMResult:
        idea_text = str(idea.content.get("idea") or "")
        hook_text = str(hook.content.get("hook") or "")
        return await self._generate_operation(
            operation="script",
            topic=topic,
            prompt_context={"topic": topic, "idea": idea_text, "hook": hook_text},
            system_prompt="You write a full short-form script in JSON.",
            user_prompt=(
                f'Write a short-form video script about "{topic}". '
                f'Idea: {idea_text!r}. Hook: {hook_text!r}. '
                "Return JSON with keys title, script, beats."
            ),
            max_tokens=self.settings.openai_script_max_tokens,
        )

    async def _policy_check(self, *, topic: str, script: LLMResult) -> LLMResult:
        script_text = str(script.content.get("script") or "")
        return await self._generate_operation(
            operation="policy",
            topic=topic,
            prompt_context={"topic": topic, "script": script_text},
            system_prompt="You evaluate short-form video policy risk in JSON.",
            user_prompt=(
                f'Review this draft for policy risk about "{topic}". Script: {script_text!r}. '
                "Return JSON with keys risk_score, reasons, allowed_topics."
            ),
            max_tokens=self.settings.openai_policy_max_tokens,
        )

    async def _generate_operation(
        self,
        *,
        operation: str,
        topic: str,
        prompt_context: dict[str, object],
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
    ) -> LLMResult:
        model = self.settings.openai_llm_model
        prompt_blob = _json_dumps(
            {
                "operation": operation,
                "topic": topic,
                "context": prompt_context,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "max_tokens": max_tokens,
                "model": model,
            }
        )
        content_hash = _hash_content(prompt_blob)

        cached = await self.session.scalar(select(LLMCache).where(LLMCache.content_hash == content_hash))
        if cached is not None:
            content = cached.response_json if cached.response_json is not None else {}
            enriched_content = dict(content)
            enriched_content["cache_hit"] = True
            enriched_content["cache_key"] = cached.cache_key
            enriched_content["input_hash"] = cached.content_hash
            return LLMResult(
                content=enriched_content,
                model=cached.model,
                request_id=None,
                usage=LLMUsage(prompt_tokens=0, completion_tokens=0),
                raw_content=cached.response_text or _json_dumps(content),
            )

        result = await self.llm_client.generate_json(
            payload=OpenAIChatPayload(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
            ),
            model=model,
        )
        cache_key = f"{operation}:{content_hash}"

        cache_row = LLMCache(
            content_hash=content_hash,
            cache_key=cache_key,
            provider="openai",
            model=result.model,
            prompt_hash=_hash_content(system_prompt, user_prompt),
            response_text=result.raw_content,
            response_json=result.content,
        )
        self.session.add(cache_row)
        self.session.add(
            CostLog(
                video_id=None,
                provider="openai",
                operation=operation,
                request_id=result.request_id,
                model=result.model,
                cost_usd=_estimate_cost(result.usage.prompt_tokens, result.usage.completion_tokens, self.settings),
            )
        )
        await self.session.flush()

        enriched_content = dict(result.content)
        enriched_content["cache_hit"] = False
        enriched_content["cache_key"] = cache_key
        enriched_content["input_hash"] = content_hash
        return LLMResult(
            content=enriched_content,
            model=result.model,
            request_id=result.request_id,
            usage=result.usage,
            raw_content=result.raw_content,
        )


def _estimate_cost(prompt_tokens: int, completion_tokens: int, settings: Settings) -> Decimal:
    cost = (
        (prompt_tokens / 1_000_000) * settings.openai_input_cost_per_1m_tokens_usd
        + (completion_tokens / 1_000_000) * settings.openai_output_cost_per_1m_tokens_usd
    )
    return Decimal(str(round(cost, 6)))


def _build_policy_notes(policy: dict[str, object]) -> str | None:
    reasons = policy.get("reasons")
    if isinstance(reasons, list):
        return "; ".join(str(reason) for reason in reasons)
    return None
