#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_API_BASE = "https://www.googleapis.com/youtube/v3"
DEFAULT_REGION_CODE = "US"
DEFAULT_MAX_RESULTS = 50
DEFAULT_OUTPUT_DIR = REPO_ROOT / "apps" / "api" / "storage" / "config" / "trends" / "youtube_template_patterns" / date.today().isoformat()
DEFAULT_QUERIES = [
    "football quiz shorts",
    "guess the player shorts",
    "football would you rather shorts",
    "football this or that shorts",
    "football quiz challenge shorts",
]
_ENV_FILES = [
    REPO_ROOT / ".env",
    REPO_ROOT / ".env.local",
    REPO_ROOT / "apps" / "api" / ".env",
    REPO_ROOT / "apps" / "api" / ".env.local",
]

_FORMAT_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("guess_the_player", ("guess the player", "guess this player", "who is this player", "name the player", "player quiz")),
    ("guess_the_club", ("guess the club", "which club", "club quiz", "who did he play for", "played for this club")),
    ("player_vs_player", (" vs ", "versus", "player vs player", "prime ", "better than", "comparison")),
    ("would_you_rather", ("would you rather", "pick one", "choose one", "rather play", "rather have")),
    ("this_or_that", ("this or that", "this / that", "this-or-that", "choose this or that")),
    ("ranking", ("top 10", "top 5", "ranking", "rank these", "best footballers", "worst footballers")),
    ("impossible_quiz", ("impossible quiz", "hardest quiz", "99% fail", "can you answer", "impossible football quiz")),
    ("only_real_fans", ("only real fans", "real fans know", "if you know football", "only true fans", "true fans")),
]

_HOOK_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("identity_guess", ("guess the player", "name the player", "who is this player", "who am i", "identify")),
    ("challenge", ("guess", "quiz", "challenge", "can you", "solve", "name the", "who is this")),
    ("curiosity", ("did you know", "watch this", "one clue", "secret", "hidden", "this player")),
    ("debate", (" vs ", "versus", "better", "who wins", "which is better", "debate")),
    ("speed_test", ("in 5 seconds", "speed quiz", "quick quiz", "fast", "timed", "countdown")),
    ("ranking_reveal", ("top", "ranking", "rank", "reveal", "best", "worst")),
]

_STRUCTURES: dict[str, list[str]] = {
    "guess_the_player": ["hook", "clue_1", "clue_2", "clue_3", "countdown", "answer_reveal"],
    "guess_the_club": ["hook", "clue_1", "clue_2", "clue_3", "countdown", "answer_reveal"],
    "player_vs_player": ["hook", "option_a", "option_b", "comparison_prompt", "comment_prompt"],
    "would_you_rather": ["hook", "option_a", "option_b", "choice_prompt", "comment_prompt"],
    "this_or_that": ["hook", "option_a", "option_b", "choice_prompt", "comment_prompt"],
    "ranking": ["hook", "rank_3", "rank_2", "rank_1", "ranking_reveal"],
    "impossible_quiz": ["hook", "clue_1", "clue_2", "clue_3", "answer_reveal"],
    "only_real_fans": ["hook", "question_1", "question_2", "question_3", "answer_reveal"],
}


@dataclass(slots=True)
class TemplatePatternItem:
    video_id: str
    title: str
    channel_title: str | None
    published_at: str | None
    duration: str | None
    duration_seconds: int | None
    view_count: int | None
    like_count: int | None
    comment_count: int | None
    thumbnail_url: str | None
    views_per_hour: float | None
    engagement_rate: float | None
    is_short_candidate: bool
    inferred_format: str
    inferred_hook_type: str
    inferred_structure: list[str]
    hook_signature: str
    snippet: dict[str, Any]
    statistics: dict[str, Any]
    content_details: dict[str, Any]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect YouTube template patterns using metadata only.")
    parser.add_argument("--region-code", default=DEFAULT_REGION_CODE, help="Region code for search and popularity lookups.")
    parser.add_argument("--max-results", type=int, default=DEFAULT_MAX_RESULTS, help="Max videos to keep after sorting.")
    parser.add_argument(
        "--query",
        action="append",
        default=None,
        help="Optional search query. Repeat to use multiple queries. Defaults to football quiz pattern queries.",
    )
    parser.add_argument(
        "--published-after",
        default=None,
        help="Optional RFC 3339 timestamp or ISO date for search.list filtering.",
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for JSON and markdown outputs.")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE, help="YouTube Data API base URL.")
    return parser.parse_args()


def _load_env_file(path: Path) -> None:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if value and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ[key] = value


def _load_env_files() -> None:
    for env_path in _ENV_FILES:
        _load_env_file(env_path)


def _require_api_key() -> str:
    _load_env_files()
    for key_name in ("YOUTUBE_DATA_API_KEY", "YOUTUBE_API_KEY", "GOOGLE_YOUTUBE_API_KEY"):
        api_key = os.getenv(key_name)
        if api_key and api_key.strip():
            return api_key.strip()
    raise RuntimeError(
        "YOUTUBE_DATA_API_KEY is not configured. Add it to .env, apps/api/.env, or export it in your shell. "
        "Supported aliases: YOUTUBE_API_KEY, GOOGLE_YOUTUBE_API_KEY."
    )


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


def parse_duration_seconds(duration: str | None) -> int | None:
    if not duration:
        return None
    match = re.match(
        r"^P"
        r"(?:(?P<days>\d+)D)?"
        r"(?:T"
        r"(?:(?P<hours>\d+)H)?"
        r"(?:(?P<minutes>\d+)M)?"
        r"(?:(?P<seconds>\d+)S)?"
        r")?$",
        duration.strip(),
    )
    if not match:
        return None
    days = int(match.group("days") or 0)
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)
    return days * 86_400 + hours * 3_600 + minutes * 60 + seconds


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


def _keyword_score(text: str, keywords: tuple[str, ...]) -> int:
    lower = text.lower()
    return sum(1 for keyword in keywords if keyword in lower)


def infer_content_format(title: str | None, description: str | None) -> str:
    text = f"{title or ''} {description or ''}"
    best_format = "ranking"
    best_score = -1
    for format_name, keywords in _FORMAT_KEYWORDS:
        score = _keyword_score(text, keywords)
        if score > best_score:
            best_format = format_name
            best_score = score
    if best_score <= 0:
        return "ranking" if "football" in text.lower() else "guess_the_player"
    return best_format


def infer_hook_type(title: str | None, description: str | None, inferred_format: str | None = None) -> str:
    text = f"{title or ''} {description or ''}"
    if inferred_format in {"would_you_rather", "this_or_that", "player_vs_player"}:
        return "debate"
    best_hook = "challenge"
    best_score = -1
    for hook_name, keywords in _HOOK_KEYWORDS:
        score = _keyword_score(text, keywords)
        if score > best_score:
            best_hook = hook_name
            best_score = score
    if best_score <= 0 and inferred_format in {"ranking", "impossible_quiz"}:
        return "ranking_reveal"
    return best_hook


def infer_structure(inferred_format: str) -> list[str]:
    return list(_STRUCTURES.get(inferred_format, ["hook", "clue_1", "clue_2", "answer_reveal"]))


def _hook_signature(title: str | None) -> str:
    text = " ".join((title or "").split())
    if not text:
        return "unknown-hook"
    for separator in (":", " - ", " | "):
        if separator in text:
            candidate = text.split(separator, 1)[0].strip()
            if candidate:
                return candidate.lower()
    words = text.split()
    return " ".join(words[:6]).lower()


def _short_candidate(title: str | None, description: str | None, duration_seconds: int | None) -> bool:
    text = f"{title or ''} {description or ''}".lower()
    if "#shorts" in text:
        return True
    return bool(duration_seconds is not None and duration_seconds <= 60)


def _thumbnail_url(snippet: dict[str, Any]) -> str | None:
    thumbnails = snippet.get("thumbnails") if isinstance(snippet.get("thumbnails"), dict) else {}
    for key in ("maxres", "standard", "high", "medium", "default"):
        candidate = thumbnails.get(key) if isinstance(thumbnails, dict) else None
        if isinstance(candidate, dict):
            url = candidate.get("url")
            if isinstance(url, str) and url.strip():
                return url.strip()
    return None


def _build_video_item(video: dict[str, Any]) -> TemplatePatternItem:
    snippet = video.get("snippet") if isinstance(video.get("snippet"), dict) else {}
    statistics = video.get("statistics") if isinstance(video.get("statistics"), dict) else {}
    content_details = video.get("contentDetails") if isinstance(video.get("contentDetails"), dict) else {}
    title = str(snippet.get("title") or "").strip()
    description = str(snippet.get("description") or "").strip()
    published_at = snippet.get("publishedAt")
    duration = str(content_details.get("duration") or "").strip() or None
    duration_seconds = parse_duration_seconds(duration)
    views = int(statistics["viewCount"]) if statistics.get("viewCount") is not None else None
    likes = int(statistics["likeCount"]) if statistics.get("likeCount") is not None else None
    comments = int(statistics["commentCount"]) if statistics.get("commentCount") is not None else None
    inferred_format = infer_content_format(title, description)
    return TemplatePatternItem(
        video_id=str(video.get("id") or ""),
        title=title,
        channel_title=str(snippet.get("channelTitle") or "").strip() or None,
        published_at=published_at,
        duration=duration,
        duration_seconds=duration_seconds,
        view_count=views,
        like_count=likes,
        comment_count=comments,
        thumbnail_url=_thumbnail_url(snippet),
        views_per_hour=_views_per_hour(views, published_at),
        engagement_rate=_engagement_rate(views, likes, comments),
        is_short_candidate=_short_candidate(title, description, duration_seconds),
        inferred_format=inferred_format,
        inferred_hook_type=infer_hook_type(title, description, inferred_format=inferred_format),
        inferred_structure=infer_structure(inferred_format),
        hook_signature=_hook_signature(title),
        snippet=snippet,
        statistics=statistics,
        content_details=content_details,
    )


def _batch(items: list[str], size: int = 50) -> list[list[str]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _collect_most_popular(*, api_key: str, api_base: str, region_code: str, max_results: int) -> list[dict[str, Any]]:
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
        payload = _request_json(f"{api_base}/videos", params)
        collected.extend(payload.get("items", []))
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
    return collected[:max_results]


def _search_video_ids(
    *,
    api_key: str,
    api_base: str,
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
        payload = _request_json(f"{api_base}/search", params)
        for item in payload.get("items", []):
            video_id = item.get("id", {}).get("videoId")
            if isinstance(video_id, str) and video_id:
                video_ids.append(video_id)
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
    return video_ids[:max_results]


def _fetch_video_details(*, api_key: str, api_base: str, video_ids: list[str]) -> list[dict[str, Any]]:
    videos: list[dict[str, Any]] = []
    for chunk in _batch(video_ids, 50):
        params = {
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(chunk),
            "maxResults": len(chunk),
            "key": api_key,
        }
        payload = _request_json(f"{api_base}/videos", params)
        videos.extend(payload.get("items", []))
    return videos


def _dedupe_videos(videos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for video in videos:
        video_id = str(video.get("id") or "").strip()
        if not video_id or video_id in unique:
            continue
        unique[video_id] = video
    return list(unique.values())


def _collect_query_videos(
    *,
    api_key: str,
    api_base: str,
    queries: list[str],
    region_code: str,
    max_results: int,
    published_after: str | None,
) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for query in queries:
        search_ids = _search_video_ids(
            api_key=api_key,
            api_base=api_base,
            query=query,
            region_code=region_code,
            max_results=max_results,
            published_after=published_after,
        )
        collected.extend(_fetch_video_details(api_key=api_key, api_base=api_base, video_ids=search_ids))
    return _dedupe_videos(collected)


def _serialize_item(item: TemplatePatternItem) -> dict[str, Any]:
    return {
        "video_id": item.video_id,
        "title": item.title,
        "channel_title": item.channel_title,
        "published_at": item.published_at,
        "duration": item.duration,
        "duration_seconds": item.duration_seconds,
        "view_count": item.view_count,
        "like_count": item.like_count,
        "comment_count": item.comment_count,
        "thumbnail_url": item.thumbnail_url,
        "views_per_hour": item.views_per_hour,
        "engagement_rate": item.engagement_rate,
        "is_short_candidate": item.is_short_candidate,
        "inferred_format": item.inferred_format,
        "inferred_hook_type": item.inferred_hook_type,
        "inferred_structure": item.inferred_structure,
        "hook_signature": item.hook_signature,
        "snippet": item.snippet,
        "statistics": item.statistics,
        "contentDetails": item.content_details,
    }


def _build_output_payload(
    *,
    source: str,
    params: dict[str, Any],
    items: list[TemplatePatternItem],
) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "params": params,
        "count": len(items),
        "items": [_serialize_item(item) for item in items],
    }


def _write_output(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _build_markdown_summary(payload: dict[str, Any]) -> str:
    items = payload.get("items", [])
    if not isinstance(items, list):
        items = []
    rows = [item for item in items if isinstance(item, dict)]
    top_by_speed = sorted(
        rows,
        key=lambda item: (
            item.get("views_per_hour") is None,
            -(float(item.get("views_per_hour") or 0.0)),
            -(int(item.get("view_count") or 0)),
        ),
    )[:10]
    hook_counts = Counter(str(item.get("hook_signature") or "unknown-hook") for item in rows)
    format_counts = Counter(str(item.get("inferred_format") or "unknown") for item in rows)
    format_views: dict[str, list[float]] = defaultdict(list)
    for item in rows:
        inferred_format = str(item.get("inferred_format") or "unknown")
        views_per_hour = item.get("views_per_hour")
        if isinstance(views_per_hour, (int, float)):
            format_views[inferred_format].append(float(views_per_hour))

    ranked_formats = sorted(
        format_counts.items(),
        key=lambda pair: (
            -(sum(format_views[pair[0]]) / len(format_views[pair[0]]) if format_views[pair[0]] else 0.0),
            -pair[1],
            pair[0],
        ),
    )
    recommended_formats = [name for name, _ in ranked_formats[:3]] or ["guess_the_player", "player_vs_player", "would_you_rather"]

    lines = [
        "# YouTube Template Patterns Summary",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- source: {payload.get('source')}",
        f"- count: {payload.get('count')}",
        "",
        "## Top videos by views_per_hour",
    ]
    for item in top_by_speed:
        lines.append(
            f"- {item.get('title')} | views_per_hour={item.get('views_per_hour')} | "
            f"format={item.get('inferred_format')} | hook={item.get('inferred_hook_type')}"
        )
    lines.extend(["", "## Top repeated hooks"])
    for hook_name, count in hook_counts.most_common(10):
        lines.append(f"- {hook_name}: {count}")
    lines.extend(["", "## Top inferred formats"])
    for format_name, count in format_counts.most_common(10):
        lines.append(f"- {format_name}: {count}")
    lines.extend(
        [
            "",
            "## Recommended formats for ShortsFactory",
        ]
    )
    for format_name in recommended_formats:
        lines.append(f"- {format_name}")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = _parse_args()
    try:
        api_key = _require_api_key()
        queries = args.query if args.query else DEFAULT_QUERIES
        params = {
            "region_code": args.region_code,
            "max_results": args.max_results,
            "queries": queries,
            "published_after": args.published_after,
            "output_dir": args.output_dir,
        }

        if len(queries) == 1:
            raw_videos = _collect_query_videos(
                api_key=api_key,
                api_base=args.api_base,
                queries=queries,
                region_code=args.region_code,
                max_results=args.max_results,
                published_after=args.published_after,
            )
            source = "search.list + videos.list"
        else:
            raw_videos = _collect_query_videos(
                api_key=api_key,
                api_base=args.api_base,
                queries=queries,
                region_code=args.region_code,
                max_results=args.max_results,
                published_after=args.published_after,
            )
            source = "search.list + videos.list"

        items = [_build_video_item(video) for video in raw_videos]
        items.sort(
            key=lambda item: (
                item.views_per_hour is None,
                -(item.views_per_hour or 0.0),
                -(item.view_count or 0),
            )
        )
        items = items[: args.max_results]

        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / "youtube_template_patterns.json"
        payload = _build_output_payload(source=source, params=params, items=items)
        _write_output(json_path, payload)

        summary_path = output_dir / "youtube_template_patterns_summary.md"
        summary_path.write_text(_build_markdown_summary(payload), encoding="utf-8")

        print(f"saved_json={json_path}")
        print(f"saved_summary={summary_path}")
        print(f"count={len(items)}")
        print(f"source={source}")
        for item in items[:10]:
            print(
                f"- {item.video_id} | views_per_hour={item.views_per_hour} | engagement_rate={item.engagement_rate} | "
                f"format={item.inferred_format} | hook={item.inferred_hook_type} | {item.title}"
            )
        return 0
    except Exception as exc:  # noqa: BLE001 - operator-facing collector
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
