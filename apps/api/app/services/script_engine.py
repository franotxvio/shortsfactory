from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.core import Channel, CostLog, LLMCache, Script, Video
from app.models.enums import LifecycleStatus, LLMProvider, VideoExecutionMode, VideoStageStatus, WorkflowStatus
from app.services.content_format_engine import build_content_format_pack, infer_content_format, normalize_content_format
from app.services.llm_types import LLMResult, LLMUsage
from app.services.openai_client import OpenAIChatPayload, LLMJSONClient


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


_VIRAL_MICRO_SHORT_STYLE = "viral_micro_short"
_VIRAL_MICRO_SHORT_MAX_DURATION_SECONDS = 15
_VIRAL_MICRO_SHORT_DEFAULT_DURATION_SECONDS = 12


def _normalize_style_tone_value(value: str | None) -> str:
    return _normalize_reason_tag(value or "")


def _is_viral_micro_short_mode(style_tone: str | None, target_duration_seconds: int | None) -> bool:
    normalized_style = _normalize_style_tone_value(style_tone)
    if normalized_style in {
        _VIRAL_MICRO_SHORT_STYLE,
        "viral",
        "micro_short",
        "microshort",
        "short_viral",
    }:
        return True
    return isinstance(target_duration_seconds, int) and 0 < target_duration_seconds <= _VIRAL_MICRO_SHORT_MAX_DURATION_SECONDS


def _normalize_language_value(value: str | None) -> str:
    normalized = _normalize_reason_tag(value or "")
    if normalized in {"en", "en-us", "en-gb", "english", "eng"}:
        return "en"
    if normalized in {"pt", "pt-br", "pt-brasil", "portuguese", "portugues"}:
        return "pt"
    return normalized


def _is_english_language(value: str | None) -> bool:
    return _normalize_language_value(value) == "en"


def _is_supported_content_format_mode(content_format: str | None) -> bool:
    return normalize_content_format(content_format) is not None


def _short_topic_label(topic: str) -> str:
    topic_text = topic.strip() or "o tema"
    normalized = unicodedata.normalize("NFKD", topic_text).encode("ascii", "ignore").decode("ascii").lower()
    for prefix in (
        "como aprender ",
        "como fazer ",
        "como ",
        "aprenda ",
        "aprendendo ",
        "tutorial de ",
        "guia de ",
    ):
        if normalized.startswith(prefix):
            topic_text = topic_text[len(prefix) :]
            break
    topic_text = re.split(r"\s+(?:vs|versus|contra|x)\s+|/", topic_text, maxsplit=1, flags=re.IGNORECASE)[0]
    topic_text = topic_text.strip(" -:;,.")
    return topic_text or "o tema"


def _looks_like_persona_topic(topic: str) -> bool:
    normalized = _normalize_reason_tag(_short_topic_label(topic))
    keywords = {
        "programador",
        "developer",
        "dev",
        "tester",
        "engenheiro",
        "engineer",
        "iniciante",
        "junior",
        "senior",
        "estudante",
        "aprendiz",
        "persona",
        "pessoa",
        "time",
        "equipe",
        "homem",
        "mulher",
    }
    return any(keyword in normalized for keyword in keywords)


def _persona_contrast_label(topic: str) -> str:
    normalized = _normalize_reason_tag(_short_topic_label(topic))
    if "tester" in normalized:
        return "tester real"
    if "developer" in normalized or "dev" in normalized:
        return "dev real"
    if "engineer" in normalized or "engenheiro" in normalized:
        return "engineer real"
    if "programador" in normalized:
        return "programador real"
    words = _short_topic_label(topic).split()
    if words:
        return f"{words[0]} real"
    return "real"


def _viral_micro_short_hook(topic: str) -> str:
    topic_label = _short_topic_label(topic)
    if len(topic_label) <= 18:
        return f"Seu primeiro erro em {topic_label}:"
    if len(topic_label) <= 28:
        return f"{topic_label}:"
    words = topic_label.split()
    if len(words) >= 2:
        return f"{' '.join(words[:2])}:"
    return f"{topic_label[:24].strip()}:"


def _viral_micro_short_body_blocks(topic: str) -> list[str]:
    topic_label = _short_topic_label(topic)
    topic_lower = topic_label.lower()
    if _looks_like_persona_topic(topic):
        contrast_label = _persona_contrast_label(topic)
        return [
            "vou estudar tudo antes de comecar.",
            f"{contrast_label}:",
            "quebra tudo.",
            "e pesquisa no Google.",
        ]

    hook_seed = int(hashlib.sha256(topic_label.encode("utf-8")).hexdigest()[:2], 16)
    variants = [
        [
            "voce tenta decorar tudo.",
            "codigo bom nao nasce decorado.",
            "nasce testado.",
        ],
        [
            "voce quer entender tudo de uma vez.",
            "mas o atalho e testar pequeno.",
            "e repetir ate fazer sentido.",
        ],
        [
            "voce comemora quando funciona.",
            "quem tem experiencia desconfia.",
            "e roda de novo.",
        ],
        [
            "voce le a solucao pronta.",
            "profissional de verdade quebra o problema.",
            "e reconstrói sozinho.",
        ],
    ]
    return variants[hook_seed % len(variants)]


def _build_beats(body_blocks: list[str], call_to_action: str) -> list[str]:
    beats = ["hook", *[f"body_{index + 1}" for index in range(len(body_blocks))]]
    if call_to_action.strip():
        beats.append("cta")
    return beats


def _extract_content_format_from_prompt(prompt: str) -> str | None:
    match = re.search(r"content format:\s*([a-z0-9_-]+)", prompt.lower())
    if not match:
        return None
    return normalize_content_format(match.group(1))


def _coerce_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for entry in value:
        text = str(entry).strip()
        if text:
            items.append(text)
    return items


def _normalize_reason_tag(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return normalized.lower().strip()


def _default_body_blocks(topic: str) -> list[str]:
    topic_text = topic.strip() or "o tema"
    return [
        f"Primeiro, simplifique {topic_text} em uma ideia central que a pessoa entenda sem esforço.",
        "Depois, mostre um passo pratico para transformar a explicacao em acao imediata.",
        "Em seguida, destaque o ganho direto para deixar claro por que isso importa agora.",
        f"Se quiser dar mais profundidade, conecte {topic_text} a um exemplo simples do dia a dia.",
        "Feche reforcando o proximo passo mais facil para a audiencia agir hoje.",
    ]


def _build_consolidated_script_text(hook: str, body_blocks: list[str], call_to_action: str) -> str:
    parts = [part.strip() for part in [hook, *body_blocks, call_to_action] if part.strip()]
    return "\n\n".join(parts)


def _normalize_script_payload(
    payload: dict[str, object],
    *,
    topic: str,
    hook_text: str,
    style_tone: str | None = None,
    default_call_to_action: str | None = None,
    target_duration_seconds: int | None = None,
    language: str | None = None,
    content_format: str | None = None,
) -> dict[str, object]:
    default_title = f"Short script: {topic}" if _normalize_language_value(language or str(payload.get("language") or payload.get("language_code") or "")) == "en" else f"Roteiro curto: {topic}"
    title = str(payload.get("title") or default_title).strip()
    style_tone = str(style_tone or payload.get("style_tone") or payload.get("tone") or "didatico e direto").strip()
    language_value = _normalize_language_value(language or str(payload.get("language") or payload.get("language_code") or ""))
    content_format_value = normalize_content_format(
        content_format or str(payload.get("content_format") or payload.get("contentFormat") or "")
    )
    viral_mode = _is_viral_micro_short_mode(style_tone, target_duration_seconds) or content_format_value is not None

    if content_format_value is not None:
        format_pack = build_content_format_pack(
            content_format_value,
            topic=topic,
            target_duration_seconds=target_duration_seconds,
            language=language_value or None,
        )
    else:
        format_pack = None

    if format_pack is not None:
        hook = str(payload.get("hook") or hook_text or format_pack.hook).strip()
        body_blocks = _coerce_string_list(payload.get("body_blocks")) or list(format_pack.body_blocks)
        if len(body_blocks) < 3:
            body_blocks.extend(format_pack.body_blocks[len(body_blocks) : 3])
        body_blocks = body_blocks[:5]
        call_to_action = str(payload.get("call_to_action") or payload.get("cta") or format_pack.call_to_action).strip()
        estimated_duration_seconds = (
            target_duration_seconds
            if isinstance(target_duration_seconds, int) and target_duration_seconds > 0
            else format_pack.estimated_duration_seconds
        )
        style_tone = format_pack.style_tone
        title = str(payload.get("title") or format_pack.title).strip()
        script_text = str(payload.get("script") or "").strip() or _build_consolidated_script_text(hook, body_blocks, call_to_action)
        beats = _coerce_string_list(payload.get("beats")) or _build_beats(body_blocks, call_to_action)
    elif viral_mode:
        hook = str(payload.get("hook") or hook_text or _viral_micro_short_hook(topic, language=language_value)).strip()
        if len(hook) > 40:
            hook = _viral_micro_short_hook(topic, language=language_value)
        body_blocks = _coerce_string_list(payload.get("body_blocks"))
        if _is_english_language(language_value):
            if not body_blocks:
                body_blocks = _english_viral_micro_short_body_blocks(topic)
            if len(body_blocks) < 3:
                defaults = _english_viral_micro_short_body_blocks(topic)
                body_blocks.extend(defaults[len(body_blocks) : 3])
            body_blocks = body_blocks[:5]
            call_to_action = ""
        elif _looks_like_persona_topic(topic):
            body_blocks = _viral_micro_short_body_blocks(topic, language=language_value)[:4]
        if not body_blocks:
            script_text = str(payload.get("script") or "").strip()
            if script_text:
                split_blocks = [part.strip() for part in re.split(r"(?<=[.!?])\s+", script_text) if part.strip()]
                body_blocks = split_blocks[:3]
        if len(body_blocks) < 3:
            defaults = _viral_micro_short_body_blocks(topic, language=language_value)
            body_blocks.extend(defaults[len(body_blocks) : 3])
        body_blocks = body_blocks[:5]
        call_to_action = "" if _is_english_language(language_value) else str(payload.get("call_to_action") or payload.get("cta") or "").strip()
        if isinstance(target_duration_seconds, int) and target_duration_seconds > 0:
            estimated_duration_seconds = max(
                6,
                min(target_duration_seconds, _VIRAL_MICRO_SHORT_MAX_DURATION_SECONDS),
            )
        else:
            estimated_duration_seconds = _VIRAL_MICRO_SHORT_DEFAULT_DURATION_SECONDS
        style_tone = _VIRAL_MICRO_SHORT_STYLE
    else:
        hook = str(payload.get("hook") or hook_text or f"Voce ja viu {topic} por este angulo?").strip()
        body_blocks = _coerce_string_list(payload.get("body_blocks"))
        if not body_blocks:
            script_text = str(payload.get("script") or "").strip()
            if script_text:
                split_blocks = [part.strip() for part in re.split(r"(?<=[.!?])\s+", script_text) if part.strip()]
                body_blocks = split_blocks[:5]
        if len(body_blocks) < 3:
            defaults = _default_body_blocks(topic)
            body_blocks.extend(defaults[len(body_blocks) : 3])
        body_blocks = body_blocks[:5]

        call_to_action = str(
            default_call_to_action
            or payload.get("call_to_action")
            or payload.get("cta")
            or "Se isso te ajudou, salva o video e compartilha com alguem que precisa simplificar isso."
        ).strip()
        estimated_duration_raw = payload.get("estimated_duration_seconds")
        if isinstance(target_duration_seconds, int) and target_duration_seconds > 0:
            estimated_duration_seconds = target_duration_seconds
        elif isinstance(estimated_duration_raw, int) and estimated_duration_raw > 0:
            estimated_duration_seconds = estimated_duration_raw
        else:
            estimated_duration_seconds = max(18, 12 + len(body_blocks) * 6)

    script_text = str(payload.get("script") or "").strip()
    if not script_text:
        script_text = _build_consolidated_script_text(hook, body_blocks, call_to_action)

    beats = _coerce_string_list(payload.get("beats"))
    if not beats:
        beats = _build_beats(body_blocks, call_to_action)

    return {
        "title": title,
        "hook": hook,
        "body_blocks": body_blocks,
        "call_to_action": call_to_action,
        "estimated_duration_seconds": estimated_duration_seconds,
        "style_tone": style_tone,
        "script": script_text,
        "beats": beats,
        "language": language_value or payload.get("language") or payload.get("language_code"),
        "content_format": content_format_value,
    }


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
    hook: str | None = None
    body_blocks: list[str] | None = None
    call_to_action: str | None = None
    estimated_duration_seconds: int | None = None
    style_tone: str | None = None
    script_text: str | None = None
    content_brain_context_used: bool = False
    winning_signals_count: int = 0
    weak_signals_count: int = 0
    applied_reason_tags: list[str] | None = None
    content_format: str | None = None


def _english_viral_micro_short_body_blocks(topic: str) -> list[str]:
    topic_label = _short_topic_label(topic)
    normalized_topic = _normalize_reason_tag(topic)
    if "beginner programmer" in normalized_topic and "senior programmer" in normalized_topic:
        return [
            "copies the solution.",
            "Senior programmer:",
            "breaks the problem apart.",
            "then fixes it twice.",
        ]
    if "when your code works first try" in normalized_topic:
        return [
            "you do not celebrate.",
            "you get nervous.",
            "and run it again.",
        ]
    if "python error messages" in normalized_topic:
        return [
            "one missing space.",
            "47 lines of panic.",
            "welcome to programming.",
        ]
    if "javascript developers at 3am" in normalized_topic or "javascript developers at 3 a.m." in normalized_topic:
        return [
            "the bug is still alive.",
            "coffee is gone.",
            "you debug with one eye open.",
        ]
    if "the bug disappears when you share your screen" in normalized_topic or (
        "bug" in normalized_topic and "share your screen" in normalized_topic
    ):
        return [
            "suddenly behaves.",
            "like it pays rent.",
            "on your laptop.",
        ]
    if "it works on my machine" in normalized_topic:
        return [
            "works in one tab.",
            "dies in the demo.",
            "classic developer energy.",
        ]
    if "merge conflict" in normalized_topic:
        return [
            "two people touched the same line.",
            "git calls it peace.",
            "you call it therapy.",
        ]
    return [
        "you try the big fix first.",
        "real devs split the problem up.",
        "then ship the smallest change.",
    ]


def _viral_micro_short_hook(topic: str, *, language: str | None = None) -> str:
    topic_label = _short_topic_label(topic)
    normalized_topic = _normalize_reason_tag(topic)
    if _is_english_language(language):
        if "beginner programmer" in normalized_topic and "senior programmer" in normalized_topic:
            return "Beginner programmer:"
        if "when your code works first try" in normalized_topic:
            return "When your code works first try:"
        if "python error messages" in normalized_topic:
            return "Python error messages:"
        if "javascript developers at 3am" in normalized_topic or "javascript developers at 3 a.m." in normalized_topic:
            return "JavaScript developers at 3AM:"
        if "the bug disappears when you share your screen" in normalized_topic or (
            "bug" in normalized_topic and "share your screen" in normalized_topic
        ):
            return "The bug when you share your screen:"
        if "it works on my machine" in normalized_topic:
            return "It works on my machine:"
        if len(topic_label) <= 28:
            return f"{topic_label}:"
        words = topic_label.split()
        if len(words) >= 2:
            return f"{' '.join(words[:2])}:"
        return f"{topic_label[:24].strip()}:"

    if len(topic_label) <= 18:
        return f"Seu primeiro erro em {topic_label}:"
    if len(topic_label) <= 28:
        return f"{topic_label}:"
    words = topic_label.split()
    if len(words) >= 2:
        return f"{' '.join(words[:2])}:"
    return f"{topic_label[:24].strip()}:"


def _viral_micro_short_body_blocks(topic: str, *, language: str | None = None) -> list[str]:
    if _is_english_language(language):
        return _english_viral_micro_short_body_blocks(topic)

    topic_label = _short_topic_label(topic)
    if _looks_like_persona_topic(topic):
        contrast_label = _persona_contrast_label(topic)
        return [
            "vou estudar tudo antes de comecar.",
            f"{contrast_label}:",
            "quebra tudo.",
            "e pesquisa no Google.",
        ]

    hook_seed = int(hashlib.sha256(topic_label.encode("utf-8")).hexdigest()[:2], 16)
    variants = [
        [
            "voce tenta decorar tudo.",
            "codigo bom nao nasce decorado.",
            "nasce testado.",
        ],
        [
            "voce quer entender tudo de uma vez.",
            "mas o atalho e testar pequeno.",
            "e repetir ate fazer sentido.",
        ],
        [
            "voce comemora quando funciona.",
            "quem tem experiencia desconfia.",
            "e roda de novo.",
        ],
        [
            "voce le a solucao pronta.",
            "profissional de verdade quebra o problema.",
            "e reconstrói sozinho.",
        ],
    ]
    return variants[hook_seed % len(variants)]


class _DeterministicLLMClient:
    async def generate_json(self, *, payload: OpenAIChatPayload, model: str) -> LLMResult:
        prompt_lower = payload.system_prompt.lower()
        if "idea" in prompt_lower:
            content = {
                "idea": "Explique uma curiosidade simples em formato curto.",
                "angle": "curiosidade",
                "title": "Ideia curta",
            }
        elif "hook" in prompt_lower:
            content = {
                "hook": "Voce ja percebeu isso em menos de 10 segundos?",
                "alt_hook": "Isso vai mudar sua forma de ver o tema.",
            }
        elif "script" in prompt_lower:
            topic_match = re.search(r'about "(.+?)"', payload.user_prompt)
            topic = topic_match.group(1).strip() if topic_match else "o tema"
            user_prompt_lower = payload.user_prompt.lower()
            duration_match = re.search(r"target duration seconds:\s*(\d+)", user_prompt_lower)
            duration_seconds = int(duration_match.group(1)) if duration_match is not None else None
            language_match = re.search(r"language:\s*([a-z-]+)", user_prompt_lower)
            language = _normalize_language_value(language_match.group(1) if language_match is not None else None)
            content_format = _extract_content_format_from_prompt(payload.user_prompt)
            format_pack = (
                build_content_format_pack(
                    content_format,
                    topic=topic,
                    target_duration_seconds=duration_seconds,
                    language=language,
                )
                if content_format is not None
                else None
            )
            viral_mode = "viral_micro_short" in user_prompt_lower or (
                duration_seconds is not None and duration_seconds <= _VIRAL_MICRO_SHORT_MAX_DURATION_SECONDS
            )
            if format_pack is not None:
                hook = format_pack.hook
                body_blocks = list(format_pack.body_blocks)
                call_to_action = format_pack.call_to_action
                estimated_duration_seconds = format_pack.estimated_duration_seconds
                style_tone = format_pack.style_tone
                content = {
                    "title": format_pack.title,
                    "hook": hook,
                    "body_blocks": body_blocks,
                    "call_to_action": call_to_action,
                    "estimated_duration_seconds": estimated_duration_seconds,
                    "style_tone": style_tone,
                    "script": _build_consolidated_script_text(hook, body_blocks, call_to_action),
                    "beats": _build_beats(body_blocks, call_to_action),
                    "content_format": content_format,
                    "language": language,
                }
            elif viral_mode:
                hook = _viral_micro_short_hook(topic, language=language)
                body_blocks = _viral_micro_short_body_blocks(topic, language=language)
                call_to_action = ""
                estimated_duration_seconds = max(
                    6,
                    min(
                        duration_seconds if duration_seconds is not None else _VIRAL_MICRO_SHORT_DEFAULT_DURATION_SECONDS,
                        _VIRAL_MICRO_SHORT_MAX_DURATION_SECONDS,
                    ),
                )
                style_tone = _VIRAL_MICRO_SHORT_STYLE
                if language == "en" and body_blocks and len(body_blocks) < 3:
                    body_blocks = [*body_blocks, *_english_viral_micro_short_body_blocks(topic)][:
                        max(3, len(body_blocks))
                    ]
                content = {
                    "title": f"Short script: {topic}" if language == "en" else f"Roteiro curto: {topic}",
                    "hook": hook,
                    "body_blocks": body_blocks,
                    "call_to_action": call_to_action,
                    "estimated_duration_seconds": estimated_duration_seconds,
                    "style_tone": style_tone,
                    "script": _build_consolidated_script_text(hook, body_blocks, call_to_action),
                    "beats": _build_beats(body_blocks, call_to_action),
                }
            else:
                body_count = 3 + int(hashlib.sha256(topic.encode("utf-8")).hexdigest()[:2], 16) % 3
                body_templates = [
                    f"Primeiro, simplifique {topic} em uma ideia central que a pessoa entenda sem esforco.",
                    "Depois, mostre um passo pratico para transformar a explicacao em acao imediata.",
                    "Em seguida, destaque o ganho direto para deixar claro por que isso importa agora.",
                    f"Se quiser dar mais profundidade, conecte {topic} a um exemplo simples do dia a dia.",
                    "Feche reforcando o proximo passo mais facil para a audiencia agir hoje.",
                ]
                body_blocks = body_templates[:body_count]
                hook = f"Voce ja viu {topic} por este angulo?"
                call_to_action = "Se isso te ajudou, salva o video e compartilha com alguem que precisa simplificar isso."
                estimated_duration_seconds = 24 + len(body_blocks) * 6
                style_tone = "didatico e direto"
                content = {
                    "title": f"Short script: {topic}" if language == "en" else f"Roteiro curto: {topic}",
                    "hook": hook,
                    "body_blocks": body_blocks,
                    "call_to_action": call_to_action,
                    "estimated_duration_seconds": estimated_duration_seconds,
                    "style_tone": style_tone,
                    "script": _build_consolidated_script_text(hook, body_blocks, call_to_action),
                    "beats": _build_beats(body_blocks, call_to_action),
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
            request_id="local-fake",
            usage=None,
            raw_content=_json_dumps(content),
        )


class ScriptEngineService:
    def __init__(
        self,
        session: AsyncSession,
        llm_client: LLMJSONClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.llm_client = llm_client

    async def create_test_script(
        self,
        *,
        topic: str,
        channel_slug: str,
        channel_name: str,
        video_title: str | None = None,
        execution_mode: VideoExecutionMode = VideoExecutionMode.FAKE,
        style_tone: str | None = None,
        default_call_to_action: str | None = None,
        target_duration_seconds: int | None = None,
        language: str | None = None,
        content_brain_context: dict[str, object] | None = None,
        content_format: str | None = None,
    ) -> ScriptGenerationResult:
        effective_language = language or ("en" if channel_slug.lower().startswith("english-") else None)
        effective_content_format = infer_content_format(channel_slug=channel_slug, explicit_format=content_format)
        llm_client, provider_name, record_cost_logs = self._get_llm_client(execution_mode)
        content_brain_summary = self._normalize_content_brain_context(content_brain_context)
        viral_micro_short_mode = _is_viral_micro_short_mode(style_tone, target_duration_seconds) or effective_content_format is not None
        effective_default_call_to_action = None if viral_micro_short_mode else default_call_to_action
        async with self.session.begin():
            channel = await self._get_or_create_channel(channel_slug=channel_slug, channel_name=channel_name)

            idea = await self._generate_idea(
                topic=topic,
                llm_client=llm_client,
                provider_name=provider_name,
                record_cost_logs=record_cost_logs,
                content_format=effective_content_format,
            )
            hook = await self._generate_hook(
                topic=topic,
                idea=idea,
                llm_client=llm_client,
                provider_name=provider_name,
                record_cost_logs=record_cost_logs,
                content_format=effective_content_format,
            )
            script = await self._generate_script(
                topic=topic,
                idea=idea,
                hook=hook,
                llm_client=llm_client,
                provider_name=provider_name,
                record_cost_logs=record_cost_logs,
                style_tone=style_tone,
                default_call_to_action=effective_default_call_to_action,
                target_duration_seconds=target_duration_seconds,
                language=effective_language,
                content_brain_context=content_brain_summary,
                content_format=effective_content_format,
            )
            if execution_mode == VideoExecutionMode.FAKE and content_brain_summary is not None and not viral_micro_short_mode:
                applied_script, applied_tags = self._apply_content_brain_context_to_script(
                    script_content=dict(script.content),
                    topic=topic,
                    content_brain_context=content_brain_summary,
                    default_call_to_action=effective_default_call_to_action,
                    style_tone=style_tone,
                    target_duration_seconds=target_duration_seconds,
                )
                script.content = applied_script
                script.raw_content = _json_dumps(applied_script)
                content_brain_summary = {**content_brain_summary, "applied_reason_tags": applied_tags}
            policy = await self._policy_check(topic=topic, script=script, llm_client=llm_client, provider_name=provider_name, record_cost_logs=record_cost_logs)
            normalized_script = _normalize_script_payload(
                script.content,
                topic=topic,
                hook_text=str(hook.content.get("hook") or ""),
                style_tone=style_tone,
                default_call_to_action=default_call_to_action,
                target_duration_seconds=target_duration_seconds,
                language=effective_language,
                content_format=effective_content_format,
            )
            if effective_content_format is not None:
                format_pack = build_content_format_pack(
                    effective_content_format,
                    topic=topic,
                    target_duration_seconds=target_duration_seconds,
                    language=effective_language,
                )
                normalized_script = {
                    **normalized_script,
                    "title": format_pack.title,
                    "hook": format_pack.hook,
                    "body_blocks": list(format_pack.body_blocks),
                    "call_to_action": format_pack.call_to_action,
                    "estimated_duration_seconds": format_pack.estimated_duration_seconds,
                    "style_tone": format_pack.style_tone,
                    "script": _build_consolidated_script_text(format_pack.hook, list(format_pack.body_blocks), format_pack.call_to_action),
                    "beats": ["hook", *[f"body_{index + 1}" for index in range(len(format_pack.body_blocks))], "cta"]
                    if format_pack.call_to_action
                    else ["hook", *[f"body_{index + 1}" for index in range(len(format_pack.body_blocks))]],
                    "content_format": effective_content_format,
                }

            video_slug = f"{_slugify(topic)}-{uuid4().hex[:8]}"
            video = Video(
                channel_id=channel.id,
                title=video_title or str(normalized_script.get("title") or topic),
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
                "script": normalized_script,
                "policy": policy.content,
                "content_brain": content_brain_summary,
                "content_brain_context": content_brain_context,
                "language": effective_language,
                "content_format": effective_content_format,
            }
            script_row = Script(
                video_id=video.id,
                version=1,
                status=script_status,
                topic=topic,
                idea=str(idea.content.get("idea") or ""),
                hook=str(normalized_script.get("hook") or hook.content.get("hook") or ""),
                content=str(normalized_script.get("script") or ""),
                notes=_build_policy_notes(policy.content),
                policy_risk_score=Decimal(str(policy.content["risk_score"])),
                policy_decision=str(policy.content["decision"]),
                generation_payload=generated_payload,
                llm_model=self.settings.llm_model,
                llm_cache_key=script.content.get("cache_key"),
                llm_input_hash=script.content.get("input_hash"),
            )
            self.session.add(script_row)
            video.status = WorkflowStatus.APPROVED if script_row.status == WorkflowStatus.APPROVED else WorkflowStatus.REJECTED
            video.stage_status = VideoStageStatus.SCRIPT_APPROVED if script_row.status == WorkflowStatus.APPROVED else VideoStageStatus.DRAFT
            await self.session.flush()

            return ScriptGenerationResult(
                channel_id=channel.id,
                video_id=video.id,
                script_id=script_row.id,
                video_slug=video.slug,
                script_status=script_row.status.value,
                policy_decision=script_row.policy_decision or "rejected",
                policy_risk_score=script_row.policy_risk_score or Decimal("0"),
                hook=str(normalized_script.get("hook") or ""),
                body_blocks=list(normalized_script.get("body_blocks") or []),
                call_to_action=str(normalized_script.get("call_to_action") or ""),
                estimated_duration_seconds=int(normalized_script.get("estimated_duration_seconds") or 0) or None,
                style_tone=str(normalized_script.get("style_tone") or ""),
                script_text=str(normalized_script.get("script") or ""),
                cache_hits={
                    "idea": bool(idea.content.get("cache_hit")),
                    "hook": bool(hook.content.get("cache_hit")),
                    "script": bool(script.content.get("cache_hit")),
                    "policy": bool(policy.content.get("cache_hit")),
                },
                content_brain_context_used=bool(content_brain_summary),
                winning_signals_count=int((content_brain_summary or {}).get("winning_signals_count") or 0),
                weak_signals_count=int((content_brain_summary or {}).get("weak_signals_count") or 0),
                applied_reason_tags=list((content_brain_summary or {}).get("applied_reason_tags") or []),
                content_format=effective_content_format,
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

    def _get_llm_client(
        self,
        execution_mode: VideoExecutionMode,
    ) -> tuple[LLMJSONClient | _DeterministicLLMClient, str, bool]:
        if execution_mode == VideoExecutionMode.FAKE:
            if self.llm_client is not None:
                return self.llm_client, self.settings.llm_provider.value, True
            return _DeterministicLLMClient(), "local", False

        if self.settings.llm_provider not in {LLMProvider.OPENAI, LLMProvider.DEEPSEEK}:
            raise ValueError(f"Unknown LLM provider: {self.settings.llm_provider}")
        if not self.settings.llm_api_key:
            raise ValueError("LLM_API_KEY is required for real LLM execution")
        return LLMJSONClient(self.settings), self.settings.llm_provider.value, True

    async def _generate_idea(
        self,
        *,
        topic: str,
        llm_client: LLMJSONClient | _DeterministicLLMClient,
        provider_name: str,
        record_cost_logs: bool,
        content_format: str | None = None,
    ) -> LLMResult:
        return await self._generate_operation(
            operation="idea",
            topic=topic,
            prompt_context={"topic": topic, "content_format": content_format},
            system_prompt="You generate one concise video idea in JSON only.",
            user_prompt=(
                f'Create one short video idea about "{topic}". '
                f"{f'Content format: {content_format}. ' if content_format else ''}"
                "Return JSON with keys idea, angle, title."
            ),
            max_tokens=self.settings.openai_idea_max_tokens,
            llm_client=llm_client,
            provider_name=provider_name,
            record_cost_logs=record_cost_logs,
        )

    async def _generate_hook(
        self,
        *,
        topic: str,
        idea: LLMResult,
        llm_client: LLMJSONClient | _DeterministicLLMClient,
        provider_name: str,
        record_cost_logs: bool,
        content_format: str | None = None,
    ) -> LLMResult:
        idea_text = str(idea.content.get("idea") or "")
        return await self._generate_operation(
            operation="hook",
            topic=topic,
            prompt_context={"topic": topic, "idea": idea_text, "content_format": content_format},
            system_prompt="You generate a hook for a short-form video in JSON only.",
            user_prompt=(
                f'Create a strong hook for a short video about "{topic}" using this idea: {idea_text!r}. '
                f"{f'Content format: {content_format}. ' if content_format else ''}"
                "Return JSON with keys hook and alt_hook."
            ),
            max_tokens=self.settings.openai_hook_max_tokens,
            llm_client=llm_client,
            provider_name=provider_name,
            record_cost_logs=record_cost_logs,
        )

    async def _generate_script(
        self,
        *,
        topic: str,
        idea: LLMResult,
        hook: LLMResult,
        llm_client: LLMJSONClient | _DeterministicLLMClient,
        provider_name: str,
        record_cost_logs: bool,
        style_tone: str | None = None,
        default_call_to_action: str | None = None,
        target_duration_seconds: int | None = None,
        language: str | None = None,
        content_brain_context: dict[str, object] | None = None,
        content_format: str | None = None,
    ) -> LLMResult:
        idea_text = str(idea.content.get("idea") or "")
        hook_text = str(hook.content.get("hook") or "")
        language_value = _normalize_language_value(language)
        content_format_value = normalize_content_format(content_format or str((content_brain_context or {}).get("content_format") or ""))
        viral_micro_short_guidance = ""
        if _is_viral_micro_short_mode(style_tone, target_duration_seconds) or content_format_value is not None:
            viral_micro_short_guidance = (
                " Viral micro short mode: keep the hook strong in the first 1-2 seconds, "
                "use 3 to 5 very short body blocks, make the CTA optional or empty, and keep the final duration between 6 and 15 seconds."
            )
            if language_value == "en":
                viral_micro_short_guidance += " Write in natural English only and keep the meme-style punchline sharp."
        content_format_guidance = ""
        if content_format_value is not None:
            content_format_guidance = (
                f" Content format: {content_format_value}. "
                "Use the format's native structure and visual rhythm, keep the language native to the audience, and keep the wording extremely short."
            )
        content_brain_context_text = ""
        if content_brain_context:
            winning_patterns = content_brain_context.get("winning_patterns") or content_brain_context.get("winning_examples")
            weak_patterns = content_brain_context.get("weak_patterns") or content_brain_context.get("weak_examples")
            context_blob = {
                "winning_patterns": winning_patterns,
                "weak_patterns": weak_patterns,
                "winning_examples": winning_patterns,
                "weak_examples": weak_patterns,
                "winning_signals_count": content_brain_context.get("winning_signals_count") or content_brain_context.get("winning_count"),
                "weak_signals_count": content_brain_context.get("weak_signals_count") or content_brain_context.get("weak_count"),
            }
            content_brain_context_text = (
                " Local content-brain learning context. "
                "Use winning patterns as positive examples and weak patterns as anti-patterns. "
                f"Context: {json.dumps(context_blob, ensure_ascii=False, sort_keys=True)}."
            )
        return await self._generate_operation(
            operation="script",
            topic=topic,
            prompt_context={
                "topic": topic,
                "idea": idea_text,
                "hook": hook_text,
                "style_tone": style_tone,
                "default_call_to_action": default_call_to_action,
                "target_duration_seconds": target_duration_seconds,
                "content_brain_context": content_brain_context,
                "language": language_value or language,
                "content_format": content_format_value,
            },
            system_prompt=(
                "You write a complete short-form script in JSON only. "
                "The JSON must include hook, body_blocks, call_to_action, estimated_duration_seconds, style_tone, title, script and beats."
            ),
            user_prompt=(
                f'Write a short-form video script about "{topic}". '
                f'Idea: {idea_text!r}. Hook: {hook_text!r}. '
                f"{f'Language: {language_value}. ' if language_value else ''}"
                f"{f'Style tone: {style_tone!r}. ' if style_tone else ''}"
                f"{f'Default CTA: {default_call_to_action!r}. ' if default_call_to_action else ''}"
                f"{f'Target duration seconds: {target_duration_seconds}. ' if target_duration_seconds else ''}"
                f"{content_format_guidance}"
                f"{viral_micro_short_guidance}"
                f"{content_brain_context_text}"
                "Return JSON with keys title, hook, body_blocks, call_to_action, estimated_duration_seconds, style_tone, script and beats. "
                "Use 3 to 5 short body_blocks and keep the final script concise enough for a Shorts video."
            ),
            max_tokens=self.settings.openai_script_max_tokens,
            llm_client=llm_client,
            provider_name=provider_name,
            record_cost_logs=record_cost_logs,
        )

    def _normalize_content_brain_context(self, content_brain_context: dict[str, object] | None) -> dict[str, object] | None:
        if not content_brain_context:
            return None
        winning_patterns = self._coerce_content_brain_patterns(content_brain_context, "winning_patterns", "winning_examples")
        weak_patterns = self._coerce_content_brain_patterns(content_brain_context, "weak_patterns", "weak_examples")
        winning_count = self._coerce_positive_int(
            content_brain_context.get("winning_signals_count") or content_brain_context.get("winning_count")
        )
        weak_count = self._coerce_positive_int(
            content_brain_context.get("weak_signals_count") or content_brain_context.get("weak_count")
        )
        if winning_count is None:
            winning_count = len(winning_patterns)
        if weak_count is None:
            weak_count = len(weak_patterns)
        if not winning_patterns and not weak_patterns and winning_count == 0 and weak_count == 0:
            return None
        return {
            "channel_slug": content_brain_context.get("channel_slug"),
            "topic": content_brain_context.get("topic"),
            "winning_patterns": winning_patterns,
            "weak_patterns": weak_patterns,
            "winning_examples": winning_patterns,
            "weak_examples": weak_patterns,
            "winning_signals_count": winning_count,
            "weak_signals_count": weak_count,
        }

    def _coerce_content_brain_patterns(
        self,
        content_brain_context: dict[str, object],
        primary_key: str,
        fallback_key: str,
    ) -> list[dict[str, object]]:
        raw_patterns = content_brain_context.get(primary_key) or content_brain_context.get(fallback_key)
        if not isinstance(raw_patterns, list):
            return []
        patterns: list[dict[str, object]] = []
        for entry in raw_patterns:
            if isinstance(entry, dict):
                pattern = {
                    "video_id": entry.get("video_id"),
                    "video_slug": entry.get("video_slug"),
                    "channel_slug": entry.get("channel_slug"),
                    "topic": entry.get("topic"),
                    "notes": entry.get("notes"),
                    "reason_tags": _coerce_string_list(entry.get("reason_tags")),
                }
                patterns.append(pattern)
        return patterns

    def _coerce_positive_int(self, value: object | None) -> int | None:
        if isinstance(value, int) and value > 0:
            return value
        return None

    def _apply_content_brain_context_to_script(
        self,
        *,
        script_content: dict[str, object],
        topic: str,
        content_brain_context: dict[str, object],
        default_call_to_action: str | None,
        style_tone: str | None,
        target_duration_seconds: int | None,
    ) -> tuple[dict[str, object], list[str]]:
        winning_patterns = content_brain_context.get("winning_patterns") or []
        weak_patterns = content_brain_context.get("weak_patterns") or []
        topic_text = topic.strip() or "o tema"
        applied_reason_tags: list[str] = []
        winning_tags = self._collect_reason_tags(winning_patterns)
        weak_tags = self._collect_reason_tags(weak_patterns)
        applied_reason_tags.extend(winning_tags[:3])
        if weak_tags:
            applied_reason_tags.extend([tag for tag in weak_tags if tag not in applied_reason_tags][:2])

        normalized_winning_tags = {_normalize_reason_tag(tag) for tag in winning_tags}
        normalized_weak_tags = {_normalize_reason_tag(tag) for tag in weak_tags}
        has_curiosity = "curiosidade" in normalized_winning_tags
        has_generic_weakness = any(tag in {"generico", "generic"} for tag in normalized_weak_tags)
        has_short_hook = any(tag in {"hook", "abertura", "curto"} for tag in normalized_winning_tags)

        if has_curiosity:
            hook = f"Voce ja percebeu essa curiosidade sobre {topic_text}?"
        elif has_short_hook:
            hook = f"Esse detalhe sobre {topic_text} muda tudo em poucos segundos."
        else:
            hook = f"Voce ja viu {topic_text} por este angulo?"

        if has_generic_weakness:
            body_blocks = [
                f"Abra com um exemplo concreto de {topic_text} para evitar uma introducao generica.",
                f"Mostre um caso real que torne {topic_text} facil de imaginar.",
                "Feche com uma acao objetiva em vez de uma explicacao longa e abstrata.",
            ]
        else:
            body_blocks = [
                f"Primeiro, simplifique {topic_text} em uma ideia central que a audiencia entenda sem esforco.",
                "Depois, mostre um passo pratico para transformar a explicacao em acao imediata.",
                "Em seguida, destaque o ganho direto para deixar claro por que isso importa agora.",
            ]
        if winning_tags:
            body_blocks[-1] = f"Feche reforcando o padrao vencedor de {', '.join(winning_tags[:2])} para manter o ritmo."

        call_to_action = default_call_to_action or (
            "Se isso te ajudou, salva o video e compartilha com alguem que precisa simplificar isso."
        )
        if any(tag == "cta" for tag in normalized_winning_tags):
            call_to_action = "Se isso fez sentido, salva e manda para quem precisa ver esse atalho."

        estimated_duration_seconds = target_duration_seconds if target_duration_seconds is not None else 24 + len(body_blocks) * 6
        script_text = "\n\n".join([hook, *body_blocks, call_to_action])
        updated_script = dict(script_content)
        updated_script.update(
            {
                "hook": hook,
                "body_blocks": body_blocks,
                "call_to_action": call_to_action,
                "estimated_duration_seconds": estimated_duration_seconds,
                "style_tone": style_tone or str(updated_script.get("style_tone") or "didatico e direto"),
                "script": script_text,
                "beats": ["hook", *[f"body_{index + 1}" for index in range(len(body_blocks))], "cta"],
                "content_brain_context_used": True,
                "applied_reason_tags": applied_reason_tags,
            }
        )
        return updated_script, applied_reason_tags

    def _collect_reason_tags(self, patterns: object) -> list[str]:
        if not isinstance(patterns, list):
            return []
        collected: list[str] = []
        for entry in patterns:
            if not isinstance(entry, dict):
                continue
            for tag in _coerce_string_list(entry.get("reason_tags")):
                if tag not in collected:
                    collected.append(tag)
        return collected

    async def _policy_check(self, *, topic: str, script: LLMResult, llm_client: LLMJSONClient | _DeterministicLLMClient, provider_name: str, record_cost_logs: bool) -> LLMResult:
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
            llm_client=llm_client,
            provider_name=provider_name,
            record_cost_logs=record_cost_logs,
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
        llm_client: LLMJSONClient | _DeterministicLLMClient,
        provider_name: str,
        record_cost_logs: bool,
    ) -> LLMResult:
        model = self.settings.llm_model
        prompt_blob = _json_dumps(
            {
                "operation": operation,
                "topic": topic,
                "context": prompt_context,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "max_tokens": max_tokens,
                "model": model,
                "provider": provider_name,
            }
        )
        content_hash = _hash_content(prompt_blob)

        cached = await self.session.scalar(
            select(LLMCache).where(LLMCache.content_hash == content_hash, LLMCache.provider == provider_name)
        )
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

        result = await llm_client.generate_json(
            payload=OpenAIChatPayload(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
            ),
            model=model,
        )
        cache_key = f"{operation}:{content_hash}"
        response_text = result.raw_content or _json_dumps(result.content)
        is_estimated = result.usage is None
        if is_estimated:
            cost_usd = _estimate_cost_from_texts(system_prompt, user_prompt, response_text, self.settings)
        else:
            cost_usd = _estimate_cost(result.usage.prompt_tokens, result.usage.completion_tokens, self.settings)

        cache_row = LLMCache(
            content_hash=content_hash,
            cache_key=cache_key,
            provider=provider_name,
            model=result.model,
            prompt_hash=_hash_content(system_prompt, user_prompt),
            response_text=response_text,
            response_json=result.content,
        )
        self.session.add(cache_row)
        if record_cost_logs:
            self.session.add(
                CostLog(
                    video_id=None,
                    provider=provider_name,
                    operation=operation,
                    request_id=result.request_id,
                    model=result.model,
                    cost_usd=cost_usd,
                    estimated=is_estimated,
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
            raw_content=response_text,
        )


def _estimate_cost(prompt_tokens: int, completion_tokens: int, settings: Settings) -> Decimal:
    cost = (
        (prompt_tokens / 1_000_000) * settings.openai_input_cost_per_1m_tokens_usd
        + (completion_tokens / 1_000_000) * settings.openai_output_cost_per_1m_tokens_usd
    )
    return Decimal(str(round(cost, 6)))


def _estimate_cost_from_texts(system_prompt: str, user_prompt: str, response_text: str, settings: Settings) -> Decimal:
    prompt_tokens = _estimate_tokens(system_prompt + "\n" + user_prompt)
    completion_tokens = _estimate_tokens(response_text)
    return _estimate_cost(prompt_tokens, completion_tokens, settings)


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _build_policy_notes(policy: dict[str, object]) -> str | None:
    reasons = policy.get("reasons")
    if isinstance(reasons, list):
        return "; ".join(str(reason) for reason in reasons)
    return None
