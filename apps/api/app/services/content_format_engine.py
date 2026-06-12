from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SUPPORTED_CONTENT_FORMATS = {"football_quiz", "general_quiz", "would_you_rather"}
DEFAULT_CONTENT_FORMAT = "general_quiz"
DEFAULT_LANGUAGE = "en"

FORMAT_CHANNEL_SLUGS = {
    "football-quiz": "football_quiz",
    "general-quiz": "general_quiz",
    "would-you-rather": "would_you_rather",
}

FORMAT_VISUAL_TEMPLATES = {
    "football_quiz": "football_quiz",
    "general_quiz": "general_quiz",
    "would_you_rather": "would_you_rather",
}

FORMAT_TOPIC_BANKS = {
    "football_quiz": [
        "Guess the player from 3 clues",
        "Prime Messi vs prime Ronaldo",
        "Player vs player: Haaland or Mbappe",
        "Which club has more Champions League titles?",
        "Guess the player by club history",
    ],
    "general_quiz": [
        "Guess the country from 3 clues",
        "Logo quiz: can you name it?",
        "Famous person by 3 hints",
        "Odd one out: red, blue, green, banana",
        "Which one is the capital city?",
    ],
    "would_you_rather": [
        "Would you rather debug at 3AM or ship broken code?",
        "Would you rather sprint with no coffee or no Wi-Fi?",
        "Would you rather fix bugs or write tests forever?",
        "Would you rather be late or be wrong?",
        "Would you rather code fast or sleep well?",
    ],
}


@dataclass(slots=True)
class ContentFormatPack:
    content_format: str
    title: str
    hook: str
    body_blocks: list[str]
    call_to_action: str
    estimated_duration_seconds: int
    style_tone: str
    visual_template: str
    scene_labels: list[str]
    language: str = DEFAULT_LANGUAGE


def normalize_content_format(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower().replace("-", "_")
    if normalized in SUPPORTED_CONTENT_FORMATS:
        return normalized
    return None


def infer_content_format(*, channel_slug: str | None = None, explicit_format: str | None = None) -> str | None:
    normalized = normalize_content_format(explicit_format)
    if normalized is not None:
        return normalized
    if not channel_slug:
        return None
    channel_key = channel_slug.strip().lower()
    mapped = FORMAT_CHANNEL_SLUGS.get(channel_key)
    if mapped:
        return mapped
    return None


def default_visual_template_for_format(content_format: str | None) -> str:
    normalized = normalize_content_format(content_format)
    if normalized is None:
        return "default"
    return FORMAT_VISUAL_TEMPLATES.get(normalized, "default")


def build_content_format_topics(content_format: str, count: int) -> list[str]:
    normalized = _require_content_format(content_format)
    if count < 1:
        raise ValueError("count must be at least 1")
    bank = list(FORMAT_TOPIC_BANKS[normalized])
    if count <= len(bank):
        return bank[:count]

    topics = list(bank)
    suffix = 2
    while len(topics) < count:
        for topic in bank:
            if len(topics) >= count:
                break
            topics.append(f"{topic} - round {suffix}")
        suffix += 1
    return topics


def build_content_format_pack(
    content_format: str,
    *,
    topic: str,
    target_duration_seconds: int | None = None,
    language: str | None = None,
) -> ContentFormatPack:
    normalized = _require_content_format(content_format)
    if normalized == "football_quiz":
        return _build_football_quiz_pack(topic=topic, target_duration_seconds=target_duration_seconds, language=language)
    if normalized == "general_quiz":
        return _build_general_quiz_pack(topic=topic, target_duration_seconds=target_duration_seconds, language=language)
    if normalized == "would_you_rather":
        return _build_would_you_rather_pack(topic=topic, target_duration_seconds=target_duration_seconds, language=language)
    raise ValueError(f"Unsupported content format: {content_format}")


def _build_football_quiz_pack(
    *,
    topic: str,
    target_duration_seconds: int | None,
    language: str | None,
) -> ContentFormatPack:
    topic_text = topic.strip() or "Football quiz"
    normalized = topic_text.lower()
    if "prime" in normalized and "vs" in normalized:
        hook = "Prime showdown:"
        body_blocks = [
            "left side: pace and goals.",
            "right side: control and trophies.",
            "who wins the prime debate?",
            "answer: the crowd splits again.",
        ]
    elif "club" in normalized and "history" in normalized:
        hook = "Club history quiz:"
        body_blocks = [
            "clue one: old-school dominance.",
            "clue two: trophy cabinet overload.",
            "clue three: the badge says it all.",
            "answer: name the club now.",
        ]
    elif "player vs player" in normalized or "vs" in normalized:
        hook = "Player vs player:"
        body_blocks = [
            "player A: raw pace.",
            "player B: better finishing.",
            "who takes the win today?",
            "drop your pick before the reveal.",
        ]
    else:
        hook = "Guess the player:"
        body_blocks = [
            "clue one: big game mentality.",
            "clue two: played for a giant club.",
            "clue three: fans still argue about him.",
            "name the player now.",
        ]
    duration = _resolve_duration(target_duration_seconds, base=10, minimum=8, maximum=15, scene_count=len(body_blocks) + 1)
    return ContentFormatPack(
        content_format="football_quiz",
        title=f"Football quiz: {topic_text}",
        hook=hook,
        body_blocks=body_blocks[:5],
        call_to_action="",
        estimated_duration_seconds=duration,
        style_tone="football_quiz",
        visual_template="football_quiz",
        scene_labels=["hook", *[f"scene_{index + 1}" for index in range(len(body_blocks[:5]))]],
        language=language or DEFAULT_LANGUAGE,
    )


def _build_general_quiz_pack(
    *,
    topic: str,
    target_duration_seconds: int | None,
    language: str | None,
) -> ContentFormatPack:
    topic_text = topic.strip() or "General quiz"
    normalized = topic_text.lower()
    if "country" in normalized:
        hook = "Guess the country:"
        body_blocks = [
            "clue one: one famous landmark.",
            "clue two: a capital city hint.",
            "clue three: flag colors flash on screen.",
            "answer: lock in your guess.",
        ]
    elif "logo" in normalized:
        hook = "Logo quiz:"
        body_blocks = [
            "clue one: one color dominates.",
            "clue two: you see it every day.",
            "clue three: the shape gives it away.",
            "answer: can you name it?",
        ]
    elif "famous person" in normalized or "person" in normalized:
        hook = "Guess the person:"
        body_blocks = [
            "clue one: one iconic quote.",
            "clue two: a career everyone knows.",
            "clue three: the internet recognizes them.",
            "answer: say the name.",
        ]
    else:
        hook = "Odd one out:"
        body_blocks = [
            "three fit the pattern.",
            "one item breaks it.",
            "spot the odd choice fast.",
            "answer: reveal in one second.",
        ]
    duration = _resolve_duration(target_duration_seconds, base=10, minimum=8, maximum=15, scene_count=len(body_blocks) + 1)
    return ContentFormatPack(
        content_format="general_quiz",
        title=f"General quiz: {topic_text}",
        hook=hook,
        body_blocks=body_blocks[:5],
        call_to_action="",
        estimated_duration_seconds=duration,
        style_tone="general_quiz",
        visual_template="general_quiz",
        scene_labels=["hook", *[f"scene_{index + 1}" for index in range(len(body_blocks[:5]))]],
        language=language or DEFAULT_LANGUAGE,
    )


def _build_would_you_rather_pack(
    *,
    topic: str,
    target_duration_seconds: int | None,
    language: str | None,
) -> ContentFormatPack:
    topic_text = topic.strip() or "Would you rather"
    normalized = topic_text.lower()
    if "coffee" in normalized and "wifi" in normalized:
        hook = "Would you rather:"
        body_blocks = [
            "option A: no coffee.",
            "option B: no Wi-Fi.",
            "vote before the timer ends.",
            "the answer is your worst nightmare.",
        ]
    elif "debug" in normalized:
        hook = "Would you rather:"
        body_blocks = [
            "option A: debug forever.",
            "option B: ship with one bug.",
            "choose the lesser evil.",
            "the internet is judging you.",
        ]
    else:
        hook = "Would you rather:"
        body_blocks = [
            "option A on the left.",
            "option B on the right.",
            "pick your side now.",
            "reveal in 3, 2, 1.",
        ]
    duration = _resolve_duration(target_duration_seconds, base=9, minimum=8, maximum=15, scene_count=len(body_blocks) + 1)
    return ContentFormatPack(
        content_format="would_you_rather",
        title=f"Would you rather: {topic_text}",
        hook=hook,
        body_blocks=body_blocks[:5],
        call_to_action="",
        estimated_duration_seconds=duration,
        style_tone="would_you_rather",
        visual_template="would_you_rather",
        scene_labels=["hook", *[f"scene_{index + 1}" for index in range(len(body_blocks[:5]))]],
        language=language or DEFAULT_LANGUAGE,
    )


def _resolve_duration(
    target_duration_seconds: int | None,
    *,
    base: int,
    minimum: int,
    maximum: int,
    scene_count: int,
) -> int:
    if isinstance(target_duration_seconds, int) and target_duration_seconds > 0:
        return max(minimum, min(target_duration_seconds, maximum))
    estimated = max(base, scene_count * 2)
    return max(minimum, min(estimated, maximum))


def _require_content_format(content_format: str) -> str:
    normalized = normalize_content_format(content_format)
    if normalized is None:
        raise ValueError("Unsupported content format. Allowed values: football_quiz, general_quiz, would_you_rather")
    return normalized
