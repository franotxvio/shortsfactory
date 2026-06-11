from __future__ import annotations

import json
from dataclasses import dataclass

from openai import AsyncOpenAI

from app.core.config import Settings
from app.models.enums import LLMProvider
from app.services.llm_types import LLMResult, LLMUsage


@dataclass(slots=True)
class OpenAIChatPayload:
    system_prompt: str
    user_prompt: str
    max_tokens: int


class OpenAIJSONClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings
        api_key = (settings or Settings()).openai_api_key
        self._client = AsyncOpenAI(api_key=api_key)

    def _get_client(self) -> AsyncOpenAI:
        return self._client

    async def generate_json(self, *, payload: OpenAIChatPayload, model: str) -> LLMResult:
        response = await self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": payload.system_prompt},
                {"role": "user", "content": payload.user_prompt},
            ],
            max_tokens=payload.max_tokens,
            response_format={"type": "json_object"},
            temperature=0.2,
        )

        raw_content = response.choices[0].message.content or "{}"
        content = json.loads(raw_content)
        usage = response.usage

        return LLMResult(
            content=content,
            model=response.model or model,
            request_id=response.id,
            usage=LLMUsage(
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
            ) if usage else None,
            raw_content=raw_content,
        )

    async def generate_tts_audio(
        self,
        *,
        text: str,
        model: str,
        voice: str,
    ) -> tuple[bytes, str | None]:
        client = self._get_client()
        response = await client.audio.speech.create(
            model=model,
            voice=voice,
            input=text,
            response_format="mp3",
        )
        audio_bytes = response.read() if hasattr(response, "read") else getattr(response, "content", b"")
        return audio_bytes, getattr(response, "request_id", None)


class LLMJSONClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or Settings()
        self._client: AsyncOpenAI | None = None

    def _get_client(self) -> AsyncOpenAI:
        if self._client is not None:
            return self._client

        provider = self._settings.llm_provider
        if provider not in {LLMProvider.OPENAI, LLMProvider.DEEPSEEK}:
            raise ValueError(f"Unknown LLM provider: {provider}")
        api_key = self._settings.llm_api_key
        if not api_key:
            raise ValueError("LLM_API_KEY is required for real LLM execution")

        client_kwargs: dict[str, str] = {"api_key": api_key}
        if provider == LLMProvider.DEEPSEEK:
            client_kwargs["base_url"] = self._settings.llm_base_url or "https://api.deepseek.com/v1"
        elif self._settings.llm_base_url:
            client_kwargs["base_url"] = self._settings.llm_base_url

        self._client = AsyncOpenAI(**client_kwargs)
        return self._client

    async def generate_json(self, *, payload: OpenAIChatPayload, model: str) -> LLMResult:
        client = self._get_client()
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": payload.system_prompt},
                {"role": "user", "content": payload.user_prompt},
            ],
            max_tokens=payload.max_tokens,
            response_format={"type": "json_object"},
            temperature=0.2,
        )

        raw_content = response.choices[0].message.content or "{}"
        content = json.loads(raw_content)
        usage = response.usage

        return LLMResult(
            content=content,
            model=response.model or model,
            request_id=response.id,
            usage=LLMUsage(
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
            ) if usage else None,
            raw_content=raw_content,
        )
