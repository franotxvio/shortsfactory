from __future__ import annotations

import importlib.util
import inspect
import sys
import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "scripts" / "collect_youtube_template_patterns.py"

_SPEC = importlib.util.spec_from_file_location("collect_youtube_template_patterns", MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
youtube_template_miner = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = youtube_template_miner
_SPEC.loader.exec_module(youtube_template_miner)


def test_parse_duration_seconds() -> None:
    assert youtube_template_miner.parse_duration_seconds("PT59S") == 59
    assert youtube_template_miner.parse_duration_seconds("PT1M30S") == 90
    assert youtube_template_miner.parse_duration_seconds("PT1H2M3S") == 3_723
    assert youtube_template_miner.parse_duration_seconds("P1DT1H") == 90_000


def test_infer_content_format_matches_common_football_patterns() -> None:
    assert (
        youtube_template_miner.infer_content_format("Guess the player from 3 clues", "football quiz shorts")
        == "guess_the_player"
    )
    assert (
        youtube_template_miner.infer_content_format("Would you rather: Messi or Ronaldo?", "football shorts")
        == "would_you_rather"
    )
    assert youtube_template_miner.infer_content_format("Top 10 football rankings", "best players") == "ranking"


def test_infer_hook_type_prefers_debate_and_challenge() -> None:
    assert (
        youtube_template_miner.infer_hook_type(
            "Would you rather: Messi or Ronaldo?",
            "pick one",
            inferred_format="would_you_rather",
        )
        == "debate"
    )
    assert (
        youtube_template_miner.infer_hook_type(
            "Guess the player from 3 clues",
            "name the player",
            inferred_format="guess_the_player",
        )
        == "identity_guess"
    )


def test_infer_structure_matches_known_formats() -> None:
    assert youtube_template_miner.infer_structure("guess_the_player") == [
        "hook",
        "clue_1",
        "clue_2",
        "clue_3",
        "countdown",
        "answer_reveal",
    ]
    assert youtube_template_miner.infer_structure("player_vs_player") == [
        "hook",
        "option_a",
        "option_b",
        "comparison_prompt",
        "comment_prompt",
    ]


def test_no_download_function_exists() -> None:
    function_names = [name for name, value in inspect.getmembers(youtube_template_miner, inspect.isfunction)]
    assert not any("download" in name.lower() for name in function_names)
    source = inspect.getsource(youtube_template_miner)
    assert "yt_dlp" not in source.lower()


def test_load_env_file_uses_key_value_lines_and_ignores_comments(tmp_path: Path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "# comment",
                "",
                "YOUTUBE_DATA_API_KEY='from-file'",
                'QUOTED_VALUE="hello world"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("YOUTUBE_DATA_API_KEY", raising=False)
    monkeypatch.delenv("QUOTED_VALUE", raising=False)

    youtube_template_miner._load_env_file(env_path)

    assert os.environ["YOUTUBE_DATA_API_KEY"] == "from-file"
    assert os.environ["QUOTED_VALUE"] == "hello world"


def test_load_env_file_does_not_override_existing_env(tmp_path: Path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("YOUTUBE_DATA_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("YOUTUBE_DATA_API_KEY", "already-set")

    youtube_template_miner._load_env_file(env_path)

    assert os.environ["YOUTUBE_DATA_API_KEY"] == "already-set"


def test_require_api_key_supports_aliases(monkeypatch) -> None:
    monkeypatch.delenv("YOUTUBE_DATA_API_KEY", raising=False)
    monkeypatch.setenv("YOUTUBE_API_KEY", "alias-key")
    monkeypatch.setattr(youtube_template_miner, "_ENV_FILES", [])

    assert youtube_template_miner._require_api_key() == "alias-key"


def test_require_api_key_error_message_is_clear(monkeypatch) -> None:
    monkeypatch.delenv("YOUTUBE_DATA_API_KEY", raising=False)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_YOUTUBE_API_KEY", raising=False)
    monkeypatch.setattr(youtube_template_miner, "_ENV_FILES", [])

    try:
        youtube_template_miner._require_api_key()
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected RuntimeError")

    assert "YOUTUBE_DATA_API_KEY is not configured" in message
    assert "YOUTUBE_API_KEY" in message
    assert "GOOGLE_YOUTUBE_API_KEY" in message
    assert "from-file" not in message
