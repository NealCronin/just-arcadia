"""Bounded, standard-library hardware capability detection."""

from __future__ import annotations

import csv
import ctypes
import math
import os
import platform as platform_module
import subprocess
from ctypes import wintypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from arcadia.hardware.errors import HardwareDetectionError
from arcadia.hardware.models import (
    AcceleratorInfo,
    CpuInfo,
    DeviceKind,
    HardwareCapabilities,
    MemoryInfo,
    OperatingSystem,
    PlatformInfo,
)

__all__ = ["HardwareDetector", "SystemHardwareDetector", "detect_hardware"]

_MIB = 1024 * 1024


@runtime_checkable
class HardwareDetector(Protocol):
    """Provider of a fresh, validated hardware snapshot."""

    def detect(self) -> HardwareCapabilities: ...


def _operating_system(system: str) -> OperatingSystem:
    normalized = system.strip().lower()
    if normalized == "linux":
        return OperatingSystem.LINUX
    if normalized == "windows":
        return OperatingSystem.WINDOWS
    if normalized == "darwin":
        return OperatingSystem.MACOS
    return OperatingSystem.OTHER


def _read_linux_cpuinfo() -> tuple[int | None, str | None]:
    try:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None
    blocks = [block for block in text.split("\n\n") if block.strip()]
    model: str | None = None
    physical_pairs: set[tuple[str, str]] = set()
    for block in blocks:
        fields: dict[str, str] = {}
        for line in block.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            fields[key.strip().lower()] = value.strip()
        if model is None:
            model = fields.get("model name") or fields.get("hardware")
        physical_id = fields.get("physical id")
        core_id = fields.get("core id")
        if physical_id is not None and core_id is not None:
            physical_pairs.add((physical_id, core_id))
    return (len(physical_pairs) or None), model


def _read_linux_memory() -> MemoryInfo:
    try:
        fields: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8", errors="replace").splitlines():
            key, separator, value = line.partition(":")
            if not separator:
                continue
            amount = value.strip().split(maxsplit=1)
            if amount and amount[0].isdigit():
                fields[key] = int(amount[0]) * 1024
        return MemoryInfo(total_bytes=fields.get("MemTotal"), available_bytes=fields.get("MemAvailable"))
    except (OSError, ValueError):
        return _memory_from_sysconf()


def _memory_from_sysconf() -> MemoryInfo:
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        total_pages = os.sysconf("SC_PHYS_PAGES")
        available_pages = os.sysconf("SC_AVPHYS_PAGES")
        if any(type(value) is not int or value < 0 for value in (page_size, total_pages, available_pages)):
            raise ValueError("invalid sysconf memory values")
        total = page_size * total_pages
        available = page_size * available_pages
        return MemoryInfo(total_bytes=total or None, available_bytes=available if total else None)
    except (AttributeError, OSError, ValueError):
        return MemoryInfo()


def _windows_memory() -> MemoryInfo:
    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(MemoryStatusEx)
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        raise OSError("Windows API unavailable")
    kernel32 = windll.kernel32
    global_memory_status_ex = kernel32.GlobalMemoryStatusEx
    global_memory_status_ex.argtypes = [ctypes.POINTER(MemoryStatusEx)]
    global_memory_status_ex.restype = wintypes.BOOL
    if not global_memory_status_ex(ctypes.byref(status)):
        raise OSError("GlobalMemoryStatusEx failed")
    return MemoryInfo(total_bytes=int(status.ullTotalPhys), available_bytes=int(status.ullAvailPhys))


class SystemHardwareDetector:
    """Detect local capabilities without caching, allocation, or model imports."""

    def __init__(self, *, command_timeout_seconds: float = 5.0) -> None:
        if (
            isinstance(command_timeout_seconds, bool)
            or not isinstance(command_timeout_seconds, (int, float))
            or not math.isfinite(command_timeout_seconds)
            or command_timeout_seconds <= 0
        ):
            raise ValueError("command_timeout_seconds must be a finite number greater than zero")
        self._command_timeout_seconds = float(command_timeout_seconds)

    def _run_command(self, arguments: list[str]) -> str:
        result = subprocess.run(
            arguments,
            capture_output=True,
            check=False,
            shell=False,
            text=True,
            timeout=self._command_timeout_seconds,
        )
        if result.returncode != 0:
            raise OSError("command returned a non-zero status")
        return result.stdout

    def _macos_value(self, key: str) -> str | None:
        try:
            value = self._run_command(["sysctl", "-n", key]).strip()
        except (OSError, subprocess.SubprocessError):
            return None
        return value or None

    def _detect_cuda(self) -> tuple[tuple[AcceleratorInfo, ...], str | None]:
        try:
            output = self._run_command(
                [
                    "nvidia-smi",
                    "--query-gpu=index,name,memory.total,memory.free,driver_version,uuid",
                    "--format=csv,noheader,nounits",
                ]
            )
        except FileNotFoundError:
            return (), "CUDA detection unavailable: nvidia-smi was not found"
        except subprocess.TimeoutExpired:
            return (), "CUDA detection unavailable: nvidia-smi timed out"
        except (OSError, subprocess.SubprocessError):
            return (), "CUDA detection unavailable: nvidia-smi probe failed"
        if not output.strip():
            return (), "CUDA detection unavailable: nvidia-smi returned no devices"
        try:
            rows = list(csv.reader(output.splitlines(), skipinitialspace=True))
            accelerators: list[AcceleratorInfo] = []
            for row in rows:
                if len(row) != 6:
                    raise ValueError("unexpected CUDA CSV column count")
                index_text, name, total_text, free_text, driver_version, identifier = (field.strip() for field in row)
                if not index_text.isdigit() or not total_text.isdigit() or not free_text.isdigit():
                    raise ValueError("invalid CUDA numeric field")
                accelerators.append(
                    AcceleratorInfo(
                        kind=DeviceKind.CUDA,
                        index=int(index_text),
                        name=name,
                        total_memory_bytes=int(total_text) * _MIB,
                        available_memory_bytes=int(free_text) * _MIB,
                        driver_version=driver_version,
                        identifier=identifier,
                    )
                )
            if not accelerators:
                raise ValueError("empty CUDA inventory")
            return tuple(sorted(accelerators, key=lambda accelerator: accelerator.index)), None
        except (ValueError, csv.Error):
            return (), "CUDA detection unavailable: nvidia-smi returned malformed data"

    def detect(self) -> HardwareCapabilities:
        notes: list[str] = []
        try:
            operating_system = _operating_system(platform_module.system())
            logical_cores = os.cpu_count()
            if type(logical_cores) is not int or logical_cores < 1:
                logical_cores = 1
                notes.append("logical CPU count unavailable; using 1")
            architecture = platform_module.machine().strip() or "unknown"
            physical_cores: int | None = None
            apple_gpu_name: str | None = None
            cpu_model = platform_module.processor().strip() or None
            if operating_system == OperatingSystem.LINUX:
                physical_cores, detected_model = _read_linux_cpuinfo()
                cpu_model = detected_model or cpu_model
                if physical_cores is None:
                    notes.append("Linux physical CPU probe unavailable")
                memory = _read_linux_memory()
                if memory.total_bytes is None:
                    notes.append("Linux memory probe unavailable")
            elif operating_system == OperatingSystem.WINDOWS:
                if cpu_model is None:
                    notes.append("Windows CPU model probe unavailable")
                notes.append("Windows physical CPU probe unavailable")
                try:
                    memory = _windows_memory()
                except (AttributeError, OSError):
                    memory = MemoryInfo()
                    notes.append("Windows memory probe unavailable")
            else:
                memory = _memory_from_sysconf()
            if operating_system == OperatingSystem.MACOS:
                physical_text = self._macos_value("hw.physicalcpu")
                if physical_text is not None and physical_text.isdigit():
                    physical_cores = int(physical_text)
                else:
                    notes.append("macOS physical CPU probe unavailable")
                model_value = self._macos_value("machdep.cpu.brand_string")
                apple_gpu_name = model_value
                cpu_model = model_value or cpu_model
                memory_text = self._macos_value("hw.memsize")
                if memory_text is not None and memory_text.isdigit():
                    memory = MemoryInfo(total_bytes=int(memory_text), available_bytes=memory.available_bytes)
                elif memory.total_bytes is None:
                    notes.append("macOS memory probe unavailable")
            if physical_cores is not None and physical_cores > logical_cores:
                physical_cores = None
                notes.append("physical CPU count was inconsistent and omitted")
            accelerators: list[AcceleratorInfo] = []
            cuda, cuda_note = self._detect_cuda()
            accelerators.extend(cuda)
            if cuda_note is not None:
                notes.append(cuda_note)
            if operating_system == OperatingSystem.MACOS and architecture.lower() in {"arm64", "aarch64"}:
                metal_name = apple_gpu_name or "Apple Silicon GPU"
                accelerators.append(AcceleratorInfo(kind=DeviceKind.METAL, index=0, name=metal_name))
            return HardwareCapabilities(
                detected_at=datetime.now(UTC),
                platform=PlatformInfo(
                    operating_system=operating_system,
                    release=platform_module.release(),
                    version=platform_module.version(),
                    machine=architecture,
                    python_version=platform_module.python_version(),
                ),
                cpu=CpuInfo(
                    logical_cores=logical_cores,
                    physical_cores=physical_cores,
                    architecture=architecture,
                    model=cpu_model,
                ),
                memory=memory,
                accelerators=tuple(accelerators),
                notes=tuple(notes),
            )
        except HardwareDetectionError:
            raise
        except Exception as exc:
            raise HardwareDetectionError(
                "could not detect local hardware capabilities",
                code="hardware_probe_failed",
                cause=exc,
            ) from exc


def detect_hardware(detector: HardwareDetector | None = None) -> HardwareCapabilities:
    """Return a detached snapshot from ``detector`` or the local system."""

    active_detector: HardwareDetector
    if detector is None:
        active_detector = SystemHardwareDetector()
    elif isinstance(detector, HardwareDetector):
        active_detector = detector
    else:
        raise HardwareDetectionError(
            "hardware detector must implement detect()",
            code="hardware_snapshot_invalid",
        )
    try:
        result = active_detector.detect()
    except HardwareDetectionError:
        raise
    except Exception as exc:
        raise HardwareDetectionError(
            "hardware detector failed",
            code="hardware_probe_failed",
            cause=exc,
        ) from exc
    if not isinstance(result, HardwareCapabilities):
        raise HardwareDetectionError(
            "hardware detector returned an invalid snapshot",
            code="hardware_snapshot_invalid",
        )
    try:
        return HardwareCapabilities.model_validate(result.model_dump(mode="python"))
    except Exception as exc:
        raise HardwareDetectionError(
            "hardware detector returned an invalid snapshot",
            code="hardware_snapshot_invalid",
            cause=exc,
        ) from exc
