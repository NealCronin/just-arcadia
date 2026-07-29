"""Common domain types and shared configuration for arcadia.models.

This module is the foundation of the domain layer. It must not import HTTP,
subprocess, filesystem, UI, or heavy inference libraries.
"""

from __future__ import annotations

import ipaddress
import math
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "JsonValue",
    "ModelBase",
    "NodeAddress",
    "HuggingFaceFileSpec",
    "RequestedRuntimeSettings",
    "ResolvedRuntimeSettings",
    "ArtifactVisibility",
]

# Type alias for recursive JSON-compatible values. Used in annotations.
JsonValue = Any


# ---------------------------------------------------------------------------
# JSON validation helpers
# ---------------------------------------------------------------------------

_HOST_CONTROLS = "".join(chr(i) for i in range(0, 0x20)) + "\x7f"


def _is_json_value(value: Any) -> bool:
    """Return True when ``value`` is JSON-compatible after recursive inspection."""
    if value is None:
        return True
    if isinstance(value, bool):
        return True
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, str):
        return True
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and _is_json_value(v) for k, v in value.items())
    return False


def _deep_copy_json(value: Any) -> Any:
    """Return a defensive copy of a JSON value, or raise ValueError."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int) or isinstance(value, float):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("non-finite float is not JSON-compatible")
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return [_deep_copy_json(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _deep_copy_json(v) for k, v in value.items()}
    raise ValueError(f"value is not JSON-compatible: {type(value).__name__}")


def _validate_json_mapping(value: Any) -> Any:
    """Validate a JSON-compatible mapping and return a defensive copy."""
    if not isinstance(value, dict):
        raise ValueError(f"expected a mapping, got {type(value).__name__}")
    if not _is_json_value(value):
        raise ValueError("mapping contains non-JSON-compatible values")
    return {str(k): _deep_copy_json(v) for k, v in value.items()}


def _normalize_datetime(value: Any) -> datetime | None:
    """Validate a timestamp and normalize to UTC.

    ``None`` passes through. Naive datetimes are rejected. Timezone-aware
    datetimes are converted to UTC. ISO 8601 strings (from JSON round trips)
    are parsed before validation.
    """
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        raise ValueError("timestamp must be a datetime")
    if value.tzinfo is None:
        raise ValueError("naive datetime is not allowed; use a timezone-aware datetime")
    return value.astimezone(UTC)


def _validate_non_empty_str(value: Any, field_name: str) -> str:
    """Validate that a value is a non-empty string after trimming."""
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must not be empty")
    return stripped


# ---------------------------------------------------------------------------
# Shared model base
# ---------------------------------------------------------------------------


class ModelBase(BaseModel):
    """Shared base for arcadia.models using Pydantic 2.

    Concrete models inherit this config: extra fields are rejected,
    attribute assignment is blocked (frozen=True), and defaults are
    validated. Nested mutable values (dicts, lists) are not automatically
    deep-frozen; callers must not share mutable mapping objects between an
    active run and editable configuration.
    Validation is explicit per-field; ``strict=True`` is not enabled globally.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
    )


# ---------------------------------------------------------------------------
# Host and port validation (shared by NodeAddress and ServiceEndpoint)
# ---------------------------------------------------------------------------


def _validate_host(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("host must be a string")
    host = value.strip()
    if not host:
        raise ValueError("host must not be empty")

    # Reject control characters, spaces, and obviously invalid characters
    if any(c in host for c in _HOST_CONTROLS):
        raise ValueError("host must not contain control characters")
    _INVALID_HOST_CHARS = " /\\@?#"
    if any(c in host for c in _INVALID_HOST_CHARS):
        bad = next(c for c in host if c in _INVALID_HOST_CHARS)
        raise ValueError(f"host contains invalid character: {bad!r}")

    # Try IP address parsing first (IPv4 or unbracketed IPv6)
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass

    # After IP parsing fails, reject colons (localhost:9000 is not a valid host)
    if ":" in host:
        raise ValueError("host must not contain a colon (port not allowed in host)")

    # Accept the literal string "localhost"
    if host == "localhost":
        return host

    # Validate as DNS hostname
    if len(host) > 253:
        raise ValueError("host exceeds maximum DNS length of 253 characters")
    labels = host.split(".")
    for label in labels:
        if not label:
            raise ValueError("host must not contain empty labels (consecutive dots)")
        if len(label) > 63:
            raise ValueError("host label exceeds maximum length of 63 characters")
        if not re.match(r"^[A-Za-z0-9-]+$", label):
            raise ValueError(f"host label contains invalid characters: {label!r}")
        if label[0] == "-" or label[-1] == "-":
            raise ValueError(f"host label must not start or end with a hyphen: {label!r}")

    return host


def _validate_port(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("port must be an integer, not a bool")
    if not isinstance(value, int):
        raise ValueError("port must be an integer")
    if not (1 <= value <= 65535):
        raise ValueError("port must be between 1 and 65535")
    return value


# ---------------------------------------------------------------------------
# NodeAddress
# ---------------------------------------------------------------------------


class NodeAddress(ModelBase):
    """Address of an Arcadia instruction endpoint.

    ``host`` accepts IPv4, IPv6, and ordinary hostnames. The ``base_url``
    property brackets IPv6 addresses per RFC 3986.
    """

    host: str
    instruction_port: int
    scheme: Literal["http"] = "http"

    @field_validator("host", mode="before")
    @classmethod
    def _validate_host_field(cls, value: Any) -> str:
        return _validate_host(value)

    @field_validator("instruction_port", mode="before")
    @classmethod
    def _validate_port_field(cls, value: Any) -> int:
        return _validate_port(value)

    @property
    def base_url(self) -> str:
        host = self.host
        try:
            if ipaddress.ip_address(host).version == 6:
                host = f"[{host}]"
        except ValueError:
            pass
        return f"{self.scheme}://{host}:{self.instruction_port}"


# ---------------------------------------------------------------------------
# HuggingFaceFileSpec
# ---------------------------------------------------------------------------

_REPO_OWNER_REPO = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")


def _validate_repo_id(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("repo_id must be a string")
    repo_id = value.strip()
    if "/" not in repo_id:
        raise ValueError("repo_id must be exactly 'owner/repository'")
    owner, _, repository = repo_id.partition("/")
    if "/" in repository or not owner or not repository:
        raise ValueError("repo_id must be exactly 'owner/repository'")
    if not _REPO_OWNER_REPO.match(owner) or not _REPO_OWNER_REPO.match(repository):
        raise ValueError("repo_id owner/repository contain invalid characters")
    return repo_id


def _validate_filename(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("filename must be a string")
    filename = value.strip()
    if not filename:
        raise ValueError("filename must not be empty")
    if "\x00" in filename or any(c in filename for c in _HOST_CONTROLS):
        raise ValueError("filename contains control characters")
    if "\\" in filename:
        raise ValueError("filename must not contain backslashes")
    if " " in filename or "\t" in filename:
        raise ValueError("filename must not contain whitespace")
    if not filename.lower().endswith(".gguf"):
        raise ValueError("filename must end with .gguf")
    if "/" in filename:
        parts = filename.split("/")
        for part in parts:
            if part == "":
                raise ValueError("filename must not contain absolute paths or empty path components")
            if part == "." or part == "..":
                raise ValueError("filename must not contain '.' or '..' components")
    return filename


def _validate_revision(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("revision must be a string")
    revision = value.strip()
    if not revision:
        raise ValueError("revision must not be empty")
    if "\x00" in revision or any(c in revision for c in _HOST_CONTROLS):
        raise ValueError("revision contains control characters")
    if revision in (".", ".."):
        raise ValueError("revision must not be '.' or '..'")
    return revision


class HuggingFaceFileSpec(ModelBase):
    """A Hugging Face model file specification, validated structurally."""

    repo_id: str
    filename: str
    revision: str = "main"

    @field_validator("repo_id", mode="before")
    @classmethod
    def _validate_repo_id_field(cls, value: Any) -> str:
        return _validate_repo_id(value)

    @field_validator("filename", mode="before")
    @classmethod
    def _validate_filename_field(cls, value: Any) -> str:
        return _validate_filename(value)

    @field_validator("revision", mode="before")
    @classmethod
    def _validate_revision_field(cls, value: Any) -> str:
        return _validate_revision(value)


# ---------------------------------------------------------------------------
# Runtime settings
# ---------------------------------------------------------------------------


class RequestedRuntimeSettings(ModelBase):
    """User-requested runtime settings, validated but uninterpreted."""

    values: dict[str, Any] = Field(default_factory=dict)

    @field_validator("values", mode="before")
    @classmethod
    def _validate_values(cls, value: Any) -> Any:
        return _validate_json_mapping(value)


class ResolvedRuntimeSettings(ModelBase):
    """Runtime settings after resolution. ``backend`` is non-empty."""

    backend: str
    values: dict[str, Any]
    notes: tuple[str, ...] = ()

    @field_validator("backend")
    @classmethod
    def _backend_non_empty(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("backend must be a string")
        stripped = value.strip()
        if not stripped:
            raise ValueError("backend must be a non-empty string")
        return stripped

    @field_validator("values", mode="before")
    @classmethod
    def _validate_values(cls, value: Any) -> Any:
        return _validate_json_mapping(value)

    @field_validator("notes")
    @classmethod
    def _validate_notes(cls, value: Any) -> tuple[str, ...]:
        if not isinstance(value, (tuple, list)):
            raise ValueError("notes must be a sequence of strings")
        result = []
        for n in value:
            if not isinstance(n, str):
                raise ValueError("notes must be strings")
            stripped = n.strip()
            if not stripped:
                raise ValueError("notes must not contain empty strings after stripping")
            result.append(stripped)
        return tuple(result)


# ---------------------------------------------------------------------------
# ArtifactVisibility (lives here so all model files can import it)
# ---------------------------------------------------------------------------


class ArtifactVisibility(StrEnum):
    """Visibility of a recorded artifact."""

    FINAL = "final"
    INTERNAL = "internal"
