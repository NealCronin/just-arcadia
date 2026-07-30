"""Focused behavioral tests for the generic service lifecycle manager."""

from __future__ import annotations

import threading
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
    ServiceConflictError,
    ServiceEndpoint,
    ServiceError,
    ServiceHealthError,
    ServiceNotRunningError,
    ServiceSpec,
    ServiceState,
    ServiceType,
)
from arcadia.services import BackendInstance, BackendProgressReporter, ServiceManager


class FreePortInspector:
    def __init__(self, *, in_use: bool = False, failure: BaseException | None = None) -> None:
        self.in_use = in_use
        self.failure = failure
        self.ports: list[int] = []

    def is_in_use(self, port: int) -> bool:
        self.ports.append(port)
        if self.failure is not None:
            raise self.failure
        return self.in_use


class FakeBackend:
    backend_id = "llama_cpp"

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail_start = False
        self.fail_health = False
        self.fail_stop = False
        self.progress_state: ServiceState | None = None

    def start(
        self,
        spec: ServiceSpec,
        resolved_settings: ResolvedRuntimeSettings,
        progress: BackendProgressReporter,
    ) -> BackendInstance:
        filename = spec.model.filename if isinstance(spec, LlamaServiceSpec) else "sam"
        self.calls.append(f"start:{filename}")
        if self.progress_state is not None:
            progress.report(state=self.progress_state, progress=0.5, message="starting")
        if self.fail_start:
            raise RuntimeError("start failure")
        return BackendInstance(
            endpoint=ServiceEndpoint(host="127.0.0.1", port=spec.port, service_type=spec.service_type),
            resolved_settings=resolved_settings,
            handle={"secret": "opaque"},
        )

    def check_health(self, instance: BackendInstance) -> None:
        self.calls.append("health")
        if self.fail_health:
            raise RuntimeError("health failure")

    def stop(self, instance: BackendInstance, progress: BackendProgressReporter) -> None:
        self.calls.append("stop")
        if self.fail_stop:
            raise RuntimeError("stop failure")

    def diagnostics(self, instance: BackendInstance) -> dict[str, Any]:
        return {"pid": 123, "port": "backend cannot override manager port"}

    def read_logs(self, instance: BackendInstance, *, tail_lines: int) -> str:
        return "first\nsecond\nthird\n"


def hardware() -> HardwareCapabilities:
    return HardwareCapabilities(
        detected_at=datetime.now(UTC),
        platform=PlatformInfo(
            operating_system=OperatingSystem.MACOS,
            release="",
            version="",
            machine="arm64",
            python_version="3.11",
        ),
        cpu=CpuInfo(logical_cores=8, architecture="arm64"),
        memory=MemoryInfo(),
    )


def spec(port: int = 19001, filename: str = "model.gguf") -> LlamaServiceSpec:
    return LlamaServiceSpec(
        service_type=ServiceType.LLM,
        port=port,
        model=HuggingFaceFileSpec(repo_id="owner/model", filename=filename),
        requested_settings=RequestedRuntimeSettings(),
    )


def manager(
    backend: FakeBackend, inspector: FreePortInspector | None = None, sink: InMemoryEventSink | None = None
) -> ServiceManager:
    emitter = None if sink is None else EventEmitter([sink])
    return ServiceManager(
        hardware=hardware(),
        backends={ServiceType.LLM: backend},
        port_inspector=inspector or FreePortInspector(),
        event_emitter=emitter,
        register_atexit=False,
    )


def test_ensure_reuses_healthy_service_and_exposes_safe_snapshots() -> None:
    backend = FakeBackend()
    sink = InMemoryEventSink()
    service_manager = manager(backend, sink=sink)

    ready = service_manager.ensure_service(spec())
    reused = service_manager.ensure_service(spec())

    assert ready.state == ServiceState.READY
    assert reused.started_at == ready.started_at
    assert backend.calls == ["start:model.gguf", "health", "health"]
    assert service_manager.get_diagnostics(19001).details == {"pid": 123}
    assert service_manager.get_logs(19001, tail_lines=2).text == "second\nthird\n"
    assert all("secret" not in event.data for event in sink.snapshot())
    assert [operation.state.value for operation in service_manager.list_operations()] == ["succeeded", "succeeded"]


def test_replacement_stops_before_start_and_does_not_roll_back() -> None:
    backend = FakeBackend()
    service_manager = manager(backend)
    service_manager.ensure_service(spec(filename="first.gguf"))
    backend.fail_start = True

    with pytest.raises(ServiceError, match="startup") as raised:
        service_manager.ensure_service(spec(filename="second.gguf"))

    assert raised.value.code == "service_startup_failed"
    assert backend.calls == ["start:first.gguf", "health", "stop", "start:second.gguf"]
    status = service_manager.get_status(19001)
    assert status.state == ServiceState.FAILED
    assert status.endpoint is None
    assert status.requested_spec == spec(filename="second.gguf")


def test_conflicting_listener_and_probe_failure_fail_closed() -> None:
    backend = FakeBackend()
    occupied = manager(backend, FreePortInspector(in_use=True))
    with pytest.raises(ServiceConflictError) as conflict:
        occupied.ensure_service(spec())
    assert conflict.value.code == "service_port_in_use"
    assert backend.calls == []

    failing = manager(FakeBackend(), FreePortInspector(failure=RuntimeError("probe")))
    with pytest.raises(ServiceConflictError) as failed_probe:
        failing.ensure_service(spec())
    assert failed_probe.value.code == "service_port_probe_failed"


def test_health_stop_progress_and_shutdown_failure_semantics() -> None:
    backend = FakeBackend()
    service_manager = manager(backend)
    service_manager.ensure_service(spec())

    backend.fail_health = True
    with pytest.raises(ServiceHealthError) as health_failure:
        service_manager.check_health(19001)
    assert health_failure.value.code == "service_health_failed"
    assert service_manager.get_status(19001).endpoint is None

    backend.fail_health = False
    backend.fail_stop = True
    with pytest.raises(ServiceError) as stop_failure:
        service_manager.stop_service(19001)
    assert stop_failure.value.code == "service_stop_failed"
    assert service_manager.get_status(19001).state == ServiceState.FAILED

    with pytest.raises(ServiceError) as shutdown_failure:
        service_manager.shutdown()
    assert shutdown_failure.value.code == "service_shutdown_incomplete"
    assert service_manager.is_closed
    with pytest.raises(ServiceError, match="closed"):
        service_manager.ensure_service(spec())
    assert service_manager.get_status(19001).state == ServiceState.FAILED


def test_invalid_progress_fails_operation_without_handle_leakage() -> None:
    backend = FakeBackend()
    backend.progress_state = ServiceState.READY
    service_manager = manager(backend)

    with pytest.raises(ServiceError) as raised:
        service_manager.ensure_service(spec())

    assert raised.value.code == "service_progress_invalid"
    operation = service_manager.list_operations()[0]
    assert operation.error is not None
    assert operation.error.code == "service_progress_invalid"
    assert "secret" not in operation.model_dump_json()


def test_same_port_operations_serialize_while_different_ports_overlap() -> None:
    entered = threading.Event()
    release = threading.Event()

    class BlockingBackend(FakeBackend):
        def start(
            self,
            spec: ServiceSpec,
            resolved_settings: ResolvedRuntimeSettings,
            progress: BackendProgressReporter,
        ) -> BackendInstance:
            entered.set()
            release.wait(timeout=2)
            return super().start(spec, resolved_settings, progress)

    backend = BlockingBackend()
    service_manager = manager(backend)
    first = threading.Thread(target=lambda: service_manager.ensure_service(spec(19001)))
    second = threading.Thread(target=lambda: service_manager.ensure_service(spec(19001, "second.gguf")))
    first.start()
    assert entered.wait(timeout=1)
    second.start()
    release.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive() and not second.is_alive()
    assert service_manager.get_status(19001).requested_spec == spec(19001, "second.gguf")
    assert backend.calls == ["start:model.gguf", "health", "stop", "start:second.gguf", "health"]


def test_unknown_ports_and_stopped_stop_are_explicit() -> None:
    service_manager = manager(FakeBackend())
    with pytest.raises(ServiceNotRunningError) as unknown:
        service_manager.stop_service(19001)
    assert unknown.value.code == "service_not_managed"

    service_manager.ensure_service(spec())
    stopped = service_manager.stop_service(19001)
    again = service_manager.stop_service(19001)
    assert stopped.state == again.state == ServiceState.STOPPED
    assert len(service_manager.list_operations()) == 2
