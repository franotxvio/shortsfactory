from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

DEFAULT_CHANNEL_SLUG = "english-dev-shorts"
DEFAULT_CHANNEL_NAME = "English Dev Shorts"
DEFAULT_VISUAL_TEMPLATE = "viral_reels"
DEFAULT_SCRIPT_MODE = "viral_micro_short"
DEFAULT_TARGET_DURATION_SECONDS = 10
DEFAULT_VIDEO_COUNT = 5

DEFAULT_TOPICS = [
    "Beginner programmer vs senior programmer",
    "When your code works first try",
    "Python error messages be like",
    "JavaScript developers at 3AM",
    "The bug disappears when you share your screen",
]


@dataclass(slots=True)
class BatchVideoSpec:
    index: int
    topic: str
    title: str
    channel_slug: str = DEFAULT_CHANNEL_SLUG
    channel_name: str = DEFAULT_CHANNEL_NAME
    execution_mode: str = "fake"
    script_mode: str = DEFAULT_SCRIPT_MODE
    target_duration_seconds: int = DEFAULT_TARGET_DURATION_SECONDS
    visual_template: str = DEFAULT_VISUAL_TEMPLATE


@dataclass(slots=True)
class BatchVideoOutcome:
    index: int
    topic: str
    title: str
    channel_slug: str
    video_id: int | None
    slug: str | None
    final_path: str | None
    caption_path: str | None
    export_path: str | None
    duration_seconds: float | None
    readiness: str
    visual_template: str
    stage_status: str | None = None
    quality_ok: bool = False
    error_message: str | None = None


def build_batch_specs(
    count: int = DEFAULT_VIDEO_COUNT,
    *,
    channel_slug: str = DEFAULT_CHANNEL_SLUG,
    channel_name: str = DEFAULT_CHANNEL_NAME,
) -> list[BatchVideoSpec]:
    if count < 1:
        raise ValueError("count must be at least 1")

    topics = list(DEFAULT_TOPICS)
    specs: list[BatchVideoSpec] = []
    for index in range(count):
        topic = topics[index % len(topics)]
        topic_label = topic if count == 1 else f"{topic}"
        specs.append(
            BatchVideoSpec(
                index=index + 1,
                topic=topic,
                title=topic_label,
                channel_slug=channel_slug,
                channel_name=channel_name,
            )
        )
    return specs


def render_batch_report(
    batch_date: date,
    outcomes: list[BatchVideoOutcome],
    *,
    channel_slug: str = DEFAULT_CHANNEL_SLUG,
    channel_name: str = DEFAULT_CHANNEL_NAME,
) -> str:
    lines = [
        "# English Shorts Batch Report",
        "",
        f"- date: {batch_date.isoformat()}",
        f"- channel_slug: {channel_slug}",
        f"- channel_name: {channel_name}",
        f"- generated_videos: {len(outcomes)}",
        "",
        "| # | topic | video_id | slug | title | duration | final_path | export_path | readiness | quality |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for outcome in outcomes:
        lines.append(
            "| {index} | {topic} | {video_id} | {slug} | {title} | {duration} | {final_path} | {export_path} | {readiness} | {quality} |".format(
                index=outcome.index,
                topic=_escape_md(outcome.topic),
                video_id=outcome.video_id if outcome.video_id is not None else "-",
                slug=_escape_md(outcome.slug or "-"),
                title=_escape_md(outcome.title),
                duration=_format_duration(outcome.duration_seconds),
                final_path=_escape_md(outcome.final_path or "-"),
                export_path=_escape_md(outcome.export_path or "-"),
                readiness=_escape_md(outcome.readiness),
                quality="OK" if outcome.quality_ok else "FAIL",
            )
        )

    failed = [item for item in outcomes if not item.quality_ok]
    lines.extend(
        [
            "",
            "## Summary",
            f"- ok: {len(outcomes) - len(failed)}",
            f"- failed: {len(failed)}",
        ]
    )
    if failed:
        lines.append("")
        lines.append("## Failures")
        for item in failed:
            reason = item.error_message or "quality gate failed"
            lines.append(f"- #{item.index} {item.topic}: {reason}")
    return "\n".join(lines) + "\n"


def _format_duration(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.3f}s"


def _escape_md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()

