#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request


DEFAULT_OUTPUT = "apps/api/storage/config/trends/youtube_trends.json"
DEFAULT_REGION_CODE = "BR"
DEFAULT_MAX_RESULTS = 50
DEFAULT_API_BASE = "https://www.googleapis.com/youtube/v3"


@dataclass(slots=True)
class VideoTrendItem:
    video_id: str
    title: str
    published_at: str | None
    age_hours: float | None
    views: int | None
    likes: int | None
    comments: int | None
    views_per_hour: float | None
    engagement_rate: float | None
    is_short_candidate: bool
    url: str
    snippet: dict[str, Any]
    statistics: dict[str, Any]
    content_details: dict[str, Any]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect public YouTube trend references with the Data API.")
    parser.add_argument("--region-code", default=DEFAULT_REGION_CODE, help="Region code for mostPopular, default: BR")
    parser.add_argument("--max-results", type=int, default=DEFAULT_MAX_RESULTS, help="Max videos to collect, default: 50")
    parser.add_argument("--query", default=None, help='Optional search query, e.g. "python shorts"')
    parser.add_argument(
        "--published-after",
        default=None,
        help="Optional RFC 3339 timestamp or date to filter search results, e.g. 2026-01-01T00:00:00Z",
    )
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help=f"Output JSON path, default: {DEFAULT_OUTPUT}")
    return parser.parse_args()


def _require_api_key() -> str:
    api_key = os.getenv("YOUTUBE_DATA_API_KEY")
    if not api_key:
        raise RuntimeError("YOUTUBE_DATA_API_KEY is not configured. Set it before running the collector.")
    return api_key.strip()


def _request_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    query = parse.urlencode({key: value for key, value in params.items() if value is not None}, doseq=True)
    full_url = f"{url}?{query}"
    req = request.Request(full_url, headers={"Accept": "application/json"})
    try:
        with request.urlopen(req, timeout=60) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload) if payload else {}
    except error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Request failed with HTTP {exc.code} for {url}\n{error_body}") from exc
    except error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(f"Failed to reach YouTube Data API at {url}\n{reason}") from exc


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _content_duration_seconds(duration: str | None) -> int | None:
    if not duration:
        return None
    try:
        import re

        pattern = re.compile(
            r"^P"
            r"(?:(?P<days>\d+)D)?"
            r"(?:T"
            r"(?:(?P<hours>\d+)H)?"
            r"(?:(?P<minutes>\d+)M)?"
            r"(?:(?P<seconds>\d+)S)?"
            r")?$"
        )
        match = pattern.match(duration)
        if not match:
            return None
        days = int(match.group("days") or 0)
        hours = int(match.group("hours") or 0)
        minutes = int(match.group("minutes") or 0)
        seconds = int(match.group("seconds") or 0)
        return days * 86_400 + hours * 3_600 + minutes * 60 + seconds
    except Exception:
        return None


def _is_short_candidate(title: str | None, description: str | None, duration_seconds: int | None) -> bool:
    text = f"{title or ''} {description or ''}".lower()
    if "#shorts" in text:
        return True
    return bool(duration_seconds is not None and duration_seconds <= 60)


def _views_per_hour(views: int | None, published_at: str | None) -> float | None:
    if views is None:
        return None
    published = _parse_iso_datetime(published_at)
    if published is None:
        return None
    age_hours = (datetime.now(timezone.utc) - published).total_seconds() / 3_600
    if age_hours <= 0:
        return float(views)
    return views / age_hours


def _engagement_rate(views: int | None, likes: int | None, comments: int | None) -> float | None:
    if views is None or views <= 0:
        return None
    total = (likes or 0) + (comments or 0)
    return total / views


def _build_video_item(video: dict[str, Any]) -> VideoTrendItem:
    snippet = video.get("snippet") if isinstance(video.get("snippet"), dict) else {}
    statistics = video.get("statistics") if isinstance(video.get("statistics"), dict) else {}
    content_details = video.get("contentDetails") if isinstance(video.get("contentDetails"), dict) else {}
    title = str(snippet.get("title") or "").strip()
    description = str(snippet.get("description") or "").strip()
    published_at = snippet.get("publishedAt")
    duration_seconds = _content_duration_seconds(content_details.get("duration"))
    views = int(statistics["viewCount"]) if statistics.get("viewCount") is not None else None
    likes = int(statistics["likeCount"]) if statistics.get("likeCount") is not None else None
    comments = int(statistics["commentCount"]) if statistics.get("commentCount") is not None else None
    age_hours = None
    published_dt = _parse_iso_datetime(published_at)
    if published_dt is not None:
        age_hours = max((datetime.now(timezone.utc) - published_dt).total_seconds() / 3_600, 0.0)
    return VideoTrendItem(
        video_id=str(video.get("id") or ""),
        title=title,
        published_at=published_at,
        age_hours=age_hours,
        views=views,
        likes=likes,
        comments=comments,
        views_per_hour=_views_per_hour(views, published_at),
        engagement_rate=_engagement_rate(views, likes, comments),
        is_short_candidate=_is_short_candidate(title, description, duration_seconds),
        url=f"https://www.youtube.com/watch?v={video.get('id')}",
        snippet=snippet,
        statistics=statistics,
        content_details=content_details,
    )


def _batch(items: list[str], size: int = 50) -> list[list[str]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _collect_most_popular(*, api_key: str, region_code: str, max_results: int) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    page_token: str | None = None
    while len(collected) < max_results:
        params = {
            "part": "snippet,statistics,contentDetails",
            "chart": "mostPopular",
            "regionCode": region_code,
            "maxResults": min(50, max_results - len(collected)),
            "key": api_key,
            "pageToken": page_token,
        }
        payload = _request_json(f"{DEFAULT_API_BASE}/videos", params)
        collected.extend(payload.get("items", []))
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
    return collected[:max_results]


def _search_video_ids(
    *,
    api_key: str,
    query: str,
    region_code: str,
    max_results: int,
    published_after: str | None,
) -> list[str]:
    video_ids: list[str] = []
    page_token: str | None = None
    while len(video_ids) < max_results:
        params = {
            "part": "snippet",
            "type": "video",
            "q": query,
            "regionCode": region_code,
            "maxResults": min(50, max_results - len(video_ids)),
            "order": "viewCount",
            "publishedAfter": published_after,
            "key": api_key,
            "pageToken": page_token,
        }
        payload = _request_json(f"{DEFAULT_API_BASE}/search", params)
        for item in payload.get("items", []):
            video_id = item.get("id", {}).get("videoId")
            if isinstance(video_id, str) and video_id:
                video_ids.append(video_id)
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
    return video_ids[:max_results]


def _fetch_video_details(*, api_key: str, video_ids: list[str]) -> list[dict[str, Any]]:
    videos: list[dict[str, Any]] = []
    for chunk in _batch(video_ids, 50):
        params = {
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(chunk),
            "maxResults": len(chunk),
            "key": api_key,
        }
        payload = _request_json(f"{DEFAULT_API_BASE}/videos", params)
        videos.extend(payload.get("items", []))
    return videos


def _build_output_payload(
    *,
    source: str,
    params: dict[str, Any],
    items: list[VideoTrendItem],
) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "params": params,
        "count": len(items),
        "items": [
            {
                "video_id": item.video_id,
                "title": item.title,
                "published_at": item.published_at,
                "age_hours": item.age_hours,
                "views": item.views,
                "likes": item.likes,
                "comments": item.comments,
                "views_per_hour": item.views_per_hour,
                "engagement_rate": item.engagement_rate,
                "is_short_candidate": item.is_short_candidate,
                "url": item.url,
                "snippet": item.snippet,
                "statistics": item.statistics,
                "contentDetails": item.content_details,
            }
            for item in items
        ],
    }


def _write_output(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def main() -> int:
    args = _parse_args()
    try:
        api_key = _require_api_key()
        params = {
            "region_code": args.region_code,
            "max_results": args.max_results,
            "query": args.query,
            "published_after": args.published_after,
            "output": args.output,
        }

        if args.query:
            search_ids = _search_video_ids(
                api_key=api_key,
                query=args.query,
                region_code=args.region_code,
                max_results=args.max_results,
                published_after=args.published_after,
            )
            raw_videos = _fetch_video_details(api_key=api_key, video_ids=search_ids)
            source = "search.list + videos.list"
        else:
            raw_videos = _collect_most_popular(
                api_key=api_key,
                region_code=args.region_code,
                max_results=args.max_results,
            )
            source = "videos.list chart=mostPopular"

        trend_items = [_build_video_item(video) for video in raw_videos]
        trend_items.sort(
            key=lambda item: (
                item.views_per_hour is None,
                -(item.views_per_hour or 0.0),
                -(item.views or 0),
            )
        )

        output_path = Path(args.output)
        payload = _build_output_payload(source=source, params=params, items=trend_items)
        _write_output(output_path, payload)

        print(f"saved={output_path}")
        print(f"count={len(trend_items)}")
        print(f"source={source}")
        for item in trend_items[:10]:
            print(
                f"- {item.video_id} | views_per_hour={item.views_per_hour} | "
                f"engagement_rate={item.engagement_rate} | short={item.is_short_candidate} | {item.title}"
            )
        return 0
    except Exception as exc:  # noqa: BLE001 - operator-facing collector
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
