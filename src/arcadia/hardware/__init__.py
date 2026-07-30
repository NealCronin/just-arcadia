"""Hardware capability detection and pure runtime-setting resolution."""

from arcadia.hardware.detection import HardwareDetector, SystemHardwareDetector, detect_hardware
from arcadia.hardware.errors import HardwareDetectionError, HardwareError, RuntimeResolutionError
from arcadia.hardware.models import (
    HARDWARE_SCHEMA_VERSION,
    AcceleratorInfo,
    CpuInfo,
    DeviceKind,
    HardwareCapabilities,
    MemoryInfo,
    OperatingSystem,
    PlatformInfo,
)
from arcadia.hardware.resolution import resolve_runtime_settings

__all__ = [
    "HARDWARE_SCHEMA_VERSION",
    "OperatingSystem",
    "DeviceKind",
    "PlatformInfo",
    "CpuInfo",
    "MemoryInfo",
    "AcceleratorInfo",
    "HardwareCapabilities",
    "HardwareDetector",
    "SystemHardwareDetector",
    "HardwareError",
    "HardwareDetectionError",
    "RuntimeResolutionError",
    "detect_hardware",
    "resolve_runtime_settings",
]
