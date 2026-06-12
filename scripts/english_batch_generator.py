#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any
from urllib import error, request
from urllib.parse import urljoin

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.english_batch_generator import (  # noqa: E402
    DEFAULT_CHANNEL_NAME,
    DEFAULT_CHANNEL_SLUG,
    DEFAULT_TARGET_DURATION_SECONDS,
    DEFAULT_VIDEO_COUNT,
    DEFAULT_VISUAL_TEMPLATE,
    BatchVideoOutcome,
    BatchVideoSpec,
    build_batch_specs,
    render_batch_report,
)


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT = 600.0
DEFAULT_OUTPUT = REPO_ROOT / "apps" / "api" / "storage" / "review" / date.today().isoformat() / "batch_report.md"


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
        raise RuntimeError(
            f"API not reachable at {base_url}. Start the FastAPI app first.\n{reason}"
        ) from exc


def _extract_state_fields(payload: dict[str, Any]) -> str:
    fields = [
        "video_id",
        "stage_status",
        "script_id",
        "script_status",
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


def _print_step(name: str, detail: str) -> None:
    print(f"[OK] {name}")
    if detail:
        print(f"  {detail}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a batch of English fake Shorts for review.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API base URL, default: http://127.0.0.1:8000")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="HTTP timeout in seconds for each request, default: 600",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=DEFAULT_VIDEO_COUNT,
        help="Number of videos to generate, default: 5",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="Batch report output path, default: apps/api/storage/review/YYYY-MM-DD/batch_report.md",
    )
    parser.add_argument(
        "--skip-preset",
        action="store_true",
        help="Skip upserting the english-dev-shorts channel preset before generation.",
    )
    return parser.parse_args()


def _ensure_channel_preset(base_url: str, *, timeout: float, skip_preset: bool) -> None:
    if skip_preset:
        _print_step("channel-preset", "skipped by --skip-preset")
        return
    payload = {
        "channel_slug": DEFAULT_CHANNEL_SLUG,
        "channel_name": DEFAULT_CHANNEL_NAME,
        "default_topic_style": "viral_micro_short",
        "default_visual_template": DEFAULT_VISUAL_TEMPLATE,
        "default_asset_slug": None,
        "default_cta": "",
        "target_duration_seconds": DEFAULT_TARGET_DURATION_SECONDS,
    }
    result = _request_json(base_url, "POST", "/internal/videos/channel-presets", payload, timeout=timeout)
    detail = (
        f"channel_slug={result.get('channel_slug')} default_visual_template={result.get('default_visual_template')} "
        f"target_duration_seconds={result.get('target_duration_seconds')}"
    )
    _print_step("channel-preset", detail)


def _build_script_patch_payload(state: dict[str, Any]) -> dict[str, Any]:
    script_text = state.get("script_text")
    if not script_text:
        raise RuntimeError("The created video did not return a script_text payload.")
    return {
        "script_text": script_text,
        "hook": state.get("hook"),
        "body_blocks": state.get("body_blocks"),
        "call_to_action": state.get("call_to_action"),
        "estimated_duration_seconds": state.get("estimated_duration_seconds"),
        "style_tone": state.get("style_tone"),
    }


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


def _build_outcome(
    *,
    index: int,
    spec: BatchVideoSpec,
    state: dict[str, Any],
    readiness: dict[str, Any],
    duration_seconds: float | None,
    error_message: str | None = None,
) -> BatchVideoOutcome:
    final_path = state.get("final_path")
    caption_path = state.get("caption_path")
    export_path = state.get("export_package_dir")
    visual_template = state.get("visual_template") or spec.visual_template
    quality_ok = (
        error_message is None
        and bool(final_path)
        and bool(caption_path)
        and bool(export_path)
        and visual_template == "viral_reels"
        and duration_seconds is not None
        and 8 <= duration_seconds <= 12
        and readiness.get("overall_status") == "ready"
        and readiness.get("ready") is True
    )
    return BatchVideoOutcome(
        index=index,
        topic=spec.topic,
        title=state.get("video_title") or spec.title,
        channel_slug=spec.channel_slug,
        video_id=state.get("video_id"),
        slug=state.get("video_slug"),
        final_path=final_path,
        caption_path=caption_path,
        export_path=export_path,
        duration_seconds=duration_seconds,
        readiness=str(readiness.get("overall_status") or "unknown"),
        visual_template=str(visual_template),
        stage_status=state.get("stage_status"),
        quality_ok=quality_ok,
        error_message=error_message,
    )


def _run_video_batch(base_url: str, *, timeout: float, count: int) -> list[BatchVideoOutcome]:
    outcomes: list[BatchVideoOutcome] = []
    specs = build_batch_specs(count, channel_slug=DEFAULT_CHANNEL_SLUG, channel_name=DEFAULT_CHANNEL_NAME)

    for spec in specs:
        create_state: dict[str, Any] = {}
        readiness_body: dict[str, Any] = {}
        try:
            create_state = _request_json(
                base_url,
                "POST",
                "/internal/videos/test",
                {
                    "topic": spec.topic,
                    "channel_slug": spec.channel_slug,
                    "channel_name": spec.channel_name,
                    "video_title": spec.title,
                    "execution_mode": spec.execution_mode,
                    "style_tone": spec.script_mode,
                    "target_duration_seconds": spec.target_duration_seconds,
                },
                timeout=timeout,
            )
            if str(create_state.get("script_status") or "").lower() != "approved":
                create_state = _request_json(
                    base_url,
                    "PATCH",
                    f"/internal/videos/{create_state['video_id']}/script",
                    _build_script_patch_payload(create_state),
                    timeout=timeout,
                )

            video_id = int(create_state["video_id"])
            _print_step(f"create-video #{spec.index}", _extract_state_fields(create_state))

            tts_state = _request_json(
                base_url,
                "POST",
                f"/internal/videos/{video_id}/tts",
                {"execution_mode": spec.execution_mode},
                timeout=timeout,
            )
            _print_step(f"tts #{spec.index}", _extract_state_fields(tts_state))

            captions_state = _request_json(
                base_url,
                "POST",
                f"/internal/videos/{video_id}/captions",
                {"execution_mode": spec.execution_mode},
                timeout=timeout,
            )
            _print_step(f"captions #{spec.index}", _extract_state_fields(captions_state))

            asset_state = _request_json(base_url, "POST", f"/internal/videos/{video_id}/asset", timeout=timeout)
            _print_step(f"asset #{spec.index}", _extract_state_fields(asset_state))

            preview_state = _request_json(
                base_url,
                "POST",
                f"/internal/videos/{video_id}/preview",
                {"visual_template": spec.visual_template},
                timeout=timeout,
            )
            _print_step(f"preview #{spec.index}", _extract_state_fields(preview_state))

            approve_state = _request_json(
                base_url,
                "POST",
                f"/internal/videos/{video_id}/approve-preview",
                timeout=timeout,
            )
            _print_step(f"approve-preview #{spec.index}", _extract_state_fields(approve_state))

            final_state = _request_json(base_url, "POST", f"/internal/videos/{video_id}/final", timeout=timeout)
            _print_step(f"final-render #{spec.index}", _extract_state_fields(final_state))

            export_state = _request_json(
                base_url,
                "POST",
                f"/internal/videos/{video_id}/export-package",
                timeout=timeout,
            )
            _print_step(f"export-package #{spec.index}", _extract_state_fields(export_state))

            youtube_state = _request_json(
                base_url,
                "POST",
                f"/internal/videos/{video_id}/youtube-prep",
                {
                    "title": create_state.get("video_title") or spec.title,
                    "description": f"Auto-generated English Shorts batch item: {spec.topic}.",
                    "tags": ["shortsfactory", "english", "batch", "coding"],
                    "visibility": "private",
                    "made_for_kids": False,
                },
                timeout=timeout,
            )
            _print_step(f"youtube-prep #{spec.index}", _extract_state_fields(youtube_state))

            readiness = _request_json(
                base_url,
                "GET",
                f"/internal/videos/{video_id}/publish-readiness",
                timeout=timeout,
            )
            readiness_body = readiness
            _print_step(
                f"publish-readiness #{spec.index}",
                f"overall_status={readiness_body.get('overall_status')} ready={readiness_body.get('ready')} missing_items={readiness_body.get('missing_items', [])}",
            )

            final_path = final_state.get("final_path")
            duration_seconds = _measure_duration_seconds(str((REPO_ROOT / "apps" / "api") / Path(str(final_path)))) if final_path else None
            outcome = _build_outcome(
                index=spec.index,
                spec=spec,
                state=youtube_state,
                readiness=readiness_body,
                duration_seconds=duration_seconds,
            )
            if not outcome.quality_ok:
                reason = outcome.error_message or "quality gate failed"
                raise RuntimeError(f"Quality gate failed for #{spec.index} {spec.topic}: {reason}")
            outcomes.append(outcome)
            print(
                f"[OK] batch-item #{spec.index} video_id={outcome.video_id} slug={outcome.slug} duration={outcome.duration_seconds:.3f}s readiness={outcome.readiness}"
            )
        except Exception as exc:  # noqa: BLE001 - operator-facing batch runner
            duration_seconds = None
            if create_state.get("final_path"):
                try:
                    duration_seconds = _measure_duration_seconds(str((REPO_ROOT / "apps" / "api") / Path(str(create_state["final_path"]))))
                except Exception:
                    duration_seconds = None
            outcome = _build_outcome(
                index=spec.index,
                spec=spec,
                state=create_state,
                readiness=readiness_body,
                duration_seconds=duration_seconds,
                error_message=str(exc),
            )
            outcomes.append(outcome)
            print(f"[FAIL] batch-item #{spec.index} {exc}")

    return outcomes


def main() -> int:
    args = _parse_args()
    try:
        _request_json(args.base_url, "GET", "/health", timeout=args.timeout)
        _print_step("health", "status=ok")
        _ensure_channel_preset(args.base_url, timeout=args.timeout, skip_preset=args.skip_preset)
        outcomes = _run_video_batch(args.base_url, timeout=args.timeout, count=args.count)
        report_path = Path(args.output)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_text = render_batch_report(date.today(), outcomes)
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
