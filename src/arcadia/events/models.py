"""Validated structured event models for ARCADIA observability."""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

from arcadia.models import ArcadiaErrorInfo

JsonValue = Any

__all__ = ["EventLevel", "ArcadiaEvent"]

_EVENT_KIND_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")


def _deep_copy_json(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite float is not JSON-compatible")
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return [_deep_copy_json(item) for item in value]
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("mapping keys must be strings")
        return {key: _deep_copy_json(item) for key, item in value.items()}
    raise ValueError(f"value is not JSON-compatible: {type(value).__name__}")


def _validate_json_mapping(value: Any) -> dict[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise ValueError(f"expected a mapping, got {type(value).__name__}")
    return cast(dict[str, JsonValue], _deep_copy_json(dict(value)))


def _normalize_datetime(value: Any) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        raise ValueError("timestamp must be a datetime")
    if value.tzinfo is None:
        raise ValueError("naive datetime is not allowed; use a timezone-aware datetime")
    return value.astimezone(UTC)


def _validate_non_empty_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    text = cast(str, value.strip())
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text


def _new_event_id() -> str:
    return str(uuid.uuid4())


def _utc_now() -> datetime:
    return datetime.now(UTC)


class EventLevel(StrEnum):
    """Severity assigned to a structured event."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class EventModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
    )


class ArcadiaEvent(EventModel):
    """A validated, serializable record of ARCADIA activity."""

    event_id: str = Field(default_factory=_new_event_id)
    timestamp: datetime = Field(default_factory=_utc_now)
    kind: str
    level: EventLevel
    source: str
    message: str
    data: dict[str, JsonValue] = Field(default_factory=dict)
    run_id: str | None = None
    operation_id: str | None = None
    error: ArcadiaErrorInfo | None = None

    @field_validator("event_id", "source", "message")
    @classmethod
    def _validate_required_text(cls, value: Any, info: Any) -> str:
        return _validate_non_empty_str(value, info.field_name)

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("kind must be a string")
        if _EVENT_KIND_RE.fullmatch(value) is None:
            raise ValueError("kind must be a lowercase dot-delimited identifier")
        return value

    @field_validator("timestamp", mode="before")
    @classmethod
    def _validate_timestamp(cls, value: Any) -> datetime:
        normalized = _normalize_datetime(value)
        if normalized is None:
            raise ValueError("timestamp is required")
        return normalized

    @field_validator("data", mode="before")
    @classmethod
    def _validate_data(cls, value: Any) -> dict[str, JsonValue]:
        return _validate_json_mapping(value)

    @field_validator("run_id", "operation_id")
    @classmethod
    def _validate_identifier(cls, value: Any, info: Any) -> str | None:
        if value is None:
            return None
        return _validate_non_empty_str(value, info.field_name)
