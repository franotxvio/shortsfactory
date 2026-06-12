from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.core.config import Settings, get_settings
from app.services.video_production import VideoProductionService


def _resolve_config_path(value: Path | None, *, settings: Settings) -> Path | None:
    if value is None:
        return None
    if value.is_absolute():
        return value
    return (settings.local_storage_path.parent / value).resolve()


def _path_is_configured(value: Path | None, *, settings: Settings) -> bool:
    resolved_path = _resolve_config_path(value, settings=settings)
    return bool(resolved_path and resolved_path.exists() and resolved_path.is_file())


def check_youtube_config(settings: Settings | None = None) -> dict[str, object]:
    current_settings = settings or get_settings()
    client_secrets_configured = _path_is_configured(current_settings.youtube_client_secrets_path, settings=current_settings)
    token_configured = _path_is_configured(current_settings.youtube_token_path, settings=current_settings)
    enabled = bool(current_settings.youtube_upload_enabled)

    warnings: list[str] = []
    if not enabled:
        warnings.append("YOUTUBE_UPLOAD_ENABLED is false; upload remains disabled.")
    if current_settings.youtube_client_secrets_path is None:
        warnings.append("YOUTUBE_CLIENT_SECRETS_PATH is not configured.")
    elif not client_secrets_configured:
        warnings.append("YOUTUBE_CLIENT_SECRETS_PATH does not point to an existing file.")
    if current_settings.youtube_token_path is None:
        warnings.append("YOUTUBE_TOKEN_PATH is not configured.")
    elif not token_configured:
        warnings.append("YOUTUBE_TOKEN_PATH does not point to an existing file.")

    return {
        "enabled": enabled,
        "client_secrets_configured": client_secrets_configured,
        "token_configured": token_configured,
        "warnings": warnings,
    }


def get_youtube_auth_status(settings: Settings | None = None) -> dict[str, object]:
    config = check_youtube_config(settings)
    enabled = bool(config["enabled"])
    client_secrets_configured = bool(config["client_secrets_configured"])
    token_configured = bool(config["token_configured"])
    ready_for_upload = enabled and client_secrets_configured and token_configured

    warnings = list(config["warnings"])
    if enabled and not ready_for_upload:
        warnings.append("Upload is enabled, but the auth files are not fully configured yet.")
    if ready_for_upload:
        warnings = []

    return {
        "enabled": enabled,
        "client_secrets_configured": client_secrets_configured,
        "token_configured": token_configured,
        "ready_for_upload": ready_for_upload,
        "warnings": warnings,
    }


async def simulate_youtube_upload(
    *,
    video_id: int,
    service: VideoProductionService,
    settings: Settings | None = None,
) -> dict[str, object]:
    current_settings = settings or get_settings()
    auth_status = get_youtube_auth_status(current_settings)
    readiness = await service.get_publish_readiness(video_id=video_id)

    upload_enabled = bool(current_settings.youtube_upload_enabled)
    auth_ready = bool(auth_status["ready_for_upload"])
    readiness_ready = bool(readiness["ready"])
    checked_at = datetime.now(timezone.utc)

    if not upload_enabled:
        return {
            "video_id": video_id,
            "slug": readiness.get("video_slug"),
            "upload_status": "ready_but_disabled",
            "youtube_video_id": None,
            "message": "YOUTUBE_UPLOAD_ENABLED está desativado; upload real continua bloqueado.",
            "checked_at": checked_at,
        }

    if not readiness_ready:
        return {
            "video_id": video_id,
            "slug": readiness.get("video_slug"),
            "upload_status": "blocked",
            "youtube_video_id": None,
            "message": "O vídeo ainda não está pronto para publicação local.",
            "checked_at": checked_at,
        }

    if not auth_ready:
        return {
            "video_id": video_id,
            "slug": readiness.get("video_slug"),
            "upload_status": "blocked",
            "youtube_video_id": None,
            "message": "A autenticação do YouTube ainda não está pronta para upload.",
            "checked_at": checked_at,
        }

    return {
        "video_id": video_id,
        "slug": readiness.get("video_slug"),
        "upload_status": "simulated",
        "youtube_video_id": None,
        "message": "Upload simulado com sucesso. Nenhuma chamada ao YouTube foi feita.",
        "checked_at": checked_at,
    }
