from __future__ import annotations

import pytest

from app.services.content_format_engine import (
    build_content_format_pack,
    build_content_format_topics,
    infer_content_format,
    normalize_content_format,
)


@pytest.mark.parametrize(
    ("content_format", "topic", "expected_hook_fragment", "expected_body_fragment"),
    [
        ("football_quiz", "Prime Messi vs prime Ronaldo", "Prime showdown:", "who wins the prime debate?"),
        ("general_quiz", "Guess the country from 3 clues", "Guess the country:", "flag colors flash on screen."),
        ("would_you_rather", "Would you rather debug at 3AM or ship broken code?", "Would you rather:", "option A:"),
    ],
)
def test_build_content_format_pack_returns_native_short_form_structure(
    content_format: str,
    topic: str,
    expected_hook_fragment: str,
    expected_body_fragment: str,
) -> None:
    pack = build_content_format_pack(content_format, topic=topic, target_duration_seconds=10, language="en")

    assert pack.content_format == normalize_content_format(content_format)
    assert pack.estimated_duration_seconds <= 15
    assert 8 <= pack.estimated_duration_seconds <= 15
    assert len(pack.body_blocks) <= 5
    assert pack.hook.startswith(expected_hook_fragment)
    assert any(expected_body_fragment in body_block for body_block in pack.body_blocks)
    assert pack.visual_template == normalize_content_format(content_format)


def test_build_content_format_topics_are_unique_for_larger_batches() -> None:
    topics = build_content_format_topics("football_quiz", 8)

    assert len(topics) == 8
    assert len(set(topics)) == len(topics)
    assert any("round" in topic for topic in topics[5:])


@pytest.mark.parametrize(
    ("channel_slug", "expected"),
    [
        ("football-quiz", "football_quiz"),
        ("general-quiz", "general_quiz"),
        ("would-you-rather", "would_you_rather"),
        ("unknown-channel", None),
    ],
)
def test_infer_content_format_from_channel_slug(channel_slug: str, expected: str | None) -> None:
    assert infer_content_format(channel_slug=channel_slug) == expected
