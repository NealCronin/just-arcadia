"""Regression and concurrency coverage for service lifecycle safety."""

from __future__ import annotations

import gc
import threading
import weakref
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
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
    SamServiceSpec,
    ServiceEndpoint,
    ServiceError,
    ServiceNotRunningError,
    ServiceSpec,
    ServiceStartupError,
    ServiceState,
    ServiceType,
)
from arcadia.services import BackendInstance, BackendProgressReporter, ServiceBackend, ServiceManager


class FreePortInspector:
    def is_in_use(self, port: int) -> bool:
        return False


def hardware() -> HardwareCapabilities:
    return HardwareCapabilities(
        detected_at=datetime.now(UTC),
        platform=PlatformInfo(
            operating_system=OperatingSystem.LINUX,
            release="",
            version="",
            machine="x86_64",
            python_version="3.11",
        ),
        cpu=CpuInfo(logical_cores=8, architecture="x86_64"),
        memory=MemoryInfo(),
    )


def spec(port: int, filename: str = "model.gguf") -> LlamaServiceSpec:
    return LlamaServiceSpec(
        service_type=ServiceType.LLM,
        port=port,
        model=HuggingFaceFileSpec(repo_id="owner/model", filename=filename),
        requested_settings=RequestedRuntimeSettings(),
    )


class RecordingBackend:
    def __init__(
        self,
        backend_id: str,
        *,
        start_hook: Callable[[ServiceSpec], None] | None = None,
        stop_hook: Callable[[BackendInstance], None] | None = None,
    ) -> None:
        self._backend_id = backend_id
        self.start_hook = start_hook
        self.stop_hook = stop_hook
        self.started: list[BackendInstance] = []
        self.stopped: list[BackendInstance] = []
        self.health_error: BaseException | None = None
        self.start_error: BaseException | None = None
        self.diagnostics_error: BaseException | None = None
        self.logs_error: BaseException | None = None

    @property
    def backend_id(self) -> str:
        return self._backend_id

    def start(
        self,
        spec: ServiceSpec,
        resolved_settings: ResolvedRuntimeSettings,
        progress: BackendProgressReporter,
    ) -> BackendInstance:
        if self.start_hook is not None:
            self.start_hook(spec)
        if self.start_error is not None:
            raise self.start_error
        instance = BackendInstance(
            endpoint=ServiceEndpoint(
                host="127.0.0.1",
                port=spec.port,
                service_type=spec.service_type,
            ),
            resolved_settings=resolved_settings,
            handle={"port": spec.port, "generation": len(self.started)},
        )
        self.started.append(instance)
        return instance

    def check_health(self, instance: BackendInstance) -> None:
        if self.health_error is not None:
            raise self.health_error

    def stop(self, instance: BackendInstance, progress: BackendProgressReporter) -> None:
        self.stopped.append(instance)
        if self.stop_hook is not None:
            self.stop_hook(instance)

    def diagnostics(self, instance: BackendInstance) -> dict[str, Any]:
        if self.diagnostics_error is not None:
            raise self.diagnostics_error
        handle = instance.handle
        assert isinstance(handle, dict)
        return {"generation": handle["generation"]}

    def read_logs(self, instance: BackendInstance, *, tail_lines: int) -> str:
        if self.logs_error is not None:
            raise self.logs_error
        handle = instance.handle
        assert isinstance(handle, dict)
        return f"generation-{handle['generation']}\n"


def make_manager(
    backends: dict[ServiceType, ServiceBackend],
    *,
    emitter: EventEmitter | None = None,
    operation_id_factory: Callable[[], str] | None = None,
    register_atexit: bool = False,
) -> ServiceManager:
    return ServiceManager(
        hardware=hardware(),
        backends=backends,
        event_emitter=emitter,
        port_inspector=FreePortInspector(),
        operation_id_factory=operation_id_factory,
        register_atexit=register_atexit,
    )


def test_different_ports_start_concurrently() -> None:
    both_entered = threading.Event()
    release = threading.Event()
    counter_lock = threading.Lock()
    active = 0
    maximum_active = 0

    def block_start(requested_spec: ServiceSpec) -> None:
        nonlocal active, maximum_active
        with counter_lock:
            active += 1
            maximum_active = max(maximum_active, active)
            if active == 2:
                both_entered.set()
        assert both_entered.wait(timeout=2)
        assert release.wait(timeout=2)
        with counter_lock:
            active -= 1

    backend = RecordingBackend("llama_cpp", start_hook=block_start)
    service_manager = make_manager({ServiceType.LLM: backend})
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(service_manager.ensure_service, spec(19010))
        second = executor.submit(service_manager.ensure_service, spec(19011))
        assert both_entered.wait(timeout=2)
        release.set()
        assert first.result(timeout=2).state == ServiceState.READY
        assert second.result(timeout=2).state == ServiceState.READY

    assert maximum_active == 2


def test_replacement_changes_service_type_and_backend() -> None:
    llama = RecordingBackend("llama_cpp")
    sam = RecordingBackend("sam3")
    service_manager = make_manager({ServiceType.LLM: llama, ServiceType.SAM3: sam})
    service_manager.ensure_service(spec(19012))
    sam_spec = SamServiceSpec(
        port=19012,
        checkpoint_path="checkpoint.pt",
        requested_settings=RequestedRuntimeSettings(),
    )

    replaced = service_manager.ensure_service(sam_spec)

    assert replaced.service_type == ServiceType.SAM3
    assert replaced.requested_spec == sam_spec
    assert replaced.resolved_settings is not None and replaced.resolved_settings.backend == "sam3"
    assert len(llama.stopped) == 1
    assert len(sam.started) == 1


def test_operation_and_progress_events_use_target_backend_identity() -> None:
    class ReportingBackend(RecordingBackend):
        def start(
            self,
            spec: ServiceSpec,
            resolved_settings: ResolvedRuntimeSettings,
            progress: BackendProgressReporter,
        ) -> BackendInstance:
            progress.report(state=ServiceState.STARTING, message="starting")
            return super().start(spec, resolved_settings, progress)

    sink = InMemoryEventSink()
    llama = ReportingBackend("llama_cpp")
    sam = ReportingBackend("sam3")
    service_manager = make_manager(
        {ServiceType.LLM: llama, ServiceType.SAM3: sam},
        emitter=EventEmitter([sink]),
    )
    service_manager.ensure_service(spec(19026))
    service_manager.ensure_service(SamServiceSpec(port=19026, checkpoint_path="checkpoint.pt"))

    started = [event for event in sink.snapshot() if event.kind == "service.operation.started"]
    progress_events = [event for event in sink.snapshot() if event.kind == "service.operation.progress"]
    assert [event.data["backend_id"] for event in started] == ["llama_cpp", "sam3"]
    assert [event.data["service_type"] for event in started] == ["llm", "sam3"]
    assert [event.data["backend_id"] for event in progress_events] == ["llama_cpp", "sam3"]


def test_failed_cross_backend_replacement_keeps_retained_instance_identity() -> None:
    llama = RecordingBackend("llama_cpp")
    sam = RecordingBackend("sam3")
    sam.start_error = RuntimeError("SAM start failed")
    service_manager = make_manager({ServiceType.LLM: llama, ServiceType.SAM3: sam})
    service_manager.ensure_service(spec(19027))
    sam_spec = SamServiceSpec(port=19027, checkpoint_path="checkpoint.pt")

    with pytest.raises(ServiceStartupError):
        service_manager.ensure_service(sam_spec)

    status = service_manager.get_status(19027)
    diagnostics = service_manager.get_diagnostics(19027)
    logs = service_manager.get_logs(19027)
    assert status.service_type == ServiceType.SAM3
    assert diagnostics.service_type == ServiceType.LLM
    assert diagnostics.backend_id == "llama_cpp"
    assert logs.service_type == ServiceType.LLM
    assert logs.backend_id == "llama_cpp"
    assert logs.text == "generation-0\n"


def test_invalid_returned_instance_is_stopped_before_rejection() -> None:
    class InvalidBackend(RecordingBackend):
        def start(
            self,
            spec: ServiceSpec,
            resolved_settings: ResolvedRuntimeSettings,
            progress: BackendProgressReporter,
        ) -> BackendInstance:
            instance = BackendInstance(
                endpoint=ServiceEndpoint(
                    host="127.0.0.1",
                    port=spec.port + 1,
                    service_type=spec.service_type,
                ),
                resolved_settings=resolved_settings,
                handle={"launched": True},
            )
            self.started.append(instance)
            return instance

    backend = InvalidBackend("llama_cpp")
    service_manager = make_manager({ServiceType.LLM: backend})

    with pytest.raises(ServiceStartupError) as raised:
        service_manager.ensure_service(spec(19013))

    assert raised.value.code == "service_backend_contract_invalid"
    assert backend.stopped == backend.started
    assert service_manager.get_status(19013).state == ServiceState.FAILED
    with pytest.raises(ServiceNotRunningError) as logs_unavailable:
        service_manager.get_logs(19013)
    assert logs_unavailable.value.code == "service_logs_unavailable"


def test_invalid_instance_cleanup_failure_is_retained_for_shutdown() -> None:
    stop_attempts = 0

    def fail_stop(instance: BackendInstance) -> None:
        nonlocal stop_attempts
        stop_attempts += 1
        raise ServiceError("cannot stop", code="backend_stop_failed", details={"port": instance.endpoint.port - 1})

    class InvalidBackend(RecordingBackend):
        def start(
            self,
            spec: ServiceSpec,
            resolved_settings: ResolvedRuntimeSettings,
            progress: BackendProgressReporter,
        ) -> BackendInstance:
            return BackendInstance(
                endpoint=ServiceEndpoint(
                    host="127.0.0.1",
                    port=spec.port + 1,
                    service_type=spec.service_type,
                ),
                resolved_settings=resolved_settings,
                handle=object(),
            )

    backend = InvalidBackend("llama_cpp", stop_hook=fail_stop)
    service_manager = make_manager({ServiceType.LLM: backend})
    with pytest.raises(ServiceStartupError) as raised:
        service_manager.ensure_service(spec(19014))
    assert raised.value.details["cleanup_error_code"] == "backend_stop_failed"

    with pytest.raises(ServiceError) as shutdown_error:
        service_manager.shutdown()
    assert shutdown_error.value.code == "service_shutdown_incomplete"
    assert stop_attempts == 2


def test_backend_service_error_is_preserved() -> None:
    backend = RecordingBackend("llama_cpp")
    expected = ServiceError("backend refused start", code="backend_refused", details={"safe": True})
    backend.start_error = expected
    service_manager = make_manager({ServiceType.LLM: backend})

    with pytest.raises(ServiceError) as raised:
        service_manager.ensure_service(spec(19015))

    assert raised.value is expected
    status = service_manager.get_status(19015)
    operation = service_manager.list_operations()[0]
    assert status.error is not None and status.error.code == "backend_refused"
    assert operation.error is not None and operation.error.code == "backend_refused"


def test_shutdown_continues_then_retries_only_failed_ports() -> None:
    stop_order: list[int] = []
    failed_once = False

    def record_stop(instance: BackendInstance) -> None:
        nonlocal failed_once
        stop_order.append(instance.endpoint.port)
        if instance.endpoint.port == 19017 and not failed_once:
            failed_once = True
            raise ServiceError("stop failed", code="chosen_stop_failure", details={"port": 19017})

    backend = RecordingBackend("llama_cpp", stop_hook=record_stop)
    service_manager = make_manager({ServiceType.LLM: backend})
    for port in (19018, 19016, 19017):
        service_manager.ensure_service(spec(port))

    with pytest.raises(ServiceError) as raised:
        service_manager.shutdown()

    assert raised.value.code == "service_shutdown_incomplete"
    assert raised.value.details["failed_ports"] == [19017]
    assert stop_order == [19016, 19017, 19018]
    with pytest.raises(ServiceError) as closed:
        service_manager.stop_service(19017)
    assert closed.value.code == "service_manager_closed"

    statuses = service_manager.shutdown()
    assert [status.port for status in statuses] == [19016, 19017, 19018]
    assert stop_order == [19016, 19017, 19018, 19017]
    assert service_manager.shutdown() == statuses
    assert stop_order == [19016, 19017, 19018, 19017]


def test_operation_ids_are_trimmed_for_lookup_and_duplicate_detection() -> None:
    ids = iter((" operation-1 ", "operation-1"))
    backend = RecordingBackend("llama_cpp")
    service_manager = make_manager(
        {ServiceType.LLM: backend},
        operation_id_factory=lambda: next(ids),
    )
    ready = service_manager.ensure_service(spec(19019))

    assert ready.operation_id == "operation-1"
    assert service_manager.get_operation("operation-1").operation_id == "operation-1"
    assert service_manager.get_operation(" operation-1 ").operation_id == "operation-1"
    with pytest.raises(ServiceError) as duplicate:
        service_manager.ensure_service(spec(19019))
    assert duplicate.value.code == "service_operation_invalid"
    assert len(service_manager.list_operations()) == 1


def test_diagnostics_and_logs_remain_readable_during_replacement() -> None:
    replacement_entered = threading.Event()
    release = threading.Event()
    starts = 0

    def block_second_start(requested_spec: ServiceSpec) -> None:
        nonlocal starts
        starts += 1
        if starts == 2:
            replacement_entered.set()
            assert release.wait(timeout=2)

    backend = RecordingBackend("llama_cpp", start_hook=block_second_start)
    service_manager = make_manager({ServiceType.LLM: backend})
    service_manager.ensure_service(spec(19020, "first.gguf"))

    with ThreadPoolExecutor(max_workers=1) as executor:
        replacement = executor.submit(service_manager.ensure_service, spec(19020, "second.gguf"))
        assert replacement_entered.wait(timeout=2)
        assert service_manager.get_diagnostics(19020).details == {"generation": 0}
        assert service_manager.get_logs(19020).text == "generation-0\n"
        release.set()
        assert replacement.result(timeout=2).state == ServiceState.READY

    assert service_manager.get_diagnostics(19020).details == {"generation": 1}
    assert service_manager.get_logs(19020).text == "generation-1\n"


def test_context_manager_preserves_active_exception_when_cleanup_fails() -> None:
    class ActiveError(RuntimeError):
        pass

    def fail_stop(instance: BackendInstance) -> None:
        raise ServiceError("cleanup failed", code="cleanup_failed", details={"port": instance.endpoint.port})

    backend = RecordingBackend("llama_cpp", stop_hook=fail_stop)
    service_manager = make_manager({ServiceType.LLM: backend})

    with pytest.raises(ActiveError, match="active"):
        with service_manager:
            service_manager.ensure_service(spec(19021))
            raise ActiveError("active")

    assert service_manager.is_closed


def test_event_callback_lifecycle_reentrancy_is_rejected() -> None:
    reentrant_errors: list[ServiceError] = []
    service_manager: ServiceManager

    class ReentrantSink:
        def emit(self, event: Any) -> None:
            if event.kind == "service.operation.started":
                try:
                    service_manager.stop_service(19022)
                except ServiceError as exc:
                    reentrant_errors.append(exc)

    backend = RecordingBackend("llama_cpp")
    service_manager = make_manager(
        {ServiceType.LLM: backend},
        emitter=EventEmitter([ReentrantSink()]),
    )

    assert service_manager.ensure_service(spec(19022)).state == ServiceState.READY
    assert [error.code for error in reentrant_errors] == ["service_lifecycle_reentrant"]
    assert len(service_manager.list_operations()) == 1


def test_event_sink_failure_does_not_change_lifecycle_outcome() -> None:
    class FailingSink:
        def emit(self, event: Any) -> None:
            raise RuntimeError("sink failed")

    backend = RecordingBackend("llama_cpp")
    service_manager = make_manager(
        {ServiceType.LLM: backend},
        emitter=EventEmitter([FailingSink()]),
    )

    assert service_manager.ensure_service(spec(19023)).state == ServiceState.READY


def test_atexit_callback_is_weak_and_unregistered(monkeypatch: pytest.MonkeyPatch) -> None:
    callbacks: list[Callable[[], None]] = []
    unregistered: list[Callable[[], None]] = []
    monkeypatch.setattr("arcadia.services.manager.atexit.register", callbacks.append)
    monkeypatch.setattr("arcadia.services.manager.atexit.unregister", unregistered.append)
    backend = RecordingBackend("llama_cpp")
    service_manager = make_manager({ServiceType.LLM: backend}, register_atexit=True)
    callback = callbacks[0]
    manager_ref = weakref.ref(service_manager)

    service_manager.shutdown()

    assert unregistered == [callback]
    del service_manager
    gc.collect()
    assert manager_ref() is None
    callback()


def test_atexit_callback_retries_incomplete_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    callbacks: list[Callable[[], None]] = []
    unregistered: list[Callable[[], None]] = []
    monkeypatch.setattr("arcadia.services.manager.atexit.register", callbacks.append)
    monkeypatch.setattr("arcadia.services.manager.atexit.unregister", unregistered.append)
    stop_attempts = 0

    def transient_stop(instance: BackendInstance) -> None:
        nonlocal stop_attempts
        stop_attempts += 1
        if stop_attempts == 1:
            raise ServiceError(
                "transient stop failure", code="transient_stop", details={"port": instance.endpoint.port}
            )

    backend = RecordingBackend("llama_cpp", stop_hook=transient_stop)
    service_manager = make_manager({ServiceType.LLM: backend}, register_atexit=True)
    service_manager.ensure_service(spec(19028))
    callback = callbacks[0]

    with pytest.raises(ServiceError) as incomplete:
        service_manager.shutdown()
    assert incomplete.value.code == "service_shutdown_incomplete"
    assert unregistered == []

    callback()

    assert stop_attempts == 2
    assert service_manager.get_status(19028).state == ServiceState.STOPPED
    assert unregistered == [callback]


def test_keyboard_interrupt_escapes_backend_boundaries() -> None:
    starting = RecordingBackend("llama_cpp")
    starting.start_error = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        make_manager({ServiceType.LLM: starting}).ensure_service(spec(19029))

    checking = RecordingBackend("llama_cpp")
    checking_manager = make_manager({ServiceType.LLM: checking})
    checking_manager.ensure_service(spec(19030))
    checking.health_error = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        checking_manager.check_health(19030)

    def interrupt_stop(instance: BackendInstance) -> None:
        raise KeyboardInterrupt

    stopping = RecordingBackend("llama_cpp", stop_hook=interrupt_stop)
    stopping_manager = make_manager({ServiceType.LLM: stopping})
    stopping_manager.ensure_service(spec(19031))
    with pytest.raises(KeyboardInterrupt):
        stopping_manager.stop_service(19031)


def test_operation_filtering_diagnostic_failures_and_stopped_logs() -> None:
    backend = RecordingBackend("llama_cpp")
    service_manager = make_manager({ServiceType.LLM: backend})
    for port in (19024, 19025):
        service_manager.ensure_service(spec(port))
    service_manager.stop_service(19024)

    assert len(service_manager.list_operations()) == 3
    assert [operation.port for operation in service_manager.list_operations(19024)] == [19024, 19024]
    assert service_manager.get_logs(19024).text == "generation-0\n"

    backend.diagnostics_error = RuntimeError("diagnostics failed")
    with pytest.raises(ServiceError) as diagnostics_error:
        service_manager.get_diagnostics(19025)
    assert diagnostics_error.value.code == "service_diagnostics_failed"

    expected_logs_error = ServiceError("logs failed", code="backend_logs_failed")
    backend.logs_error = expected_logs_error
    with pytest.raises(ServiceError) as logs_error:
        service_manager.get_logs(19025)
    assert logs_error.value is expected_logs_error
