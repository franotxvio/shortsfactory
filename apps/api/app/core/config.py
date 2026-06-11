from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    app_name: str = "ShortsFactory"
    app_debug: bool = True

    database_url: str = "postgresql+asyncpg://shortsfactory:shortsfactory@localhost:5433/shortsfactory"
    redis_url: str = "redis://localhost:6379/0"
    openai_api_key: str | None = None
    openai_llm_model: str = "gpt-4o-mini"
    openai_tts_model: str = "tts-1"
    openai_tts_voice: str = "onyx"
    openai_idea_max_tokens: int = 120
    openai_hook_max_tokens: int = 96
    openai_script_max_tokens: int = 900
    openai_policy_max_tokens: int = 128
    openai_policy_risk_threshold: float = 0.65
    openai_input_cost_per_1m_tokens_usd: float = 0.15
    openai_output_cost_per_1m_tokens_usd: float = 0.60
    openai_tts_cost_per_1m_chars_usd: float = 15.0
    local_storage_path: Path = Path("./storage")
    asset_pool_path: Path = Path("./storage/assets")
    audio_output_path: Path = Path("./storage/audio")
    caption_output_path: Path = Path("./storage/captions")
    preview_output_path: Path = Path("./storage/renders/previews")
    final_output_path: Path = Path("./storage/renders/finals")
    ffmpeg_path: str = "ffmpeg"
    whisper_command: str = "whisper"
    whisper_model: str = "base"
    whisper_model_path: Path = Path("./storage/models/ggml-base.en.bin")
    preview_width: int = 720
    preview_height: int = 1280
    final_width: int = 1080
    final_height: int = 1920

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[4] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
