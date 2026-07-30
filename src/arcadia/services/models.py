"""Public support models for the service lifecycle layer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from pydantic import Field, field_validator

from arcadia.models.common import (
    ModelBase,
    ResolvedRuntimeSettings,
    _normalize_datetime,
    _validate_json_mapping,
    _validate_port,
)
from arcadia.models.services import ServiceEndpoint, ServiceState, ServiceType

__all__ = ["BackendInstance", "ServiceDiagnostics", "ServiceLogSnapshot"]


@dataclass(frozen=True, slots=True)
class BackendInstance:
    """An opaque backend-owned service instance."""

    endpoint: ServiceEndpoint
    resolved_settings: ResolvedRuntimeSettings
    handle: object


class ServiceDiagnostics(ModelBase):
    """Safe, bounded diagnostics for a managed service."""

    port: int
    service_type: ServiceType
    state: ServiceState
    backend_id: str
    details: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime

    @field_validator("port", mode="before")
    @classmethod
    def _validate_port_field(cls, value: Any) -> int:
        return _validate_port(value)

    @field_validator("backend_id", mode="before")
    @classmethod
    def _validate_backend_id(cls, value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("backend_id must be a non-empty string")
        return value.strip()

    @field_validator("details", mode="before")
    @classmethod
    def _validate_details(cls, value: Any) -> dict[str, Any]:
        return cast(dict[str, Any], _validate_json_mapping(value))

    @field_validator("updated_at", mode="before")
    @classmethod
    def _validate_updated_at(cls, value: Any) -> datetime:
        normalized = _normalize_datetime(value)
        if normalized is None:
            raise ValueError("updated_at is required")
        return normalized


class ServiceLogSnapshot(ModelBase):
    """A bounded tail of backend-owned service logs."""

    port: int
    service_type: ServiceType
    backend_id: str
    text: str
    tail_lines: int
    updated_at: datetime

    @field_validator("port", mode="before")
    @classmethod
    def _validate_port_field(cls, value: Any) -> int:
        return _validate_port(value)

    @field_validator("backend_id", mode="before")
    @classmethod
    def _validate_backend_id(cls, value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("backend_id must be a non-empty string")
        return value.strip()

    @field_validator("text", mode="before")
    @classmethod
    def _validate_text(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("text must be a string")
        return value

    @field_validator("tail_lines", mode="before")
    @classmethod
    def _validate_tail_lines(cls, value: Any) -> int:
        if type(value) is not int or value < 0:
            raise ValueError("tail_lines must be an integer greater than or equal to zero")
        return value

    @field_validator("updated_at", mode="before")
    @classmethod
    def _validate_updated_at(cls, value: Any) -> datetime:
        normalized = _normalize_datetime(value)
        if normalized is None:
            raise ValueError("updated_at is required")
        return normalized
