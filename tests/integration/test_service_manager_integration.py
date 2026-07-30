"""Integration coverage across hardware resolution, events, and service management."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from arcadia.events import EventEmitter, InMemoryEventSink
from arcadia.hardware import CpuInfo, HardwareCapabilities, MemoryInfo, OperatingSystem, PlatformInfo
from arcadia.models import (
    HuggingFaceFileSpec,
    LlamaServiceSpec,
    RequestedRuntimeSettings,
    ResolvedRuntimeSettings,
    ServiceEndpoint,
    ServiceError,
    ServiceSpec,
    ServiceState,
    ServiceType,
)
from arcadia.services import BackendInstance, BackendProgressReporter, ServiceManager


class FreeInspector:
    def is_in_use(self, port: int) -> bool:
        return False


class IntegrationBackend:
    backend_id = "llama_cpp"

    def __init__(self) -> None:
        self.unhealthy = False
        self.starts = 0
        self.stops = 0

    def start(
        self,
        spec: ServiceSpec,
        resolved_settings: ResolvedRuntimeSettings,
        progress: BackendProgressReporter,
    ) -> BackendInstance:
        self.starts += 1
        return BackendInstance(
            endpoint=ServiceEndpoint(host="127.0.0.1", port=spec.port, service_type=spec.service_type),
            resolved_settings=resolved_settings,
            handle=object(),
        )

    def check_health(self, instance: BackendInstance) -> None:
        if self.unhealthy:
            raise RuntimeError("unhealthy")

    def stop(self, instance: BackendInstance, progress: BackendProgressReporter) -> None:
        self.stops += 1

    def diagnostics(self, instance: BackendInstance) -> dict[str, Any]:
        return {"pid": 7}

    def read_logs(self, instance: BackendInstance, *, tail_lines: int) -> str:
        return "a\nb\n"


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


def _spec(filename: str) -> LlamaServiceSpec:
    return LlamaServiceSpec(
        service_type=ServiceType.LLM,
        port=19003,
        model=HuggingFaceFileSpec(repo_id="owner/model", filename=filename),
        requested_settings=RequestedRuntimeSettings(),
    )


def test_manager_integrates_runtime_resolution_events_and_serialization() -> None:
    backend = IntegrationBackend()
    sink = InMemoryEventSink()
    service_manager = ServiceManager(
        hardware=_hardware(),
        backends={ServiceType.LLM: backend},
        event_emitter=EventEmitter([sink]),
        port_inspector=FreeInspector(),
        register_atexit=False,
    )

    initial = service_manager.ensure_service(_spec("first.gguf"))
    reused = service_manager.ensure_service(_spec("first.gguf"))
    replacement = service_manager.ensure_service(_spec("second.gguf"))
    diagnostics = service_manager.get_diagnostics(19003)
    logs = service_manager.get_logs(19003)

    assert initial.resolved_settings is not None
    assert initial.resolved_settings.values["device"] == "cpu"
    assert reused.started_at == initial.started_at
    assert replacement.requested_spec == _spec("second.gguf")
    assert backend.starts == 2 and backend.stops == 1
    assert diagnostics.model_validate_json(diagnostics.model_dump_json()) == diagnostics
    assert logs.model_validate_json(logs.model_dump_json()) == logs
    assert all("handle" not in event.model_dump_json() for event in sink.snapshot())

    backend.unhealthy = True
    with pytest.raises(ServiceError, match="health"):
        service_manager.check_health(19003)
    assert service_manager.get_status(19003).state == ServiceState.FAILED
    assert service_manager.stop_service(19003).state == ServiceState.STOPPED
    assert service_manager.shutdown()[0].state == ServiceState.STOPPED
