"""Validated run manifests and filesystem paths for ARCADIA storage."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from arcadia.models import (
    AnalysisSpec,
    AnalysisStatus,
    ResolvedRuntimeSettings,
    ServiceEndpoint,
    ServiceSpec,
    parse_service_spec,
)
from arcadia.models.common import JsonValue

RUN_MANIFEST_SCHEMA_VERSION = 1

__all__ = ["RUN_MANIFEST_SCHEMA_VERSION", "RunManifest", "RunPaths"]

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_DRIVE_PREFIX_RE = re.compile(r"^[A-Za-z]:")


def _copy_json(value: Any, field_name: str) -> JsonValue:
    """Validate and recursively copy one JSON-compatible value."""
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{field_name} contains a non-finite float")
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return [_copy_json(item, field_name) for item in value]
    if isinstance(value, dict):
        copied: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{field_name} contains a non-string mapping key")
            copied[key] = _copy_json(item, field_name)
        return copied
    raise ValueError(f"{field_name} contains an unsupported value type")


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a mapping")
    result: dict[str, Any] = {}
    trimmed_keys: set[str] = set()
    for key, item in value.items():
        if not isinstance(key, str):
            raise ValueError(f"{field_name} keys must be strings")
        trimmed = key.strip()
        if not trimmed:
            raise ValueError(f"{field_name} keys must not be empty")
        if _CONTROL_RE.search(key):
            raise ValueError(f"{field_name} keys must not contain control characters")
        if trimmed in trimmed_keys:
            raise ValueError(f"{field_name} keys collide after trimming: {trimmed!r}")
        trimmed_keys.add(trimmed)
        result[key] = item
    return result


def _timestamp(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field_name} must be a valid ISO timestamp") from exc
    if not isinstance(value, datetime):
        raise ValueError(f"{field_name} must be a datetime")
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _run_id(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("run_id must be a string")
    if not value or value in {".", ".."}:
        raise ValueError("run_id must be a safe path component")
    if "/" in value or "\\" in value or _DRIVE_PREFIX_RE.match(value):
        raise ValueError("run_id must be a safe path component")
    if _CONTROL_RE.search(value):
        raise ValueError("run_id must not contain control characters")
    return value


@dataclass(frozen=True)
class RunPaths:
    """Absolute paths belonging to one run directory."""

    run_dir: Path
    manifest_path: Path
    event_log_path: Path
    artifact_index_path: Path
    outputs_dir: Path

    @classmethod
    def from_run_dir(cls, run_dir: str | Path) -> RunPaths:
        absolute = Path(run_dir).absolute()
        return cls(
            run_dir=absolute,
            manifest_path=absolute / "manifest.json",
            event_log_path=absolute / "events.jsonl",
            artifact_index_path=absolute / "artifacts.jsonl",
            outputs_dir=absolute / "outputs",
        )

    def __post_init__(self) -> None:
        values = (self.run_dir, self.manifest_path, self.event_log_path, self.artifact_index_path, self.outputs_dir)
        if any(not isinstance(path, Path) or not path.is_absolute() for path in values):
            raise ValueError("RunPaths paths must be absolute pathlib.Path values")
        expected = (
            self.run_dir / "manifest.json",
            self.run_dir / "events.jsonl",
            self.run_dir / "artifacts.jsonl",
            self.run_dir / "outputs",
        )
        if (self.manifest_path, self.event_log_path, self.artifact_index_path, self.outputs_dir) != expected:
            raise ValueError("RunPaths fields must be derived from run_dir")


class RunManifest(BaseModel):
    """Versioned, immutable-core metadata for one analysis run."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    schema_version: int = RUN_MANIFEST_SCHEMA_VERSION
    run_id: str
    created_at: datetime
    updated_at: datetime
    analysis_spec: AnalysisSpec
    analysis_status: AnalysisStatus
    configuration: dict[str, JsonValue] = Field(default_factory=dict)
    service_specs: dict[str, ServiceSpec] = Field(default_factory=dict)
    resolved_settings: dict[str, ResolvedRuntimeSettings] = Field(default_factory=dict)
    hardware: dict[str, JsonValue] = Field(default_factory=dict)
    endpoint_assignments: dict[str, ServiceEndpoint] = Field(default_factory=dict)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: Any) -> int:
        if type(value) is not int or value != RUN_MANIFEST_SCHEMA_VERSION:
            raise ValueError(f"schema_version must be exactly {RUN_MANIFEST_SCHEMA_VERSION}")
        return value

    @field_validator("run_id", mode="before")
    @classmethod
    def _validate_run_id(cls, value: Any) -> str:
        return _run_id(value)

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _validate_timestamps(cls, value: Any, info: Any) -> datetime:
        return _timestamp(value, info.field_name)

    @field_validator("configuration", "hardware", "metadata", mode="before")
    @classmethod
    def _validate_json_maps(cls, value: Any, info: Any) -> dict[str, JsonValue]:
        mapping = _mapping(value, info.field_name)
        return {key: _copy_json(item, info.field_name) for key, item in mapping.items()}

    @field_validator("service_specs", mode="before")
    @classmethod
    def _validate_service_specs(cls, value: Any) -> dict[str, ServiceSpec]:
        mapping = _mapping(value, "service_specs")
        result: dict[str, ServiceSpec] = {}
        for key, spec in mapping.items():
            if isinstance(spec, dict):
                try:
                    result[key] = parse_service_spec(spec)
                except Exception as exc:
                    raise ValueError(f"invalid service spec for {key!r}: {type(exc).__name__}") from exc
            elif isinstance(spec, BaseModel):
                try:
                    result[key] = parse_service_spec(spec.model_dump(mode="python"))
                except Exception as exc:
                    raise ValueError(f"invalid service spec for {key!r}: {type(exc).__name__}") from exc
            else:
                raise ValueError(f"service_specs[{key!r}] must be a service specification")
        return result

    @field_validator("resolved_settings", mode="before")
    @classmethod
    def _validate_resolved_settings(cls, value: Any) -> dict[str, ResolvedRuntimeSettings]:
        return _mapping(value, "resolved_settings")

    @field_validator("endpoint_assignments", mode="before")
    @classmethod
    def _validate_endpoints(cls, value: Any) -> dict[str, ServiceEndpoint]:
        return _mapping(value, "endpoint_assignments")

    @model_validator(mode="after")
    def _validate_coherence(self) -> RunManifest:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not be before created_at")
        if self.analysis_status.run_id != self.run_id:
            raise ValueError("analysis_status.run_id must match run_id")
        if self.analysis_status.tool_name != self.analysis_spec.tool_name:
            raise ValueError("analysis_status.tool_name must match analysis_spec.tool_name")
        service_keys = set(self.service_specs)
        if set(self.resolved_settings) - service_keys:
            raise ValueError("resolved_settings contains an unknown service key")
        if set(self.endpoint_assignments) - service_keys:
            raise ValueError("endpoint_assignments contains an unknown service key")
        for key, endpoint in self.endpoint_assignments.items():
            if endpoint.service_type != self.service_specs[key].service_type:
                raise ValueError(f"endpoint service_type does not match service_specs[{key!r}]")
        return self
