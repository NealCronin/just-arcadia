from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from arcadia.hardware import (
    AcceleratorInfo,
    CpuInfo,
    DeviceKind,
    HardwareCapabilities,
    MemoryInfo,
    OperatingSystem,
    PlatformInfo,
)


def snapshot(**updates: Any) -> HardwareCapabilities:
    data: dict[str, Any] = {
        "detected_at": datetime(2025, 1, 1, tzinfo=UTC),
        "platform": PlatformInfo(
            operating_system=OperatingSystem.LINUX,
            release="6.0",
            version="build",
            machine="x86_64",
            python_version="3.11",
        ),
        "cpu": CpuInfo(logical_cores=8, physical_cores=4, architecture="x86_64"),
        "memory": MemoryInfo(total_bytes=32, available_bytes=16),
    }
    data.update(updates)
    return HardwareCapabilities(**data)


def test_hardware_snapshot_round_trips_and_orders_accelerators() -> None:
    details = {"nested": ["value"]}
    caps = snapshot(
        accelerators=(
            AcceleratorInfo(kind=DeviceKind.METAL, index=0, name="M"),
            AcceleratorInfo(kind=DeviceKind.CUDA, index=2, name="two", details=details),
            AcceleratorInfo(kind=DeviceKind.CUDA, index=0, name="zero"),
        ),
        notes=(" second ", "first"),
    )
    details["nested"].append("changed")
    assert [(item.kind, item.index) for item in caps.accelerators] == [
        (DeviceKind.CUDA, 0),
        (DeviceKind.CUDA, 2),
        (DeviceKind.METAL, 0),
    ]
    assert caps.accelerators[1].details == {"nested": ["value"]}
    assert caps.notes == ("first", "second")
    assert caps.available_devices == (DeviceKind.CPU, DeviceKind.CUDA, DeviceKind.METAL)
    assert HardwareCapabilities.model_validate_json(caps.model_dump_json()) == caps


@pytest.mark.parametrize("schema_version", [True, 1.0, "1", 2])
def test_schema_version_requires_exact_integer(schema_version: object) -> None:
    with pytest.raises(ValidationError):
        snapshot(schema_version=schema_version)


def test_snapshot_normalizes_utc_and_rejects_invalid_numerics() -> None:
    caps = snapshot(detected_at=datetime(2025, 1, 1, 2, tzinfo=timezone(timedelta(hours=2))))
    assert caps.detected_at == datetime(2025, 1, 1, tzinfo=UTC)
    with pytest.raises(ValidationError):
        snapshot(detected_at=datetime(2025, 1, 1))
    with pytest.raises(ValidationError):
        CpuInfo(logical_cores=True, architecture="x86_64")
    with pytest.raises(ValidationError):
        MemoryInfo(total_bytes=3, available_bytes=4)


def test_accelerators_require_unique_identities_and_json_details() -> None:
    accelerator = AcceleratorInfo(kind=DeviceKind.CUDA, index=0, name="gpu")
    with pytest.raises(ValidationError, match="identities"):
        snapshot(accelerators=(accelerator, accelerator))
    with pytest.raises(ValidationError, match="unsupported"):
        AcceleratorInfo(kind=DeviceKind.CUDA, index=0, name="gpu", details={"bad": object()})
    with pytest.raises(ValidationError, match="control"):
        PlatformInfo(
            operating_system=OperatingSystem.LINUX,
            release="",
            version="",
            machine="x\n86",
            python_version="3.11",
        )


@pytest.mark.parametrize(
    "factory",
    [
        lambda: CpuInfo(logical_cores=1, architecture="\tx86_64"),
        lambda: AcceleratorInfo(kind=DeviceKind.CUDA, index=0, name="GPU\n"),
        lambda: PlatformInfo(
            operating_system=OperatingSystem.LINUX,
            release="release",
            version="version",
            machine="\tmachine",
            python_version="3.11",
        ),
    ],
)
def test_model_strings_reject_leading_and_trailing_controls(factory: Callable[[], object]) -> None:
    with pytest.raises(ValidationError, match="control"):
        factory()
