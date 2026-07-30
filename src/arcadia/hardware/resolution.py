"""Pure runtime-setting resolution against a hardware snapshot."""

from __future__ import annotations

import copy
from typing import Any, cast

from arcadia.hardware.errors import RuntimeResolutionError
from arcadia.hardware.models import DeviceKind, HardwareCapabilities
from arcadia.models import LlamaServiceSpec, ResolvedRuntimeSettings, SamServiceSpec, ServiceSpec, ServiceType

__all__ = ["resolve_runtime_settings"]


def _invalid(message: str, *, code: str = "runtime_settings_invalid", details: dict[str, Any] | None = None) -> None:
    raise RuntimeResolutionError(message, code=code, details=details)


def _device_request(value: Any) -> str:
    if not isinstance(value, str):
        _invalid("requested device must be a string")
    normalized = value.strip().lower()
    if normalized not in {"auto", "cpu", "cuda", "metal", "mps"}:
        _invalid("requested device must be auto, cpu, cuda, metal, or mps")
    return cast(str, normalized)


def _requested_index(value: Any) -> int:
    if type(value) is not int or value < 0:
        _invalid("requested device_index must be an integer greater than or equal to zero")
    return cast(int, value)


def _requested_threads(value: Any) -> int:
    if type(value) is not int or value < 1:
        _invalid("requested threads must be an integer greater than or equal to one")
    return cast(int, value)


def _backend_for(spec: LlamaServiceSpec | SamServiceSpec) -> str:
    if spec.service_type in (ServiceType.LLM, ServiceType.VISUAL_LLM):
        return "llama_cpp"
    return "sam3"


def resolve_runtime_settings(spec: ServiceSpec, hardware: HardwareCapabilities) -> ResolvedRuntimeSettings:
    """Resolve device-related settings without performing I/O or mutation."""

    if not isinstance(spec, (LlamaServiceSpec, SamServiceSpec)):
        _invalid("spec must be a public service specification")
    if not isinstance(hardware, HardwareCapabilities):
        _invalid("hardware must be a HardwareCapabilities snapshot")

    values = copy.deepcopy(spec.requested_settings.values)
    if "backend" in values:
        _invalid("backend is reserved by the service type", code="reserved_runtime_setting")
    if "threads" in values:
        _requested_threads(values["threads"])

    requested_device = _device_request(values.get("device", "auto"))
    notes: list[str] = []
    cuda_accelerators = tuple(item for item in hardware.accelerators if item.kind == DeviceKind.CUDA)
    metal_accelerators = tuple(item for item in hardware.accelerators if item.kind == DeviceKind.METAL)

    if requested_device == "auto":
        if cuda_accelerators:
            device = DeviceKind.CUDA
            notes.append(f"device auto-selected CUDA accelerator {cuda_accelerators[0].index}")
        elif metal_accelerators:
            device = DeviceKind.METAL
            notes.append(f"device auto-selected Metal accelerator {metal_accelerators[0].index}")
        else:
            device = DeviceKind.CPU
            notes.append("no supported accelerator detected; device auto-selected CPU")
    elif requested_device == "mps":
        device = DeviceKind.METAL
        notes.append("normalized requested device 'mps' to 'metal'")
    else:
        device = DeviceKind(requested_device)

    if device == DeviceKind.CUDA and not cuda_accelerators:
        _invalid(
            "requested CUDA device is unavailable", code="requested_device_unavailable", details={"device": "cuda"}
        )
    if device == DeviceKind.METAL and not metal_accelerators:
        _invalid(
            "requested Metal device is unavailable", code="requested_device_unavailable", details={"device": "metal"}
        )

    values["device"] = device.value
    if device == DeviceKind.CUDA:
        if "device_index" in values:
            index = _requested_index(values["device_index"])
            if not any(accelerator.index == index for accelerator in cuda_accelerators):
                _invalid(
                    "requested CUDA device index is unavailable",
                    code="requested_device_index_unavailable",
                    details={"device_index": index},
                )
        else:
            index = cuda_accelerators[0].index
        values["device_index"] = index
    elif "device_index" in values:
        _invalid("device_index is valid only for CUDA")

    return ResolvedRuntimeSettings(backend=_backend_for(spec), values=values, notes=tuple(notes))
