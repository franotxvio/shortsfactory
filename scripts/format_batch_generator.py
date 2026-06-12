#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib import error, request
from urllib.parse import urljoin

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.content_format_engine import (  # noqa: E402
    DEFAULT_LANGUAGE,
    build_content_format_pack,
    build_content_format_topics,
    default_visual_template_for_format,
    infer_content_format,
)


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT = 900.0
DEFAULT_COUNT = 3
DEFAULT_OUTPUT_DIR = REPO_ROOT / "apps" / "api" / "storage" / "review" / date.today().isoformat()
SUPPORTED_FORMATS = {"football_quiz", "general_quiz", "would_you_rather"}
DEFAULT_CHANNELS = {
    "football_quiz": ("football-quiz", "Football Quiz"),
    "general_quiz": ("general-quiz", "General Quiz"),
    "would_you_rather": ("would-you-rather", "Would You Rather"),
}


@dataclass(slots=True)
class FormatVideoOutcome:
    index: int
    content_format: str
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
    quality_ok: bool
    error_message: str | None = None


def _normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/"


def _request_json(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float,
) -> dict[str, Any]:
    url = urljoin(_normalize_base_url(base_url), path.lstrip("/"))
    body_bytes = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if body_bytes is not None:
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=body_bytes, method=method, headers=headers)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            response_body = response.read().decode("utf-8")
            return json.loads(response_body) if response_body else {}
    except error.HTTPError as exc:
        error_body = exc.read().decode("utf-8")
        raise RuntimeError(f"{method} {path} failed with HTTP {exc.code}\n{error_body}") from exc
    except error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(f"API not reachable at {base_url}. Start the FastAPI app first.\n{reason}") from exc


def _request_text(base_url: str, path: str, *, timeout: float) -> str:
    url = urljoin(_normalize_base_url(base_url), path.lstrip("/"))
    req = request.Request(url, method="GET", headers={"Accept": "text/plain"})
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except error.HTTPError as exc:
        error_body = exc.read().decode("utf-8")
        raise RuntimeError(f"GET {path} failed with HTTP {exc.code}\n{error_body}") from exc
    except error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(f"API not reachable at {base_url}. Start the FastAPI app first.\n{reason}") from exc


def _print_step(name: str, detail: str) -> None:
    print(f"[OK] {name}")
    if detail:
        print(f"  {detail}")


def _extract_state_fields(payload: dict[str, Any]) -> str:
    fields = [
        "video_id",
        "content_format",
        "stage_status",
        "script_id",
        "script_status",
        "visual_template",
        "audio_path",
        "caption_path",
        "asset_path",
        "preview_path",
        "final_path",
        "export_package_dir",
        "export_metadata_path",
        "export_final_path",
        "export_preview_path",
        "export_caption_path",
        "youtube_publish_path",
    ]
    parts: list[str] = []
    for field in fields:
        value = payload.get(field)
        if value not in (None, "", [], {}):
            parts.append(f"{field}={value}")
    return " ".join(parts) if parts else "(no tracked fields)"


def _measure_duration_seconds(path_value: str) -> float:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        path_value,
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=True)
    return float(completed.stdout.strip())


def _build_topic_specs(content_format: str, count: int) -> list[dict[str, str]]:
    topics = build_content_format_topics(content_format, count)
    pack = build_content_format_pack(content_format, topic=topics[0], target_duration_seconds=10, language=DEFAULT_LANGUAGE)
    channel_slug, channel_name = DEFAULT_CHANNELS[content_format]
    specs: list[dict[str, str]] = []
    for index, topic in enumerate(topics, start=1):
        topic_pack = build_content_format_pack(content_format, topic=topic, target_duration_seconds=10, language=DEFAULT_LANGUAGE)
        specs.append(
            {
                "index": str(index),
                "content_format": content_format,
                "topic": topic,
                "title": topic_pack.title,
                "channel_slug": channel_slug,
                "channel_name": channel_name,
                "visual_template": default_visual_template_for_format(content_format),
                "hook": topic_pack.hook,
            }
        )
    _ = pack
    return specs


def _build_outcome(
    *,
    index: int,
    spec: dict[str, str],
    create_state: dict[str, Any],
    readiness: dict[str, Any],
    duration_seconds: float | None,
    error_message: str | None = None,
) -> FormatVideoOutcome:
    final_path = create_state.get("final_path")
    caption_path = create_state.get("caption_path")
    export_path = create_state.get("export_package_dir")
    quality_ok = (
        error_message is None
        and bool(final_path)
        and bool(caption_path)
        and bool(export_path)
        and create_state.get("visual_template") == default_visual_template_for_format(spec["content_format"])
        and duration_seconds is not None
        and 8 <= duration_seconds <= 15
        and readiness.get("overall_status") == "ready"
        and readiness.get("ready") is True
    )
    return FormatVideoOutcome(
        index=index,
        content_format=spec["content_format"],
        topic=spec["topic"],
        title=create_state.get("video_title") or spec["title"],
        channel_slug=create_state.get("channel_slug") or spec["channel_slug"],
        video_id=create_state.get("video_id"),
        slug=create_state.get("video_slug"),
        final_path=final_path,
        caption_path=caption_path,
        export_path=export_path,
        duration_seconds=duration_seconds,
        readiness=str(readiness.get("overall_status") or "unknown"),
        visual_template=str(create_state.get("visual_template") or default_visual_template_for_format(spec["content_format"])),
        quality_ok=quality_ok,
        error_message=error_message,
    )


def _render_report(date_value: date, outcomes: list[FormatVideoOutcome], *, content_format: str) -> str:
    lines = [
        f"# {content_format.replace('_', ' ').title()} Batch Report",
        "",
        f"- generated_at: {date_value.isoformat()}",
        f"- generated_videos: {len(outcomes)}",
        "",
    ]
    for outcome in outcomes:
        status = "OK" if outcome.quality_ok else "FAIL"
        lines.extend(
            [
                f"## {status} #{outcome.index} - {outcome.topic}",
                f"- video_id: {outcome.video_id}",
                f"- slug: {outcome.slug}",
                f"- title: {outcome.title}",
                f"- final_path: {outcome.final_path}",
                f"- caption_path: {outcome.caption_path}",
                f"- export_path: {outcome.export_path}",
                f"- duration_seconds: {outcome.duration_seconds}",
                f"- readiness: {outcome.readiness}",
                f"- visual_template: {outcome.visual_template}",
            ]
        )
        if outcome.error_message:
            lines.append(f"- error: {outcome.error_message}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a batch of local fake Shorts for review.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument(
        "--format",
        required=True,
        choices=sorted(SUPPORTED_FORMATS),
        help="Content format to generate.",
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args()


def _run_batch(base_url: str, *, timeout: float, content_format: str, count: int) -> list[FormatVideoOutcome]:
    topics = _build_topic_specs(content_format, count)
    outcomes: list[FormatVideoOutcome] = []
    channel_slug, channel_name = DEFAULT_CHANNELS[content_format]
    for spec in topics:
        create_state: dict[str, Any] = {}
        readiness_state: dict[str, Any] = {}
        try:
            create_state = _request_json(
                base_url,
                "POST",
                "/internal/videos/test",
                {
                    "topic": spec["topic"],
                    "channel_slug": channel_slug,
                    "channel_name": channel_name,
                    "video_title": spec["title"],
                    "execution_mode": "fake",
                    "style_tone": "viral_micro_short",
                    "target_duration_seconds": 10,
                    "language": DEFAULT_LANGUAGE,
                    "content_format": content_format,
                },
                timeout=timeout,
            )
            _print_step(f"create-video #{spec['index']}", _extract_state_fields(create_state))
            if create_state.get("content_format") != content_format:
                raise RuntimeError(f"Created video did not keep content_format={content_format}")

            video_id = int(create_state["video_id"])
            if str(create_state.get("script_status") or "").lower() != "approved":
                raise RuntimeError("Script should be approved for local demo batches.")

            tts_state = _request_json(
                base_url,
                "POST",
                f"/internal/videos/{video_id}/tts",
                {"execution_mode": "fake"},
                timeout=timeout,
            )
            _print_step(f"tts #{spec['index']}", _extract_state_fields(tts_state))

            captions_state = _request_json(
                base_url,
                "POST",
                f"/internal/videos/{video_id}/captions",
                {"execution_mode": "fake"},
                timeout=timeout,
            )
            _print_step(f"captions #{spec['index']}", _extract_state_fields(captions_state))

            asset_state = _request_json(base_url, "POST", f"/internal/videos/{video_id}/asset", timeout=timeout)
            _print_step(f"asset #{spec['index']}", _extract_state_fields(asset_state))

            preview_state = _request_json(
                base_url,
                "POST",
                f"/internal/videos/{video_id}/preview",
                {"visual_template": spec["visual_template"]},
                timeout=timeout,
            )
            _print_step(f"preview #{spec['index']}", _extract_state_fields(preview_state))

            approve_state = _request_json(base_url, "POST", f"/internal/videos/{video_id}/approve-preview", timeout=timeout)
            _print_step(f"approve-preview #{spec['index']}", _extract_state_fields(approve_state))

            final_state = _request_json(base_url, "POST", f"/internal/videos/{video_id}/final", timeout=timeout)
            _print_step(f"final-render #{spec['index']}", _extract_state_fields(final_state))

            export_state = _request_json(base_url, "POST", f"/internal/videos/{video_id}/export-package", timeout=timeout)
            _print_step(f"export-package #{spec['index']}", _extract_state_fields(export_state))

            youtube_state = _request_json(
                base_url,
                "POST",
                f"/internal/videos/{video_id}/youtube-prep",
                {
                    "title": create_state.get("video_title") or spec["title"],
                    "description": f"Auto-generated {content_format} demo item: {spec['topic']}.",
                    "tags": ["shortsfactory", content_format, "batch"],
                    "visibility": "private",
                    "made_for_kids": False,
                },
                timeout=timeout,
            )
            _print_step(f"youtube-prep #{spec['index']}", _extract_state_fields(youtube_state))

            readiness_state = _request_json(base_url, "GET", f"/internal/videos/{video_id}/publish-readiness", timeout=timeout)
            _print_step(
                f"publish-readiness #{spec['index']}",
                f"overall_status={readiness_state.get('overall_status')} ready={readiness_state.get('ready')} missing_items={readiness_state.get('missing_items', [])}",
            )

            final_path = final_state.get("final_path")
            duration_seconds = _measure_duration_seconds(str((REPO_ROOT / "apps" / "api") / Path(str(final_path)))) if final_path else None
            outcome = _build_outcome(
                index=int(spec["index"]),
                spec=spec,
                create_state=youtube_state,
                readiness=readiness_state,
                duration_seconds=duration_seconds,
            )
            if not outcome.quality_ok:
                raise RuntimeError(outcome.error_message or "quality gate failed")
            outcomes.append(outcome)
            print(
                f"[OK] batch-item #{spec['index']} video_id={outcome.video_id} slug={outcome.slug} duration={outcome.duration_seconds:.3f}s readiness={outcome.readiness}"
            )
        except Exception as exc:  # noqa: BLE001 - operator-facing batch runner
            duration_seconds = None
            if create_state.get("final_path"):
                try:
                    duration_seconds = _measure_duration_seconds(str((REPO_ROOT / "apps" / "api") / Path(str(create_state["final_path"]))))
                except Exception:
                    duration_seconds = None
            outcome = _build_outcome(
                index=int(spec["index"]),
                spec=spec,
                create_state=create_state,
                readiness=readiness_state,
                duration_seconds=duration_seconds,
                error_message=str(exc),
            )
            outcomes.append(outcome)
            print(f"[FAIL] batch-item #{spec['index']} {exc}")
    return outcomes


def main() -> int:
    args = _parse_args()
    try:
        _request_json(args.base_url, "GET", "/health", timeout=args.timeout)
        _print_step("health", "status=ok")
        _ = infer_content_format(channel_slug=DEFAULT_CHANNELS[args.format][0], explicit_format=args.format)
        outcomes = _run_batch(args.base_url, timeout=args.timeout, content_format=args.format, count=args.count)
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        report_path = output_dir / f"{args.format}_batch_report.md"
        report_text = _render_report(date.today(), outcomes, content_format=args.format)
        report_path.write_text(report_text, encoding="utf-8")
        print(f"\nReport written to: {report_path}")
        print(f"Generated videos: {len(outcomes)}")
        if len(outcomes) != args.count or any(not item.quality_ok for item in outcomes):
            return 1
        return 0
    except Exception as exc:  # noqa: BLE001 - operator-facing batch runner
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
