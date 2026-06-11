from enum import Enum

from sqlalchemy import Enum as SAEnum


class LifecycleStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class WorkflowStatus(str, Enum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"


class VideoStageStatus(str, Enum):
    DRAFT = "draft"
    SCRIPT_APPROVED = "script_approved"
    TTS_DONE = "tts_done"
    CAPTION_DONE = "caption_done"
    ASSET_READY = "asset_ready"
    PREVIEW_READY = "preview_ready"
    PREVIEW_APPROVED = "preview_approved"
    FINAL_RENDERED = "final_rendered"


class VideoExecutionMode(str, Enum):
    FAKE = "fake"
    REAL = "real"


def lifecycle_status_type(**kwargs: object) -> SAEnum:
    return SAEnum(
        LifecycleStatus,
        name="lifecycle_status",
        native_enum=True,
        values_callable=lambda enum_cls: [enum_member.value for enum_member in enum_cls],
        **kwargs,
    )


def workflow_status_type(**kwargs: object) -> SAEnum:
    return SAEnum(
        WorkflowStatus,
        name="workflow_status",
        native_enum=True,
        values_callable=lambda enum_cls: [enum_member.value for enum_member in enum_cls],
        **kwargs,
    )


def video_stage_status_type(**kwargs: object) -> SAEnum:
    return SAEnum(
        VideoStageStatus,
        name="video_stage_status",
        native_enum=True,
        values_callable=lambda enum_cls: [enum_member.value for enum_member in enum_cls],
        **kwargs,
    )
