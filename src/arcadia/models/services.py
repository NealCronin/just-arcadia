"""Service domain models for arcadia.models.

These models describe inference service specifications, endpoints, status,
and operation progress. They carry no execution logic, process handles,
or network behavior.

This module must not import HTTP, subprocess, filesystem, UI, or heavy
inference libraries.
"""

from __future__ import annotations

import ipaddress
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import field_validator, model_validator

from arcadia.models.common import (
    HuggingFaceFileSpec,
    ModelBase,
    RequestedRuntimeSettings,
    ResolvedRuntimeSettings,
    _normalize_datetime,
    _validate_host,
    _validate_port,
)
from arcadia.models.errors import ArcadiaErrorInfo

__all__ = [
    "ServiceType",
    "ServiceState",
    "OperationState",
    "LlamaServiceSpec",
    "SamServiceSpec",
    "ServiceSpec",
    "parse_service_spec",
    "ServiceEndpoint",
    "ServiceStatus",
    "OperationStatus",
]


class ServiceType(StrEnum):
    """Kinds of inference services."""

    LLM = "llm"
    VISUAL_LLM = "visual_llm"
    SAM3 = "sam3"


class ServiceState(StrEnum):
    """Lifecycle state of a single service instance."""

    stopped = "stopped"
    resolving = "resolving"
    downloading = "downloading"
    starting = "starting"
    ready = "ready"
    failed = "failed"
    stopping = "stopping"


class OperationState(StrEnum):
    """State of a long-running operation."""

    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


# ---------------------------------------------------------------------------
# Service specifications
# ---------------------------------------------------------------------------


class LlamaServiceSpec(ModelBase):
    """Specification for a llama.cpp-backed LLM service."""

    service_type: Literal[ServiceType.LLM, ServiceType.VISUAL_LLM]
    port: int
    model: HuggingFaceFileSpec
    projector: HuggingFaceFileSpec | None = None
    requested_settings: RequestedRuntimeSettings = RequestedRuntimeSettings()

    @field_validator("port", mode="before")
    @classmethod
    def _validate_port(cls, value: Any) -> int:
        return _validate_port(value)

    @model_validator(mode="after")
    def _validate_projector_rules(self) -> LlamaServiceSpec:
        is_visual = self.service_type == ServiceType.VISUAL_LLM
        if is_visual and self.projector is None:
            raise ValueError("visual_llm service requires a projector")
        if not is_visual and self.projector is not None:
            raise ValueError("llm service must not have a projector")
        return self


class SamServiceSpec(ModelBase):
    """Specification for a Segment Anything service."""

    service_type: Literal[ServiceType.SAM3] = ServiceType.SAM3
    port: int
    checkpoint_path: str
    requested_settings: RequestedRuntimeSettings = RequestedRuntimeSettings()

    @field_validator("port", mode="before")
    @classmethod
    def _validate_port(cls, value: Any) -> int:
        return _validate_port(value)

    @field_validator("checkpoint_path")
    @classmethod
    def _validate_checkpoint_path(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("checkpoint_path must be a string")
        stripped = value.strip()
        if not stripped:
            raise ValueError("checkpoint_path must not be empty")
        if "\x00" in stripped:
            raise ValueError("checkpoint_path must not contain null bytes")
        if "\r" in stripped or "\n" in stripped:
            raise ValueError("checkpoint_path must not contain CR or LF")
        return stripped


ServiceSpec = LlamaServiceSpec | SamServiceSpec


def parse_service_spec(data: Any) -> ServiceSpec:
    """Parse and validate a service specification mapping.

    Unknown service types and unknown fields fail validation.
    """
    if not isinstance(data, dict):
        raise ValueError("service spec must be a mapping")
    return _parse_service_spec(data)


def _parse_service_spec(data: dict[str, Any]) -> ServiceSpec:
    """Internal helper to parse a service spec into a ServiceSpec."""
    service_type_raw = data.get("service_type")
    if not isinstance(service_type_raw, str):
        raise ValueError("service_type is required")
    try:
        service_type = ServiceType(service_type_raw)
    except ValueError:
        raise ValueError(f"unknown service_type: {service_type_raw}") from None

    if service_type == ServiceType.SAM3:
        return SamServiceSpec(**data)
    if service_type in (ServiceType.LLM, ServiceType.VISUAL_LLM):
        return LlamaServiceSpec(**data)
    raise ValueError(f"unknown service_type: {service_type_raw}")


# ---------------------------------------------------------------------------
# ServiceEndpoint
# ---------------------------------------------------------------------------


class ServiceEndpoint(ModelBase):
    """Network endpoint of a ready service instance."""

    host: str
    port: int
    service_type: ServiceType
    scheme: Literal["http"] = "http"

    @field_validator("host", mode="before")
    @classmethod
    def _validate_host_field(cls, value: Any) -> str:
        return _validate_host(value)

    @field_validator("port", mode="before")
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
        return f"{self.scheme}://{host}:{self.port}"


# ---------------------------------------------------------------------------
# ServiceStatus
# ---------------------------------------------------------------------------


class ServiceStatus(ModelBase):
    """Status of a single service instance on a compute node."""

    port: int
    service_type: ServiceType
    state: ServiceState
    endpoint: ServiceEndpoint | None = None
    requested_spec: ServiceSpec | None = None
    resolved_settings: ResolvedRuntimeSettings | None = None
    operation_id: str | None = None
    error: ArcadiaErrorInfo | None = None
    started_at: datetime | None = None
    updated_at: datetime

    @field_validator("port", mode="before")
    @classmethod
    def _validate_port(cls, value: Any) -> int:
        return _validate_port(value)

    @field_validator("operation_id", mode="before")
    @classmethod
    def _validate_operation_id(cls, value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("operation_id must be a string")
        stripped = value.strip()
        if not stripped:
            raise ValueError("operation_id must not be empty")
        return stripped

    @field_validator("started_at", "updated_at", mode="before")
    @classmethod
    def _validate_timestamps(cls, value: Any) -> datetime | None:
        return _normalize_datetime(value)

    @model_validator(mode="after")
    def _validate_coherence(self) -> ServiceStatus:
        state = self.state
        if state == ServiceState.ready:
            if self.endpoint is None:
                raise ValueError("ready state requires an endpoint")
            if self.resolved_settings is None:
                raise ValueError("ready state requires resolved settings")
        if state != ServiceState.failed and self.error is not None:
            raise ValueError("non-failed service must not have an error")
        if state == ServiceState.failed and self.error is None:
            raise ValueError("failed state requires an error")
        if state == ServiceState.stopped:
            if self.endpoint is not None:
                raise ValueError("stopped state must not expose an endpoint")
        # Cross-field consistency: endpoint, spec, and status must agree on port and service_type
        if self.endpoint is not None:
            if self.endpoint.port != self.port:
                raise ValueError("endpoint port must match status port")
            if self.endpoint.service_type != self.service_type:
                raise ValueError("endpoint service_type must match status service_type")
        if self.requested_spec is not None:
            if self.requested_spec.port != self.port:
                raise ValueError("requested_spec port must match status port")
            if self.requested_spec.service_type != self.service_type:
                raise ValueError("requested_spec service_type must match status service_type")
        if self.started_at is not None and self.updated_at is not None:
            if self.started_at > self.updated_at:
                raise ValueError("started_at cannot be after updated_at")
        return self


# ---------------------------------------------------------------------------
# OperationStatus
# ---------------------------------------------------------------------------


class OperationStatus(ModelBase):
    """Progress of a single service operation (e.g. start, stop, replace)."""

    operation_id: str
    port: int
    state: OperationState
    service_state: ServiceState | None = None
    progress: float | None = None
    message: str = ""
    error: ArcadiaErrorInfo | None = None
    started_at: datetime | None = None
    updated_at: datetime
    finished_at: datetime | None = None

    @field_validator("operation_id", mode="before")
    @classmethod
    def _validate_operation_id(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("operation_id must be a string")
        stripped = value.strip()
        if not stripped:
            raise ValueError("operation_id must not be empty")
        return stripped

    @field_validator("port", mode="before")
    @classmethod
    def _validate_port(cls, value: Any) -> int:
        return _validate_port(value)

    @field_validator("progress", mode="before")
    @classmethod
    def _validate_progress(cls, value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool):
            raise ValueError("progress must be a float, not a bool")
        if not isinstance(value, (int, float)):
            raise ValueError("progress must be a number")
        fval = float(value)
        if not (0.0 <= fval <= 1.0):
            raise ValueError("progress must be between 0.0 and 1.0")
        return fval

    @field_validator("started_at", "updated_at", "finished_at", mode="before")
    @classmethod
    def _validate_timestamps(cls, value: Any) -> datetime | None:
        return _normalize_datetime(value)

    @model_validator(mode="after")
    def _validate_state_timestamps(self) -> OperationStatus:
        state = self.state
        if state == OperationState.pending:
            if self.started_at is not None or self.finished_at is not None:
                raise ValueError("pending operation must not have start or finish times")
        if state == OperationState.running:
            if self.started_at is None:
                raise ValueError("running operation must have a start time")
            if self.finished_at is not None:
                raise ValueError("running operation must not have a finish time")
        if state in (OperationState.succeeded, OperationState.failed):
            if self.started_at is None or self.finished_at is None:
                raise ValueError("terminal operation must have start and finish times")
        if state == OperationState.failed and self.error is None:
            raise ValueError("failed operation must have an error")
        if state != OperationState.failed and self.error is not None:
            raise ValueError("non-failed operation must not have an error")
        # Validate timestamp ordering
        times = [t for t in (self.started_at, self.updated_at, self.finished_at) if t is not None]
        for i in range(len(times) - 1):
            if times[i] > times[i + 1]:
                raise ValueError("timestamps must be non-decreasing")
        return self
