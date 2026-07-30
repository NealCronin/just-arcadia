"""Reusable behavioral contract for ServiceBackend implementations."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from arcadia.hardware import (
    CpuInfo,
    HardwareCapabilities,
    MemoryInfo,
    OperatingSystem,
    PlatformInfo,
    resolve_runtime_settings,
)
from arcadia.models import (
    HuggingFaceFileSpec,
    LlamaServiceSpec,
    RequestedRuntimeSettings,
    ResolvedRuntimeSettings,
    ServiceEndpoint,
    ServiceSpec,
    ServiceState,
    ServiceType,
)
from arcadia.services import BackendInstance, BackendProgressReporter, ServiceBackend, ServiceManager


class FreeInspector:
    def is_in_use(self, port: int) -> bool:
        return False


class ContractBackend:
    backend_id = "llama_cpp"

    def __init__(self) -> None:
        self.stopped = False
        self.stop_calls = 0

    def start(
        self,
        spec: ServiceSpec,
        resolved_settings: ResolvedRuntimeSettings,
        progress: BackendProgressReporter,
    ) -> BackendInstance:
        progress.report(state=ServiceState.STARTING, progress=0.25, message="launching")
        return BackendInstance(
            endpoint=ServiceEndpoint(host="127.0.0.1", port=spec.port, service_type=spec.service_type),
            resolved_settings=resolved_settings,
            handle=object(),
        )

    def check_health(self, instance: BackendInstance) -> None:
        assert not self.stopped

    def stop(self, instance: BackendInstance, progress: BackendProgressReporter) -> None:
        self.stop_calls += 1
        self.stopped = True

    def diagnostics(self, instance: BackendInstance) -> dict[str, Any]:
        return {"pid": 42, "version": "test"}

    def read_logs(self, instance: BackendInstance, *, tail_lines: int) -> str:
        return "".join(["one\n", "two\n", "three\n"][-tail_lines:])


def _hardware() -> HardwareCapabilities:
    return HardwareCapabilities(
        detected_at=datetime.now(UTC),
        platform=PlatformInfo(
            operating_system=OperatingSystem.LINUX,
            release="",
            version="",
            machine="x86_64",
            python_version="3.11",
        ),
        cpu=CpuInfo(logical_cores=4, architecture="x86_64"),
        memory=MemoryInfo(),
    )


def _spec() -> LlamaServiceSpec:
    return LlamaServiceSpec(
        service_type=ServiceType.LLM,
        port=19002,
        model=HuggingFaceFileSpec(repo_id="owner/model", filename="model.gguf"),
        requested_settings=RequestedRuntimeSettings(),
    )


class ContractProgressReporter:
    def __init__(self, allowed_states: set[ServiceState]) -> None:
        self.allowed_states = allowed_states
        self.states: list[ServiceState] = []

    def report(
        self,
        *,
        state: ServiceState,
        progress: float | None = None,
        message: str = "",
    ) -> None:
        assert state in self.allowed_states
        self.states.append(state)


def assert_service_backend_contract(
    backend_factory: Callable[[], ServiceBackend],
    *,
    hardware: HardwareCapabilities,
    spec: ServiceSpec,
) -> None:
    """Exercise the reusable contract shared by fake and future real backends."""
    original = spec.model_dump_json()
    direct_backend = backend_factory()
    backend_id = direct_backend.backend_id
    assert backend_id and direct_backend.backend_id == backend_id
    resolved = resolve_runtime_settings(spec, hardware)
    start_progress = ContractProgressReporter({ServiceState.RESOLVING, ServiceState.DOWNLOADING, ServiceState.STARTING})
    instance = direct_backend.start(spec, resolved, start_progress)
    assert spec.model_dump_json() == original
    assert instance.endpoint.port == spec.port
    assert instance.endpoint.service_type == spec.service_type
    assert instance.resolved_settings.backend == resolved.backend
    direct_backend.check_health(instance)
    details = direct_backend.diagnostics(instance)
    assert isinstance(details, Mapping)
    json.dumps(dict(details), allow_nan=False)
    assert len(direct_backend.read_logs(instance, tail_lines=2).splitlines()) <= 2
    stop_progress = ContractProgressReporter({ServiceState.STOPPING})
    direct_backend.stop(instance, stop_progress)
    direct_backend.stop(instance, stop_progress)
    direct_backend.diagnostics(instance)
    direct_backend.read_logs(instance, tail_lines=2)

    backend = backend_factory()
    assert isinstance(backend, ServiceBackend)
    service_manager = ServiceManager(
        hardware=hardware,
        backends={spec.service_type: backend},
        port_inspector=FreeInspector(),
        register_atexit=False,
    )
    assert spec.model_dump_json() == original

    ready = service_manager.ensure_service(spec)
    diagnostics = service_manager.get_diagnostics(spec.port)
    logs = service_manager.get_logs(spec.port, tail_lines=2)

    assert spec.model_dump_json() == original
    assert ready.endpoint is not None and ready.endpoint.port == spec.port
    assert ready.resolved_settings is not None and ready.resolved_settings.backend == backend.backend_id
    assert len(logs.text.splitlines()) <= 2
    assert diagnostics.model_validate_json(diagnostics.model_dump_json()) == diagnostics
    assert logs.model_validate_json(logs.model_dump_json()) == logs
    assert "handle" not in ready.model_dump_json()
    assert service_manager.stop_service(spec.port).state == ServiceState.STOPPED
    assert service_manager.stop_service(spec.port).state == ServiceState.STOPPED


def test_fake_backend_satisfies_reusable_contract() -> None:
    assert_service_backend_contract(ContractBackend, hardware=_hardware(), spec=_spec())
