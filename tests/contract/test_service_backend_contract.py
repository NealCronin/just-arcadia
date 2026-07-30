"""Reusable behavioral contract for ServiceBackend implementations."""

from __future__ import annotations

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


def test_backend_contract_through_manager() -> None:
    backend = ContractBackend()
    assert isinstance(backend, ServiceBackend)
    service_manager = ServiceManager(
        hardware=_hardware(),
        backends={ServiceType.LLM: backend},
        port_inspector=FreeInspector(),
        register_atexit=False,
    )
    requested = _spec()
    original = requested.model_dump_json()

    ready = service_manager.ensure_service(requested)
    diagnostics = service_manager.get_diagnostics(requested.port)
    logs = service_manager.get_logs(requested.port, tail_lines=2)

    assert requested.model_dump_json() == original
    assert ready.endpoint is not None and ready.endpoint.port == requested.port
    assert ready.resolved_settings is not None and ready.resolved_settings.backend == backend.backend_id
    assert diagnostics.details == {"pid": 42, "version": "test"}
    assert logs.text == "two\nthree\n"
    assert "handle" not in ready.model_dump_json()
    assert service_manager.stop_service(requested.port).state == ServiceState.STOPPED
