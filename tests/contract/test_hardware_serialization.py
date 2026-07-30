from datetime import UTC, datetime

from arcadia.hardware import CpuInfo, HardwareCapabilities, MemoryInfo, OperatingSystem, PlatformInfo


def test_hardware_capabilities_json_round_trip_is_lossless() -> None:
    snapshot = HardwareCapabilities(
        detected_at=datetime(2025, 1, 1, tzinfo=UTC),
        platform=PlatformInfo(
            operating_system=OperatingSystem.LINUX,
            release="6.0",
            version="build",
            machine="x86_64",
            python_version="3.11",
        ),
        cpu=CpuInfo(logical_cores=4, architecture="x86_64"),
        memory=MemoryInfo(),
        notes=("no accelerator",),
    )
    assert HardwareCapabilities.model_validate_json(snapshot.model_dump_json()) == snapshot
