from datetime import UTC, datetime

import pytest

from arcadia.hardware import (
    AcceleratorInfo,
    CpuInfo,
    DeviceKind,
    HardwareCapabilities,
    MemoryInfo,
    OperatingSystem,
    PlatformInfo,
    RuntimeResolutionError,
    resolve_runtime_settings,
)
from arcadia.models import HuggingFaceFileSpec, LlamaServiceSpec, RequestedRuntimeSettings, SamServiceSpec, ServiceType


def hardware(*accelerators: AcceleratorInfo) -> HardwareCapabilities:
    return HardwareCapabilities(
        detected_at=datetime(2025, 1, 1, tzinfo=UTC),
        platform=PlatformInfo(
            operating_system=OperatingSystem.LINUX,
            release="release",
            version="version",
            machine="x86_64",
            python_version="3.11",
        ),
        cpu=CpuInfo(logical_cores=8, architecture="x86_64"),
        memory=MemoryInfo(total_bytes=32, available_bytes=16),
        accelerators=accelerators,
    )


def llama(values: dict[str, object]) -> LlamaServiceSpec:
    return LlamaServiceSpec(
        service_type=ServiceType.LLM,
        port=8080,
        model=HuggingFaceFileSpec(repo_id="org/model", filename="model.gguf"),
        requested_settings=RequestedRuntimeSettings(values=values),
    )


def sam(values: dict[str, object]) -> SamServiceSpec:
    return SamServiceSpec(
        port=8081, checkpoint_path="checkpoint.pt", requested_settings=RequestedRuntimeSettings(values=values)
    )


def test_auto_prefers_cuda_and_selects_lowest_device_index() -> None:
    caps = hardware(
        AcceleratorInfo(kind=DeviceKind.METAL, index=0, name="Apple"),
        AcceleratorInfo(kind=DeviceKind.CUDA, index=4, name="four"),
        AcceleratorInfo(kind=DeviceKind.CUDA, index=2, name="two"),
    )
    resolved = resolve_runtime_settings(llama({"advanced": {"nested": [1]}}), caps)
    assert resolved.backend == "llama_cpp"
    assert resolved.values == {"advanced": {"nested": [1]}, "device": "cuda", "device_index": 2}
    assert resolved.notes == ("device auto-selected CUDA accelerator 2",)


def test_auto_falls_back_to_metal_then_cpu_and_sam_maps_backend() -> None:
    metal = resolve_runtime_settings(sam({}), hardware(AcceleratorInfo(kind=DeviceKind.METAL, index=3, name="Apple")))
    cpu = resolve_runtime_settings(sam({}), hardware())
    assert metal.backend == "sam3"
    assert metal.values == {"device": "metal"}
    assert metal.notes == ("device auto-selected Metal accelerator 3",)
    assert cpu.values == {"device": "cpu"}
    assert cpu.notes == ("no supported accelerator detected; device auto-selected CPU",)


def test_explicit_device_alias_threads_and_unknown_values_are_preserved() -> None:
    requested = {"device": " MPS ", "threads": 3, "advanced": ["keep"]}
    spec = llama(requested)
    resolved = resolve_runtime_settings(spec, hardware(AcceleratorInfo(kind=DeviceKind.METAL, index=0, name="Apple")))
    assert resolved.values == {"device": "metal", "threads": 3, "advanced": ["keep"]}
    assert resolved.notes == ("normalized requested device 'mps' to 'metal'",)
    assert spec.requested_settings.values == requested


@pytest.mark.parametrize(
    ("values", "caps", "code"),
    [
        ({"device": "cuda"}, hardware(), "requested_device_unavailable"),
        ({"device": "metal"}, hardware(), "requested_device_unavailable"),
        ({"device": "bogus"}, hardware(), "runtime_settings_invalid"),
        ({"device": "cpu", "device_index": 0}, hardware(), "runtime_settings_invalid"),
        (
            {"device": "cuda", "device_index": 3},
            hardware(AcceleratorInfo(kind=DeviceKind.CUDA, index=2, name="two")),
            "requested_device_index_unavailable",
        ),
        ({"backend": "other"}, hardware(), "reserved_runtime_setting"),
        ({"threads": True}, hardware(), "runtime_settings_invalid"),
    ],
)
def test_invalid_and_unavailable_requests_have_stable_codes(
    values: dict[str, object], caps: HardwareCapabilities, code: str
) -> None:
    with pytest.raises(RuntimeResolutionError) as error:
        resolve_runtime_settings(llama(values), caps)
    assert error.value.code == code


def test_explicit_cuda_index_and_inputs_are_not_mutated_after_failure() -> None:
    caps = hardware(AcceleratorInfo(kind=DeviceKind.CUDA, index=3, name="three"))
    spec = llama({"device": "cuda", "device_index": 3})
    assert resolve_runtime_settings(spec, caps).values == {"device": "cuda", "device_index": 3}
    requested_before = spec.requested_settings.model_dump(mode="python")
    with pytest.raises(RuntimeResolutionError):
        resolve_runtime_settings(llama({"device": "cuda"}), hardware())
    assert spec.requested_settings.model_dump(mode="python") == requested_before
