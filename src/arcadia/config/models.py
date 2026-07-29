"""Configuration domain models for arcadia.config.

Pydantic 2 models for the human-editable JSON configuration layer.
All models use frozen=True, extra="forbid", and validate_default=True.

This module depends only on arcadia.models and the Python standard library.
"""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from arcadia.models import ConfigurationError
from arcadia.models.services import (
    SamServiceSpec,
    ServiceSpec,
    parse_service_spec,
)

__all__ = [
    "CONFIG_SCHEMA_VERSION",
    "NodeKind",
    "NodeConfig",
    "ServiceProfile",
    "StageBinding",
    "ToolProfile",
    "RetryPolicy",
    "OutputSettings",
    "ArcadiaConfig",
]

CONFIG_SCHEMA_VERSION: Literal[1] = 1

_CONTROLS = "".join(chr(i) for i in range(0, 0x20)) + "\x7f"
_NAME_CONTROLS = _CONTROLS


# ---------------------------------------------------------------------------
# JSON helpers (private — do not import arcadia.models private helpers)
# ---------------------------------------------------------------------------


def _is_json_value(value: Any) -> bool:
    """Return True when value is JSON-compatible after recursive inspection."""
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


def _validate_json_mapping(value: Any) -> dict[str, Any]:
    """Validate a JSON-compatible mapping and return a defensive copy."""
    if not isinstance(value, dict):
        raise ValueError(f"expected a mapping, got {type(value).__name__}")
    if not _is_json_value(value):
        raise ValueError("mapping contains non-JSON-compatible values")
    return {str(k): _deep_copy_json(v) for k, v in value.items()}


# ---------------------------------------------------------------------------
# Shared validators
# ---------------------------------------------------------------------------


def _validate_name(name: str, field_name: str) -> str:
    """Validate a name is non-empty after trimming and has no control characters."""
    stripped = name.strip() if isinstance(name, str) else ""
    if not stripped:
        raise ValueError(f"{field_name} must not be empty")
    if any(c in _NAME_CONTROLS for c in stripped):
        raise ValueError(f"{field_name} must not contain control characters")
    return stripped


def _validate_description(value: str) -> str:
    """Validate a description string. Empty is allowed; otherwise trim and reject controls."""
    if not isinstance(value, str):
        raise ValueError("description must be a string")
    stripped = value.strip()
    if stripped and any(c in _CONTROLS for c in stripped):
        raise ValueError("description must not contain control characters")
    return stripped


def _reject_bool_as_numeric(value: Any, field_name: str) -> None:
    """Raise if a boolean is passed where a numeric type is expected."""
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a number, not a boolean")


# ---------------------------------------------------------------------------
# NodeKind
# ---------------------------------------------------------------------------


class NodeKind(StrEnum):
    """Whether a compute node is local or remote."""

    LOCAL = "local"
    REMOTE = "remote"


# ---------------------------------------------------------------------------
# NodeConfig
# ---------------------------------------------------------------------------


class NodeConfig(BaseModel):
    """Configuration for a single compute node."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    kind: NodeKind
    address: Any = None  # NodeAddress | None — validated below
    description: str = ""
    extensions: dict[str, Any] = {}

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: str) -> str:
        return _validate_description(value)

    @field_validator("extensions")
    @classmethod
    def _validate_extensions(cls, value: Any) -> dict[str, Any]:
        return _validate_json_mapping(value)

    @field_validator("address")
    @classmethod
    def _validate_address_type(cls, value: Any) -> Any:
        """Type-check address; kind-specific validation is in ArcadiaConfig."""
        if value is None:
            return None
        # Accept dict (will be parsed) or NodeAddress-like object
        from arcadia.models import NodeAddress

        if isinstance(value, dict):
            return NodeAddress.model_validate(value)
        if hasattr(value, "host") and hasattr(value, "instruction_port"):
            return value
        raise ValueError("address must be a NodeAddress or a mapping with host and instruction_port")

    @model_validator(mode="after")
    def _validate_kind_address(self) -> NodeConfig:
        if self.kind == NodeKind.LOCAL and self.address is not None:
            raise ValueError("local nodes must not have an address")
        if self.kind == NodeKind.REMOTE and self.address is None:
            raise ValueError("remote nodes must have an address")
        return self


# ---------------------------------------------------------------------------
# ServiceProfile
# ---------------------------------------------------------------------------


class ServiceProfile(BaseModel):
    """A reusable desired service configuration pairing a node with a spec."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    node: str
    spec: ServiceSpec
    description: str = ""
    extensions: dict[str, Any] = {}

    @field_validator("node")
    @classmethod
    def _validate_node_name(cls, value: str) -> str:
        return _validate_name(value, "node")

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: str) -> str:
        return _validate_description(value)

    @field_validator("extensions")
    @classmethod
    def _validate_extensions(cls, value: Any) -> dict[str, Any]:
        return _validate_json_mapping(value)

    @field_validator("spec")
    @classmethod
    def _validate_spec(cls, value: Any) -> ServiceSpec:
        if isinstance(value, dict):
            return parse_service_spec(value)
        # Accept already-parsed specs
        if isinstance(value, (SamServiceSpec,)):
            return value
        # Check for LlamaServiceSpec via service_type attribute
        if hasattr(value, "service_type"):
            return value  # type: ignore[no-any-return]
        raise ValueError("spec must be a service specification mapping or model")


# ---------------------------------------------------------------------------
# StageBinding
# ---------------------------------------------------------------------------


class StageBinding(BaseModel):
    """Binds an inference stage to a service profile."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    service_profile: str
    extensions: dict[str, Any] = {}

    @field_validator("service_profile")
    @classmethod
    def _validate_service_profile_name(cls, value: str) -> str:
        return _validate_name(value, "service_profile")

    @field_validator("extensions")
    @classmethod
    def _validate_extensions(cls, value: Any) -> dict[str, Any]:
        return _validate_json_mapping(value)


# ---------------------------------------------------------------------------
# ToolProfile
# ---------------------------------------------------------------------------


class ToolProfile(BaseModel):
    """Configuration for a research tool profile."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    tool_name: str
    stages: dict[str, StageBinding] = {}
    settings: dict[str, Any] = {}
    description: str = ""
    extensions: dict[str, Any] = {}

    @field_validator("tool_name")
    @classmethod
    def _validate_tool_name(cls, value: str) -> str:
        return _validate_name(value, "tool_name")

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: str) -> str:
        return _validate_description(value)

    @field_validator("settings")
    @classmethod
    def _validate_settings(cls, value: Any) -> dict[str, Any]:
        return _validate_json_mapping(value)

    @field_validator("extensions")
    @classmethod
    def _validate_extensions(cls, value: Any) -> dict[str, Any]:
        return _validate_json_mapping(value)

    @field_validator("stages")
    @classmethod
    def _validate_stages(cls, value: Any) -> dict[str, StageBinding]:
        if not isinstance(value, dict):
            raise ValueError("stages must be a mapping")
        result: dict[str, StageBinding] = {}
        for key, val in value.items():
            stage_name = _validate_name(str(key), "stage name")
            if isinstance(val, dict):
                result[stage_name] = StageBinding.model_validate(val)
            elif isinstance(val, StageBinding):
                result[stage_name] = val
            else:
                raise ValueError(f"stage '{stage_name}' must be a StageBinding or mapping")
        return result


# ---------------------------------------------------------------------------
# RetryPolicy
# ---------------------------------------------------------------------------


class RetryPolicy(BaseModel):
    """Retry configuration for transient failures."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    max_attempts: int = 3
    initial_delay_seconds: float = 1.0
    multiplier: float = 2.0
    maximum_delay_seconds: float = 10.0

    @field_validator("max_attempts", mode="before")
    @classmethod
    def _reject_bool_max_attempts(cls, value: Any) -> Any:
        _reject_bool_as_numeric(value, "max_attempts")
        return value

    @field_validator("initial_delay_seconds", "multiplier", "maximum_delay_seconds", mode="before")
    @classmethod
    def _reject_bool_delays(cls, value: Any, info: Any) -> Any:
        field_name = info.field_name
        _reject_bool_as_numeric(value, field_name)
        return value

    @field_validator("max_attempts")
    @classmethod
    def _validate_max_attempts(cls, value: int) -> int:
        if value < 1:
            raise ValueError("max_attempts must be at least 1")
        return value

    @field_validator("initial_delay_seconds", "maximum_delay_seconds")
    @classmethod
    def _validate_delays(cls, value: float, info: Any) -> float:
        field_name = info.field_name
        if not math.isfinite(value):
            raise ValueError(f"{field_name} must be finite")
        if value < 0:
            raise ValueError(f"{field_name} must be non-negative")
        return value

    @field_validator("multiplier")
    @classmethod
    def _validate_multiplier(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("multiplier must be finite")
        if value < 1.0:
            raise ValueError("multiplier must be at least 1.0")
        return value

    @model_validator(mode="after")
    def _validate_delay_relationship(self) -> RetryPolicy:
        if self.maximum_delay_seconds < self.initial_delay_seconds:
            raise ValueError("maximum_delay_seconds must be at least initial_delay_seconds")
        return self


# ---------------------------------------------------------------------------
# OutputSettings
# ---------------------------------------------------------------------------


class OutputSettings(BaseModel):
    """Output directory configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    root: str = "./outputs"
    extensions: dict[str, Any] = {}

    @field_validator("root")
    @classmethod
    def _validate_root(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("root must be a string")
        if not value:
            raise ValueError("root must not be empty")
        if "\0" in value or "\r" in value or "\n" in value:
            raise ValueError("root must not contain null bytes, CR, or LF")
        return value

    @field_validator("extensions")
    @classmethod
    def _validate_extensions(cls, value: Any) -> dict[str, Any]:
        return _validate_json_mapping(value)


# ---------------------------------------------------------------------------
# ArcadiaConfig
# ---------------------------------------------------------------------------


class ArcadiaConfig(BaseModel):
    """Root configuration document for ARCADIA."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    schema_version: int = CONFIG_SCHEMA_VERSION
    nodes: dict[str, NodeConfig] = {}
    service_profiles: dict[str, ServiceProfile] = {}
    tool_profiles: dict[str, ToolProfile] = {}
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    output: OutputSettings = Field(default_factory=OutputSettings)
    extensions: dict[str, Any] = {}

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: Any) -> int:
        if isinstance(value, bool):
            raise ValueError("schema_version must be an integer")
        if not isinstance(value, int):
            raise ValueError("schema_version must be an integer")
        if value != CONFIG_SCHEMA_VERSION:
            raise ConfigurationError(
                f"unsupported schema version: {value}",
                code="config_unsupported_version",
            )
        return value

    @field_validator("extensions")
    @classmethod
    def _validate_extensions(cls, value: Any) -> dict[str, Any]:
        return _validate_json_mapping(value)

    @field_validator("nodes")
    @classmethod
    def _validate_nodes(cls, value: Any) -> dict[str, NodeConfig]:
        if not isinstance(value, dict):
            raise ValueError("nodes must be a mapping")
        result: dict[str, NodeConfig] = {}
        for key, val in value.items():
            name = _validate_name(str(key), "node name")
            if isinstance(val, dict):
                result[name] = NodeConfig.model_validate(val)
            elif isinstance(val, NodeConfig):
                result[name] = val
            else:
                raise ValueError(f"node '{name}' must be a NodeConfig or mapping")
        return result

    @field_validator("service_profiles")
    @classmethod
    def _validate_service_profiles(cls, value: Any) -> dict[str, ServiceProfile]:
        if not isinstance(value, dict):
            raise ValueError("service_profiles must be a mapping")
        result: dict[str, ServiceProfile] = {}
        for key, val in value.items():
            name = _validate_name(str(key), "service profile name")
            if isinstance(val, dict):
                result[name] = ServiceProfile.model_validate(val)
            elif isinstance(val, ServiceProfile):
                result[name] = val
            else:
                raise ValueError(f"service profile '{name}' must be a ServiceProfile or mapping")
        return result

    @field_validator("tool_profiles")
    @classmethod
    def _validate_tool_profiles(cls, value: Any) -> dict[str, ToolProfile]:
        if not isinstance(value, dict):
            raise ValueError("tool_profiles must be a mapping")
        result: dict[str, ToolProfile] = {}
        for key, val in value.items():
            name = _validate_name(str(key), "tool profile name")
            if isinstance(val, dict):
                result[name] = ToolProfile.model_validate(val)
            elif isinstance(val, ToolProfile):
                result[name] = val
            else:
                raise ValueError(f"tool profile '{name}' must be a ToolProfile or mapping")
        return result

    @model_validator(mode="after")
    def _validate_cross_references(self) -> ArcadiaConfig:
        # 1. Every service profile references an existing node
        for sp_name, sp in self.service_profiles.items():
            if sp.node not in self.nodes:
                raise ValueError(f"service profile '{sp_name}' references unknown node '{sp.node}'")

        # 2. Every stage binding in every tool profile references an existing service profile
        for tp_name, tp in self.tool_profiles.items():
            for stage_name, binding in tp.stages.items():
                if binding.service_profile not in self.service_profiles:
                    raise ValueError(
                        f"tool profile '{tp_name}', stage '{stage_name}' "
                        f"references unknown service profile '{binding.service_profile}'"
                    )

        # 3. At most one local node
        local_count = sum(1 for n in self.nodes.values() if n.kind == NodeKind.LOCAL)
        if local_count > 1:
            raise ValueError("at most one local node is allowed")

        return self
