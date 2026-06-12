#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any
from urllib import error, request
from urllib.parse import urljoin


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT = 600.0
DEFAULT_TOPIC = "Como aprender Python mais rapido"
DEFAULT_CHANNEL_SLUG = "manual-test"
DEFAULT_CHANNEL_NAME = "Manual Test"


@dataclass(slots=True)
class HttpResult:
    status: int
    body: dict[str, Any]


@dataclass(slots=True)
class StepResult:
    name: str
    ok: bool
    detail: str


def _normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/"


def _request_json(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float,
) -> HttpResult:
    url = urljoin(_normalize_base_url(base_url), path.lstrip("/"))
    body_bytes = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if body_bytes is not None:
        headers["Content-Type"] = "application/json"

    req = request.Request(url, data=body_bytes, method=method, headers=headers)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            response_body = response.read().decode("utf-8")
            body = json.loads(response_body) if response_body else {}
            return HttpResult(status=response.status, body=body)
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


def _print_step(result: StepResult) -> None:
    status = "OK" if result.ok else "FAIL"
    print(f"[{status}] {result.name}")
    if result.detail:
        print(f"  {result.detail}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the full local ShortsFactory smoke demo over HTTP.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API base URL, default: http://127.0.0.1:8000")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="HTTP timeout in seconds for each request, default: 600",
    )
    parser.add_argument(
        "--skip-reset",
        action="store_true",
        help="Skip POST /internal/videos/demo/reset before running the smoke.",
    )
    return parser.parse_args()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


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


def run_smoke_demo(*, base_url: str, timeout: float, skip_reset: bool) -> list[StepResult]:
    steps: list[StepResult] = []

    if not skip_reset:
        reset_result = _request_json(
            base_url,
            "POST",
            "/internal/videos/demo/reset",
            {"confirm": True},
            timeout=timeout,
        )
        detail = f"deleted_videos={reset_result.body.get('deleted_videos', 0)} deleted_scripts={reset_result.body.get('deleted_scripts', 0)}"
        step = StepResult("demo-reset", True, detail)
        steps.append(step)
        _print_step(step)
    else:
        step = StepResult("demo-reset", True, "skipped by --skip-reset")
        steps.append(step)
        _print_step(step)

    health = _request_json(base_url, "GET", "/health", timeout=timeout)
    _require(health.body.get("status") == "ok", f"Health check failed: {health.body}")
    step = StepResult("health", True, f"status={health.body.get('status')}")
    steps.append(step)
    _print_step(step)

    create_result = _request_json(
        base_url,
        "POST",
        "/internal/videos/test",
        {
            "topic": DEFAULT_TOPIC,
            "channel_slug": DEFAULT_CHANNEL_SLUG,
            "channel_name": DEFAULT_CHANNEL_NAME,
            "video_title": "Smoke Demo Local",
            "execution_mode": "fake",
        },
        timeout=timeout,
    )
    state = create_result.body
    _require("video_id" in state, f"Create video response missing video_id: {state}")
    step = StepResult("create-video", True, _extract_state_fields(state))
    steps.append(step)
    _print_step(step)

    script_status = str(state.get("script_status") or "").lower()
    script_id = state.get("script_id")
    if not script_id or script_status != "approved":
        patch_result = _request_json(
            base_url,
            "PATCH",
            f"/internal/videos/{state['video_id']}/script",
            _build_script_patch_payload(state),
            timeout=timeout,
        )
        state = patch_result.body
    _require(state.get("script_id") is not None, "Script confirmation failed: script_id is missing.")
    _require(str(state.get("script_status") or "").lower() == "approved", "Script confirmation failed: script is not approved.")
    step = StepResult("script-confirm", True, _extract_state_fields(state))
    steps.append(step)
    _print_step(step)

    video_id = int(state["video_id"])

    tts_result = _request_json(
        base_url,
        "POST",
        f"/internal/videos/{video_id}/tts",
        {"execution_mode": "fake"},
        timeout=timeout,
    )
    state = tts_result.body
    _require(state.get("audio_path"), "TTS did not return an audio_path.")
    step = StepResult("tts", True, _extract_state_fields(state))
    steps.append(step)
    _print_step(step)

    captions_result = _request_json(
        base_url,
        "POST",
        f"/internal/videos/{video_id}/captions",
        {"execution_mode": "fake"},
        timeout=timeout,
    )
    state = captions_result.body
    _require(state.get("caption_path"), "Captions did not return a caption_path.")
    step = StepResult("captions", True, _extract_state_fields(state))
    steps.append(step)
    _print_step(step)

    asset_result = _request_json(base_url, "POST", f"/internal/videos/{video_id}/asset", timeout=timeout)
    state = asset_result.body
    _require(state.get("asset_path"), "Asset selection did not return an asset_path.")
    step = StepResult("asset", True, _extract_state_fields(state))
    steps.append(step)
    _print_step(step)

    preview_payload = {"visual_template": state.get("visual_template") or "default"}
    preview_result = _request_json(
        base_url,
        "POST",
        f"/internal/videos/{video_id}/preview",
        preview_payload,
        timeout=timeout,
    )
    state = preview_result.body
    _require(state.get("preview_path"), "Preview render did not return a preview_path.")
    step = StepResult("preview", True, _extract_state_fields(state))
    steps.append(step)
    _print_step(step)

    approve_result = _request_json(
        base_url,
        "POST",
        f"/internal/videos/{video_id}/approve-preview",
        timeout=timeout,
    )
    state = approve_result.body
    _require(str(state.get("stage_status") or "").lower() in {"preview_approved", "final_rendered"}, "Preview approval did not advance the stage.")
    step = StepResult("approve-preview", True, _extract_state_fields(state))
    steps.append(step)
    _print_step(step)

    final_result = _request_json(base_url, "POST", f"/internal/videos/{video_id}/final", timeout=timeout)
    state = final_result.body
    _require(state.get("final_path"), "Final render did not return a final_path.")
    step = StepResult("final-render", True, _extract_state_fields(state))
    steps.append(step)
    _print_step(step)

    export_result = _request_json(base_url, "POST", f"/internal/videos/{video_id}/export-package", timeout=timeout)
    state = export_result.body
    _require(state.get("export_package_dir"), "Export package did not return export_package_dir.")
    step = StepResult("export-package", True, _extract_state_fields(state))
    steps.append(step)
    _print_step(step)

    youtube_prep_result = _request_json(
        base_url,
        "POST",
        f"/internal/videos/{video_id}/youtube-prep",
        {
            "title": state.get("video_title") or "Smoke Demo Local",
            "description": "Smoke demo local gerado via API interna.",
            "tags": ["shortsfactory", "smoke", "local"],
            "visibility": "private",
            "made_for_kids": False,
        },
        timeout=timeout,
    )
    state = youtube_prep_result.body
    _require(state.get("youtube_publish_path"), "YouTube prep did not return youtube_publish_path.")
    step = StepResult("youtube-prep", True, _extract_state_fields(state))
    steps.append(step)
    _print_step(step)

    readiness_result = _request_json(
        base_url,
        "GET",
        f"/internal/videos/{video_id}/publish-readiness",
        timeout=timeout,
    )
    readiness = readiness_result.body
    readiness_detail = (
        f"overall_status={readiness.get('overall_status')} ready={readiness.get('ready')} "
        f"missing_items={readiness.get('missing_items', [])}"
    )
    step = StepResult("publish-readiness", True, readiness_detail)
    steps.append(step)
    _print_step(step)

    auth_result = _request_json(base_url, "GET", "/internal/videos/youtube/auth-status", timeout=timeout)
    auth = auth_result.body
    auth_detail = (
        f"enabled={auth.get('enabled')} client_secrets_configured={auth.get('client_secrets_configured')} "
        f"token_configured={auth.get('token_configured')} ready_for_upload={auth.get('ready_for_upload')} "
        f"warnings={auth.get('warnings', [])}"
    )
    step = StepResult("youtube-auth-status", True, auth_detail)
    steps.append(step)
    _print_step(step)

    upload_result = _request_json(base_url, "POST", f"/internal/videos/{video_id}/youtube/upload", timeout=timeout)
    upload = upload_result.body
    upload_status = str(upload.get("upload_status") or "").strip()
    _require(upload_status in {"blocked", "ready_but_disabled", "simulated"}, f"Unexpected upload status: {upload}")
    upload_detail = (
        f"upload_status={upload_status} youtube_video_id={upload.get('youtube_video_id')} "
        f"message={upload.get('message')} checked_at={upload.get('checked_at')}"
    )
    step = StepResult("youtube-upload-stub", True, upload_detail)
    steps.append(step)
    _print_step(step)

    safe_ok = upload_status in {"blocked", "ready_but_disabled", "simulated"} and upload.get("youtube_video_id") is None
    safe_detail = f"safe={safe_ok} upload_status={upload_status}"
    if not safe_ok:
        raise RuntimeError(f"YouTube upload stub returned an unsafe payload: {upload}")
    step = StepResult("upload-safe-check", True, safe_detail)
    steps.append(step)
    _print_step(step)

    return steps


def main() -> int:
    args = _parse_args()
    try:
        steps = run_smoke_demo(base_url=args.base_url, timeout=args.timeout, skip_reset=args.skip_reset)
    except Exception as exc:  # noqa: BLE001 - operator-facing smoke script
        print(str(exc), file=sys.stderr)
        return 1

    print("\nResumo final:")
    for step in steps:
        _print_step(step)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
