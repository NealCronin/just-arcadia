"""Validated, transport-safe hardware capability models."""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

HARDWARE_SCHEMA_VERSION = 1

__all__ = [
    "HARDWARE_SCHEMA_VERSION",
    "OperatingSystem",
    "DeviceKind",
    "PlatformInfo",
    "CpuInfo",
    "MemoryInfo",
    "AcceleratorInfo",
    "HardwareCapabilities",
]

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class OperatingSystem(StrEnum):
    LINUX = "linux"
    WINDOWS = "windows"
    MACOS = "macos"
    OTHER = "other"


class DeviceKind(StrEnum):
    CPU = "cpu"
    CUDA = "cuda"
    METAL = "metal"


def _string(value: Any, field_name: str, *, required: bool = True) -> str | None:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    result = value.strip()
    if _CONTROL_RE.search(result):
        raise ValueError(f"{field_name} must not contain control characters")
    if required and not result:
        raise ValueError(f"{field_name} must not be empty")
    return result


def _exact_int(value: Any, field_name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{field_name} must be an integer greater than or equal to {minimum}")
    return value


def _copy_json(value: Any, field_name: str) -> Any:
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
        copied: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{field_name} contains a non-string mapping key")
            copied[key] = _copy_json(item, field_name)
        return copied
    raise ValueError(f"{field_name} contains an unsupported value type")


class _HardwareModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class PlatformInfo(_HardwareModel):
    operating_system: OperatingSystem
    release: str
    version: str
    machine: str
    python_version: str

    @field_validator("release", "version", mode="before")
    @classmethod
    def _optional_strings(cls, value: Any, info: Any) -> str:
        result = _string(value, info.field_name, required=False)
        assert result is not None
        return result

    @field_validator("machine", "python_version", mode="before")
    @classmethod
    def _required_strings(cls, value: Any, info: Any) -> str:
        result = _string(value, info.field_name)
        assert result is not None
        return result


class CpuInfo(_HardwareModel):
    logical_cores: int
    physical_cores: int | None = None
    architecture: str
    model: str | None = None

    @field_validator("logical_cores", mode="before")
    @classmethod
    def _logical_cores(cls, value: Any) -> int:
        return _exact_int(value, "logical_cores", minimum=1)

    @field_validator("physical_cores", mode="before")
    @classmethod
    def _physical_cores(cls, value: Any) -> int | None:
        return None if value is None else _exact_int(value, "physical_cores", minimum=1)

    @field_validator("architecture", mode="before")
    @classmethod
    def _architecture(cls, value: Any) -> str:
        result = _string(value, "architecture")
        assert result is not None
        return result

    @field_validator("model", mode="before")
    @classmethod
    def _model(cls, value: Any) -> str | None:
        return None if value is None else _string(value, "model")

    @field_validator("physical_cores")
    @classmethod
    def _physical_not_greater_than_logical(cls, value: int | None, info: Any) -> int | None:
        logical_cores = info.data.get("logical_cores")
        if value is not None and isinstance(logical_cores, int) and value > logical_cores:
            raise ValueError("physical_cores must not exceed logical_cores")
        return value


class MemoryInfo(_HardwareModel):
    total_bytes: int | None = None
    available_bytes: int | None = None

    @field_validator("total_bytes", mode="before")
    @classmethod
    def _total_bytes(cls, value: Any) -> int | None:
        return None if value is None else _exact_int(value, "total_bytes", minimum=1)

    @field_validator("available_bytes", mode="before")
    @classmethod
    def _available_bytes(cls, value: Any) -> int | None:
        return None if value is None else _exact_int(value, "available_bytes", minimum=0)

    @field_validator("available_bytes")
    @classmethod
    def _available_not_greater_than_total(cls, value: int | None, info: Any) -> int | None:
        total = info.data.get("total_bytes")
        if value is not None and isinstance(total, int) and value > total:
            raise ValueError("available_bytes must not exceed total_bytes")
        return value


class AcceleratorInfo(_HardwareModel):
    kind: Literal[DeviceKind.CUDA, DeviceKind.METAL]
    index: int
    name: str
    total_memory_bytes: int | None = None
    available_memory_bytes: int | None = None
    driver_version: str | None = None
    identifier: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("index", mode="before")
    @classmethod
    def _index(cls, value: Any) -> int:
        return _exact_int(value, "index", minimum=0)

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, value: Any) -> str:
        result = _string(value, "name")
        assert result is not None
        return result

    @field_validator("total_memory_bytes", mode="before")
    @classmethod
    def _total_memory(cls, value: Any) -> int | None:
        return None if value is None else _exact_int(value, "total_memory_bytes", minimum=1)

    @field_validator("available_memory_bytes", mode="before")
    @classmethod
    def _available_memory(cls, value: Any) -> int | None:
        return None if value is None else _exact_int(value, "available_memory_bytes", minimum=0)

    @field_validator("driver_version", "identifier", mode="before")
    @classmethod
    def _optional_string(cls, value: Any, info: Any) -> str | None:
        return None if value is None else _string(value, info.field_name)

    @field_validator("details", mode="before")
    @classmethod
    def _details(cls, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("details must be a mapping")
        copied = _copy_json(value, "details")
        assert isinstance(copied, dict)
        return copied

    @field_validator("available_memory_bytes")
    @classmethod
    def _available_memory_not_greater_than_total(cls, value: int | None, info: Any) -> int | None:
        total = info.data.get("total_memory_bytes")
        if value is not None and isinstance(total, int) and value > total:
            raise ValueError("available_memory_bytes must not exceed total_memory_bytes")
        return value


class HardwareCapabilities(_HardwareModel):
    schema_version: int = HARDWARE_SCHEMA_VERSION
    detected_at: datetime
    platform: PlatformInfo
    cpu: CpuInfo
    memory: MemoryInfo
    accelerators: tuple[AcceleratorInfo, ...] = ()
    notes: tuple[str, ...] = ()

    @field_validator("schema_version", mode="before")
    @classmethod
    def _schema_version(cls, value: Any) -> int:
        if type(value) is not int or value != HARDWARE_SCHEMA_VERSION:
            raise ValueError(f"schema_version must be exactly {HARDWARE_SCHEMA_VERSION}")
        return value

    @field_validator("detected_at", mode="before")
    @classmethod
    def _detected_at(cls, value: Any) -> datetime:
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if not isinstance(value, datetime):
            raise ValueError("detected_at must be a datetime")
        if value.tzinfo is None:
            raise ValueError("detected_at must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("accelerators", mode="before")
    @classmethod
    def _accelerators(cls, value: Any) -> tuple[AcceleratorInfo, ...]:
        if not isinstance(value, (tuple, list)):
            raise ValueError("accelerators must be a sequence")
        accelerators = tuple(value)
        identities: set[tuple[DeviceKind, int]] = set()
        for accelerator in accelerators:
            parsed = (
                accelerator if isinstance(accelerator, AcceleratorInfo) else AcceleratorInfo.model_validate(accelerator)
            )
            identity = (parsed.kind, parsed.index)
            if identity in identities:
                raise ValueError("accelerator identities must be unique")
            identities.add(identity)
        return tuple(
            sorted(
                (
                    item if isinstance(item, AcceleratorInfo) else AcceleratorInfo.model_validate(item)
                    for item in accelerators
                ),
                key=lambda item: (0 if item.kind == DeviceKind.CUDA else 1, item.index),
            )
        )

    @field_validator("notes", mode="before")
    @classmethod
    def _notes(cls, value: Any) -> tuple[str, ...]:
        if not isinstance(value, (tuple, list)):
            raise ValueError("notes must be a sequence of strings")
        result: list[str] = []
        for note in value:
            trimmed = _string(note, "notes")
            assert trimmed is not None
            result.append(trimmed)
        return tuple(sorted(set(result)))

    @property
    def available_devices(self) -> tuple[DeviceKind, ...]:
        devices = [DeviceKind.CPU]
        devices.extend(accelerator.kind for accelerator in self.accelerators if accelerator.kind not in devices)
        return tuple(devices)
