"""Reusable behavioral contract for ServiceBackend implementations."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from arcadia.hardware import CpuInfo, HardwareCapabilities, MemoryInfo, OperatingSystem, PlatformInfo
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
        self.stopped = True

    def diagnostics(self, instance: BackendInstance) -> dict[str, Any]:
        return {"pid": 42, "version": "test"}

    def read_logs(self, instance: BackendInstance, *, tail_lines: int) -> str:
        return "one\ntwo\nthree\n"


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


def assert_service_backend_contract(
    backend_factory: Callable[[], ServiceBackend],
    *,
    hardware: HardwareCapabilities,
    spec: ServiceSpec,
) -> None:
    """Exercise the reusable contract shared by fake and future real backends."""

    backend = backend_factory()
    assert isinstance(backend, ServiceBackend)
    service_manager = ServiceManager(
        hardware=hardware,
        backends={spec.service_type: backend},
        port_inspector=FreeInspector(),
        register_atexit=False,
    )
    original = spec.model_dump_json()

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
