import subprocess
from datetime import UTC

import pytest

import arcadia.hardware.detection as detection
from arcadia.hardware import (
    AcceleratorInfo,
    DeviceKind,
    HardwareCapabilities,
    HardwareDetectionError,
    OperatingSystem,
    SystemHardwareDetector,
    detect_hardware,
)


def test_detector_construction_performs_no_subprocess_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        detection.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected probe")),
    )
    SystemHardwareDetector()


def test_linux_detection_parses_cpu_memory_and_sorted_cuda(monkeypatch: pytest.MonkeyPatch) -> None:
    detector = SystemHardwareDetector(command_timeout_seconds=1)
    monkeypatch.setattr(detection.platform_module, "system", lambda: "Linux")
    monkeypatch.setattr(detection.platform_module, "machine", lambda: "x86_64")
    monkeypatch.setattr(detection.platform_module, "processor", lambda: "processor")
    monkeypatch.setattr(detection.platform_module, "release", lambda: "release")
    monkeypatch.setattr(detection.platform_module, "version", lambda: "version")
    monkeypatch.setattr(detection.platform_module, "python_version", lambda: "3.11")
    monkeypatch.setattr(detection.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(detection, "_read_linux_cpuinfo", lambda: (4, "CPU Model"))
    monkeypatch.setattr(
        detection, "_read_linux_memory", lambda: detection.MemoryInfo(total_bytes=100, available_bytes=40)
    )
    monkeypatch.setattr(
        detector,
        "_run_command",
        lambda _: '2, "GPU, Two", 20, 10, 555, uuid-2\n0, GPU Zero, 10, 5, 555, uuid-0\n',
    )
    caps = detector.detect()
    assert caps.detected_at.tzinfo == UTC
    assert caps.cpu.logical_cores == 8
    assert caps.memory.total_bytes == 100
    assert [(item.kind, item.index, item.name) for item in caps.accelerators] == [
        (DeviceKind.CUDA, 0, "GPU Zero"),
        (DeviceKind.CUDA, 2, "GPU, Two"),
    ]
    assert caps.accelerators[0].total_memory_bytes == 10 * 1024 * 1024


@pytest.mark.parametrize(
    ("failure", "expected_note"),
    [
        (FileNotFoundError(), "not found"),
        (subprocess.TimeoutExpired("nvidia-smi", 1), "timed out"),
        (OSError(), "probe failed"),
    ],
)
def test_cuda_probe_failures_preserve_partial_snapshot(
    monkeypatch: pytest.MonkeyPatch, failure: BaseException, expected_note: str
) -> None:
    detector = SystemHardwareDetector()
    monkeypatch.setattr(detector, "_run_command", lambda _: (_ for _ in ()).throw(failure))
    caps = detector.detect()
    assert caps.cpu.logical_cores >= 1
    assert all(item.kind != DeviceKind.CUDA for item in caps.accelerators)
    assert any(expected_note in note for note in caps.notes)


def test_malformed_cuda_discards_entire_inventory(monkeypatch: pytest.MonkeyPatch) -> None:
    detector = SystemHardwareDetector()
    monkeypatch.setattr(detector, "_run_command", lambda _: "0, valid, 10, 5, driver, id\nbad row")
    accelerators, note = detector._detect_cuda()
    assert accelerators == ()
    assert note == "CUDA detection unavailable: nvidia-smi returned malformed data"


def test_windows_memory_probe_success(monkeypatch: pytest.MonkeyPatch) -> None:
    detector = SystemHardwareDetector()
    monkeypatch.setattr(detection.platform_module, "system", lambda: "Windows")
    monkeypatch.setattr(detection.platform_module, "machine", lambda: "AMD64")
    monkeypatch.setattr(detection.platform_module, "processor", lambda: "processor")
    monkeypatch.setattr(detection.platform_module, "release", lambda: "release")
    monkeypatch.setattr(detection.platform_module, "version", lambda: "version")
    monkeypatch.setattr(detection.platform_module, "python_version", lambda: "3.11")
    monkeypatch.setattr(detection.os, "cpu_count", lambda: 4)
    monkeypatch.setattr(detection, "_windows_memory", lambda: detection.MemoryInfo(total_bytes=100, available_bytes=50))
    monkeypatch.setattr(detector, "_detect_cuda", lambda: ((), None))
    caps = detector.detect()
    assert caps.platform.operating_system == OperatingSystem.WINDOWS
    assert caps.memory == detection.MemoryInfo(total_bytes=100, available_bytes=50)


def test_windows_memory_probe_failure_is_a_note(monkeypatch: pytest.MonkeyPatch) -> None:
    detector = SystemHardwareDetector()
    monkeypatch.setattr(detection.platform_module, "system", lambda: "Windows")
    monkeypatch.setattr(detection.platform_module, "machine", lambda: "AMD64")
    monkeypatch.setattr(detection.platform_module, "processor", lambda: "processor")
    monkeypatch.setattr(detection.platform_module, "release", lambda: "release")
    monkeypatch.setattr(detection.platform_module, "version", lambda: "version")
    monkeypatch.setattr(detection.platform_module, "python_version", lambda: "3.11")
    monkeypatch.setattr(detection.os, "cpu_count", lambda: 4)
    monkeypatch.setattr(detection, "_windows_memory", lambda: (_ for _ in ()).throw(OSError("unavailable")))
    monkeypatch.setattr(detector, "_detect_cuda", lambda: ((), None))
    caps = detector.detect()
    assert caps.memory == detection.MemoryInfo()
    assert "Windows memory probe unavailable" in caps.notes


def test_apple_silicon_reports_metal_with_fallback_name(monkeypatch: pytest.MonkeyPatch) -> None:
    detector = SystemHardwareDetector()
    monkeypatch.setattr(detection.platform_module, "system", lambda: "Darwin")
    monkeypatch.setattr(detection.platform_module, "machine", lambda: "arm64")
    monkeypatch.setattr(detection.platform_module, "processor", lambda: "")
    monkeypatch.setattr(detection.platform_module, "release", lambda: "release")
    monkeypatch.setattr(detection.platform_module, "version", lambda: "version")
    monkeypatch.setattr(detection.platform_module, "python_version", lambda: "3.11")
    monkeypatch.setattr(detector, "_macos_value", lambda _: None)
    monkeypatch.setattr(detector, "_detect_cuda", lambda: ((), None))
    caps = detector.detect()
    assert caps.platform.operating_system == OperatingSystem.MACOS
    assert caps.accelerators == (AcceleratorInfo(kind=DeviceKind.METAL, index=0, name="Apple Silicon GPU"),)


def test_invalid_cpu_count_uses_one_and_intel_mac_has_no_metal(monkeypatch: pytest.MonkeyPatch) -> None:
    detector = SystemHardwareDetector()
    monkeypatch.setattr(detection.platform_module, "system", lambda: "Darwin")
    monkeypatch.setattr(detection.platform_module, "machine", lambda: "x86_64")
    monkeypatch.setattr(detection.platform_module, "processor", lambda: "Intel")
    monkeypatch.setattr(detection.platform_module, "release", lambda: "release")
    monkeypatch.setattr(detection.platform_module, "version", lambda: "version")
    monkeypatch.setattr(detection.platform_module, "python_version", lambda: "3.11")
    monkeypatch.setattr(detection.os, "cpu_count", lambda: None)
    monkeypatch.setattr(detector, "_detect_cuda", lambda: ((), None))
    caps = detector.detect()
    assert caps.cpu.logical_cores == 1
    assert caps.accelerators == ()


class FixedDetector:
    def __init__(self, result: object) -> None:
        self.result = result

    def detect(self) -> HardwareCapabilities:
        return self.result  # type: ignore[return-value]


class BrokenDetector:
    def detect(self) -> HardwareCapabilities:
        raise RuntimeError("boom")


def test_custom_detector_results_are_detached_and_invalid_results_translate() -> None:
    original = SystemHardwareDetector().detect()
    result = detect_hardware(FixedDetector(original))
    assert result == original
    assert result is not original
    with pytest.raises(HardwareDetectionError) as invalid:
        detect_hardware(FixedDetector("not a snapshot"))
    assert invalid.value.code == "hardware_snapshot_invalid"
    with pytest.raises(HardwareDetectionError) as failed:
        detect_hardware(BrokenDetector())
    assert failed.value.code == "hardware_probe_failed"
