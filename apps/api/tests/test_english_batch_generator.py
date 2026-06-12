from __future__ import annotations

from datetime import date

from app.services.english_batch_generator import (
    DEFAULT_CHANNEL_NAME,
    DEFAULT_CHANNEL_SLUG,
    DEFAULT_SCRIPT_MODE,
    DEFAULT_TARGET_DURATION_SECONDS,
    DEFAULT_VISUAL_TEMPLATE,
    BatchVideoOutcome,
    build_batch_specs,
    render_batch_report,
)


def test_build_batch_specs_uses_english_dev_defaults() -> None:
    specs = build_batch_specs()

    assert len(specs) == 5
    assert [item.topic for item in specs] == [
        "Beginner programmer vs senior programmer",
        "When your code works first try",
        "Python error messages be like",
        "JavaScript developers at 3AM",
        "The bug disappears when you share your screen",
    ]
    assert all(item.channel_slug == DEFAULT_CHANNEL_SLUG for item in specs)
    assert all(item.channel_name == DEFAULT_CHANNEL_NAME for item in specs)
    assert all(item.execution_mode == "fake" for item in specs)
    assert all(item.script_mode == DEFAULT_SCRIPT_MODE for item in specs)
    assert all(item.target_duration_seconds == DEFAULT_TARGET_DURATION_SECONDS for item in specs)
    assert all(item.visual_template == DEFAULT_VISUAL_TEMPLATE for item in specs)


def test_render_batch_report_includes_quality_and_paths() -> None:
    report = render_batch_report(
        date(2026, 6, 12),
        [
            BatchVideoOutcome(
                index=1,
                topic="Beginner programmer vs senior programmer",
                title="Beginner programmer vs senior programmer",
                channel_slug=DEFAULT_CHANNEL_SLUG,
                video_id=101,
                slug="beginner-vs-senior",
                final_path="storage/renders/finals/beginner-vs-senior.mp4",
                caption_path="storage/captions/beginner-vs-senior.srt",
                export_path="storage/exports/beginner-vs-senior",
                duration_seconds=10.0,
                readiness="ready",
                visual_template=DEFAULT_VISUAL_TEMPLATE,
                stage_status="final_rendered",
                quality_ok=True,
            ),
            BatchVideoOutcome(
                index=2,
                topic="Python error messages be like",
                title="Python error messages be like",
                channel_slug=DEFAULT_CHANNEL_SLUG,
                video_id=102,
                slug="python-errors",
                final_path="storage/renders/finals/python-errors.mp4",
                caption_path="storage/captions/python-errors.srt",
                export_path="storage/exports/python-errors",
                duration_seconds=2.0,
                readiness="missing_items",
                visual_template=DEFAULT_VISUAL_TEMPLATE,
                stage_status="final_rendered",
                quality_ok=False,
                error_message="duration gate failed",
            ),
        ],
        channel_slug=DEFAULT_CHANNEL_SLUG,
        channel_name=DEFAULT_CHANNEL_NAME,
    )

    assert "# English Shorts Batch Report" in report
    assert "- generated_videos: 2" in report
    assert "beginner-vs-senior" in report
    assert "duration gate failed" in report
    assert "OK" in report
    assert "FAIL" in report

