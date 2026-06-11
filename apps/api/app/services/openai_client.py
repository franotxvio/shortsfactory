from __future__ import annotations

import json
from dataclasses import dataclass

from openai import AsyncOpenAI

from app.core.config import Settings
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
            ),
            raw_content=raw_content,
        )

    async def generate_tts_audio(
        self,
        *,
        text: str,
        model: str,
        voice: str,
    ) -> tuple[bytes, str | None]:
        response = await self._client.audio.speech.create(
            model=model,
            voice=voice,
            input=text,
            response_format="mp3",
        )
        audio_bytes = response.read() if hasattr(response, "read") else getattr(response, "content", b"")
        return audio_bytes, getattr(response, "request_id", None)
