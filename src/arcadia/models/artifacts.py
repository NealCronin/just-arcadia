"""Artifact domain models for arcadia.models.

An artifact is a file produced during an analysis run. This module defines
the structured record kept for later retrieval and presentation. No
filesystem access occurs here.

This module must not import HTTP, subprocess, filesystem, UI, or heavy
inference libraries.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import Field, field_validator

from arcadia.models.common import (
    ArtifactVisibility,
    ModelBase,
    _validate_json_mapping,
)

__all__ = [
    "ArtifactRecord",
]


def _validate_non_empty_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must not be empty")
    return stripped


class ArtifactRecord(ModelBase):
    """A single artifact recorded during an analysis run."""

    artifact_id: str
    name: str
    relative_path: str
    media_type: str
    visibility: ArtifactVisibility
    stage: str | None = None
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("artifact_id", "name", "media_type", "stage", mode="before")
    @classmethod
    def _validate_str_fields(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _validate_non_empty_str(value, "field")

    @field_validator("relative_path")
    @classmethod
    def _validate_relative_path(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("relative_path must be a string")
        stripped = value.strip()
        if not stripped:
            raise ValueError("relative_path must not be empty")
        # Reject null bytes and control characters
        controls = "".join(chr(i) for i in range(0, 0x20)) + "\x7F"
        if "\x00" in stripped or any(c in stripped for c in controls):
            raise ValueError("relative_path contains control characters")
        # Reject backslashes — paths must use POSIX separators
        if "\\" in stripped:
            raise ValueError("relative_path must not contain backslashes")
        # Reject absolute paths (leading slash on POSIX)
        if stripped.startswith("/"):
            raise ValueError("relative_path must not be an absolute path")
        # Reject Windows drive letters
        if len(stripped) >= 2 and stripped[1] == ":":
            raise ValueError("relative_path must not contain Windows drive letters")
        # Split into components and validate
        parts = stripped.split("/")
        for part in parts:
            if part == "":
                raise ValueError("relative_path must not contain empty components")
            if part == "..":
                raise ValueError("relative_path must not contain '..' components")
            if part == ".":
                raise ValueError("relative_path must not contain '.' components")
        return stripped

    @field_validator("created_at", mode="before")
    @classmethod
    def _validate_created_at(cls, value: Any) -> datetime:
        if isinstance(value, str):
            # Parse ISO 8601 strings from JSON round trips
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if not isinstance(value, datetime):
            raise ValueError("created_at must be a datetime")
        if value.tzinfo is None:
            raise ValueError("naive datetime is not allowed; use a timezone-aware datetime")
        return value.astimezone(timezone.utc)

    @field_validator("metadata", mode="before")
    @classmethod
    def _validate_metadata(cls, value: Any) -> Any:
        return _validate_json_mapping(value)

