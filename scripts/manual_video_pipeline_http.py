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


@dataclass(slots=True)
class HttpResult:
    status: int
    body: dict[str, Any]


def _normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/"


def _request_json(base_url: str, method: str, path: str, payload: dict[str, Any] | None = None) -> HttpResult:
    url = urljoin(_normalize_base_url(base_url), path.lstrip("/"))
    body_bytes = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if body_bytes is not None:
        headers["Content-Type"] = "application/json"

    req = request.Request(url, data=body_bytes, method=method, headers=headers)
    try:
        with request.urlopen(req, timeout=600) as response:
            response_body = response.read().decode("utf-8")
            body = json.loads(response_body) if response_body else {}
            return HttpResult(status=response.status, body=body)
    except error.HTTPError as exc:
        error_body = exc.read().decode("utf-8")
        raise RuntimeError(f"{method} {path} failed with {exc.code}\n{error_body}") from exc


def _print_state(label: str, payload: dict[str, Any]) -> None:
    print(f"{label}:")
    print(f"  video_id={payload.get('video_id')}")
    print(f"  stage_status={payload.get('stage_status')}")
    if payload.get("script_id") is not None:
        print(f"  script_id={payload.get('script_id')}")
    if payload.get("script_status") is not None:
        print(f"  script_status={payload.get('script_status')}")
    for field in ("audio_path", "caption_path", "asset_path", "preview_path", "final_path"):
        value = payload.get(field)
        if value:
            print(f"  {field}={value}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local video pipeline against the FastAPI API.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API base URL, default: http://127.0.0.1:8000")
    parser.add_argument(
        "--mode",
        choices=("fake", "real"),
        default="fake",
        help="Pipeline execution mode, default: fake",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        run_pipeline_with_mode(args.base_url, args.mode)
        return 0
    except Exception as exc:  # noqa: BLE001 - manual operator script
        print(str(exc), file=sys.stderr)
        return 1


def run_pipeline_with_mode(base_url: str, mode: str) -> None:
    health = _request_json(base_url, "GET", "/health")
    if health.body.get("status") != "ok":
        raise RuntimeError(f"Health check failed: {health.body}")
    print("health=ok")

    create_result = _request_json(
        base_url,
        "POST",
        "/internal/videos/test",
        {
            "topic": "Como aprender Python",
            "channel_slug": "manual-test",
            "channel_name": "Manual Test",
            "video_title": "Teste manual",
            "execution_mode": mode,
        },
    )
    create_state = create_result.body
    _print_state("create", create_state)

    video_id = create_state["video_id"]

    tts_state = _request_json(
        base_url,
        "POST",
        f"/internal/videos/{video_id}/tts",
        {"execution_mode": mode},
    ).body
    _print_state("tts", tts_state)

    captions_state = _request_json(
        base_url,
        "POST",
        f"/internal/videos/{video_id}/captions",
        {"execution_mode": mode},
    ).body
    _print_state("captions", captions_state)

    asset_state = _request_json(base_url, "POST", f"/internal/videos/{video_id}/asset").body
    _print_state("asset", asset_state)

    preview_state = _request_json(base_url, "POST", f"/internal/videos/{video_id}/preview").body
    _print_state("preview", preview_state)

    approve_state = _request_json(base_url, "POST", f"/internal/videos/{video_id}/approve-preview").body
    _print_state("approve-preview", approve_state)

    final_state = _request_json(base_url, "POST", f"/internal/videos/{video_id}/final").body
    _print_state("final", final_state)

    status_state = _request_json(base_url, "GET", f"/internal/videos/{video_id}/status").body
    _print_state("status", status_state)


if __name__ == "__main__":
    raise SystemExit(main())
