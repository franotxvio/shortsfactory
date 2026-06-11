from __future__ import annotations

import math
import subprocess
from pathlib import Path


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_text_file(path: Path, text: str) -> None:
    ensure_parent_dir(path)
    path.write_text(text, encoding="utf-8")


def read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def run_command(command: list[str]) -> None:
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(
            "Command failed: "
            + " ".join(command)
            + f"\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )


def escape_ffmpeg_path(path: Path) -> str:
    escaped = path.resolve().as_posix()
    if len(escaped) > 1 and escaped[1] == ":":
        escaped = escaped[0] + r"\:" + escaped[2:]
    return escaped.replace("'", r"\'")


def probe_duration_seconds(path: Path) -> float | None:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        return None

    raw_duration = completed.stdout.strip()
    try:
        return float(raw_duration)
    except ValueError:
        return None


def seconds_to_srt_timestamp(seconds: float) -> str:
    total_milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def estimate_duration_from_text(text: str, words_per_minute: int = 150) -> float:
    word_count = max(1, len(text.split()))
    minutes = word_count / max(1, words_per_minute)
    return max(4.0, minutes * 60.0)


def build_srt_from_text(text: str, duration_seconds: float | None = None) -> str:
    words = text.split()
    if not words:
        return "1\n00:00:00,000 --> 00:00:04,000\n\n"

    duration = duration_seconds or estimate_duration_from_text(text)
    segment_size = max(4, math.ceil(len(words) / 4))
    segments: list[list[str]] = []
    for start in range(0, len(words), segment_size):
        segments.append(words[start : start + segment_size])

    segment_duration = duration / max(1, len(segments))
    lines: list[str] = []
    for index, segment in enumerate(segments, start=1):
        start_seconds = (index - 1) * segment_duration
        end_seconds = min(duration, index * segment_duration)
        lines.append(str(index))
        lines.append(
            f"{seconds_to_srt_timestamp(start_seconds)} --> {seconds_to_srt_timestamp(end_seconds)}"
        )
        lines.append(" ".join(segment))
        lines.append("")
    return "\n".join(lines)

