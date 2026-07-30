"""Synchronous, thread-safe lifecycle management for backend-owned services."""

from __future__ import annotations

import atexit
import copy
import math
import threading
import uuid
import weakref
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from arcadia.events import ArcadiaEvent, EventEmitter, EventLevel
from arcadia.hardware import HardwareCapabilities, resolve_runtime_settings
from arcadia.models import (
    ArcadiaErrorInfo,
    OperationState,
    OperationStatus,
    ResolvedRuntimeSettings,
    ServiceConflictError,
    ServiceEndpoint,
    ServiceError,
    ServiceHealthError,
    ServiceNotRunningError,
    ServiceSpec,
    ServiceStartupError,
    ServiceState,
    ServiceStatus,
    ServiceType,
)
from arcadia.models.common import _normalize_datetime, _validate_port
from arcadia.services.backend import PortInspector, ServiceBackend, TcpPortInspector
from arcadia.services.models import BackendInstance, ServiceDiagnostics, ServiceLogSnapshot

__all__ = ["ServiceManager"]

_SOURCE = "arcadia.services.ServiceManager"
_START_PROGRESS_STATES = frozenset({ServiceState.RESOLVING, ServiceState.DOWNLOADING, ServiceState.STARTING})
_STOP_PROGRESS_STATES = frozenset({ServiceState.STOPPING})
_RESERVED_DIAGNOSTIC_KEYS = frozenset({"port", "service_type", "state", "backend_id"})


@dataclass(slots=True)
class _Slot:
    port: int
    service_type: ServiceType
    target_backend_id: str | None
    state: ServiceState
    requested_spec: ServiceSpec | None
    resolved_settings: ResolvedRuntimeSettings | None
    backend: ServiceBackend | None
    backend_id: str | None
    instance_service_type: ServiceType | None
    instance: BackendInstance | None
    endpoint: ServiceEndpoint | None
    error: ArcadiaErrorInfo | None
    started_at: datetime | None
    updated_at: datetime
    operation_id: str | None = None
    lifecycle_lock: threading.RLock = field(default_factory=threading.RLock)


class _ProgressReporter:
    """Validates and records progress reported during one backend call."""

    def __init__(
        self,
        manager: ServiceManager,
        slot: _Slot,
        operation_id: str,
        allowed_states: frozenset[ServiceState],
        *,
        service_type: ServiceType,
        backend_id: str,
    ) -> None:
        self._manager = manager
        self._slot = slot
        self._operation_id = operation_id
        self._allowed_states = allowed_states
        self._service_type = service_type
        self._backend_id = backend_id

    def report(self, *, state: ServiceState, progress: float | None = None, message: str = "") -> None:
        if state not in self._allowed_states:
            raise ServiceError(
                "backend reported an invalid lifecycle progress state",
                code="service_progress_invalid",
                details={"port": self._slot.port, "state": getattr(state, "value", str(state))},
            )
        if progress is not None:
            if isinstance(progress, bool) or not isinstance(progress, (int, float)):
                raise ServiceError("backend progress must be numeric", code="service_progress_invalid")
            if not math.isfinite(float(progress)) or not 0.0 <= float(progress) <= 1.0:
                raise ServiceError(
                    "backend progress must be finite and between 0.0 and 1.0", code="service_progress_invalid"
                )
        if not isinstance(message, str) or len(message) > 512 or any(ord(char) < 32 for char in message):
            raise ServiceError("backend progress message is invalid", code="service_progress_invalid")
        self._manager._transition(
            self._slot,
            state=state,
            operation_id=self._operation_id,
            event_service_type=self._service_type,
            event_backend_id=self._backend_id,
            progress=None if progress is None else float(progress),
            message=message.strip(),
        )
        self._manager._emit(
            "service.operation.progress",
            EventLevel.DEBUG,
            "service operation progress reported",
            operation_id=self._operation_id,
            data={
                "port": self._slot.port,
                "service_type": self._service_type.value,
                "backend_id": self._backend_id,
                "state": state.value,
                "progress": progress,
            },
        )


class ServiceManager:
    """Own in-memory service slots and delegate backend-specific lifecycle work."""

    def __init__(
        self,
        *,
        hardware: HardwareCapabilities,
        backends: Mapping[ServiceType, ServiceBackend],
        event_emitter: EventEmitter | None = None,
        port_inspector: PortInspector | None = None,
        clock: Callable[[], datetime] | None = None,
        operation_id_factory: Callable[[], str] | None = None,
        register_atexit: bool = True,
    ) -> None:
        if not isinstance(hardware, HardwareCapabilities):
            raise ValueError("hardware must be a HardwareCapabilities snapshot")
        if not isinstance(backends, Mapping):
            raise ValueError("backends must be a mapping")
        detached_backends: dict[ServiceType, ServiceBackend] = {}
        for service_type, backend in backends.items():
            if not isinstance(service_type, ServiceType):
                raise ValueError("backend keys must be ServiceType values")
            if not isinstance(backend, ServiceBackend):
                raise ValueError("backend values must implement ServiceBackend")
            backend_id = self._backend_id(backend)
            if not backend_id:
                raise ValueError("backend_id must be a non-empty string")
            detached_backends[service_type] = backend
        if event_emitter is not None and not isinstance(event_emitter, EventEmitter):
            raise ValueError("event_emitter must be an EventEmitter")
        if port_inspector is not None and not isinstance(port_inspector, PortInspector):
            raise ValueError("port_inspector must implement PortInspector")
        if clock is not None and not callable(clock):
            raise ValueError("clock must be callable")
        if operation_id_factory is not None and not callable(operation_id_factory):
            raise ValueError("operation_id_factory must be callable")

        self._hardware = HardwareCapabilities.model_validate(hardware.model_dump())
        self._backends = detached_backends
        self._event_emitter = event_emitter or EventEmitter()
        self._port_inspector = port_inspector or TcpPortInspector()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._operation_id_factory = operation_id_factory or (lambda: str(uuid.uuid4()))
        self._registry_lock = threading.RLock()
        self._shutdown_lock = threading.Lock()
        self._lifecycle_local = threading.local()
        self._slots: dict[int, _Slot] = {}
        self._operations: list[OperationStatus] = []
        self._operation_by_id: dict[str, OperationStatus] = {}
        self._operation_identities: dict[str, tuple[ServiceType, str]] = {}
        self._closing = False
        self._closed = False
        self._cleanup_complete = False
        self._atexit_callback: Callable[[], None] | None = None
        if register_atexit:
            manager_ref = weakref.ref(self)

            def cleanup() -> None:
                manager = manager_ref()
                if manager is not None:
                    try:
                        manager.shutdown()
                    except BaseException:
                        pass

            self._atexit_callback = cleanup
            atexit.register(cleanup)

    @staticmethod
    def _backend_id(backend: ServiceBackend) -> str:
        try:
            backend_id = backend.backend_id
        except Exception as exc:
            raise ValueError("backend_id could not be read") from exc
        if not isinstance(backend_id, str):
            return ""
        return backend_id.strip()

    @property
    def hardware(self) -> HardwareCapabilities:
        """Return a detached immutable hardware capability snapshot."""

        return HardwareCapabilities.model_validate(self._hardware.model_dump())

    @property
    def is_closed(self) -> bool:
        """Return whether shutdown has permanently closed lifecycle operations."""

        with self._registry_lock:
            return self._closed

    def ensure_service(self, spec: ServiceSpec) -> ServiceStatus:
        """Ensure a healthy service matching ``spec`` exists on its requested port."""

        with self._lifecycle_call():
            return self._ensure_service(spec)

    def _ensure_service(self, spec: ServiceSpec) -> ServiceStatus:
        requested = self._copy_spec(spec)
        self._assert_lifecycle_open()
        slot = self._get_or_create_slot(requested)
        with slot.lifecycle_lock:
            self._assert_lifecycle_open()
            if slot.state == ServiceState.READY and slot.requested_spec == requested:
                return self._reuse_locked(slot)
            target_backend = self._backends.get(requested.service_type)
            target_backend_id = "" if target_backend is None else self._backend_id(target_backend)
            with self._registry_lock:
                slot.target_backend_id = target_backend_id or None
            operation_id = self._start_operation(
                slot,
                service_type=requested.service_type,
                backend_id=target_backend_id,
            )
            self._emit_operation_started(slot, operation_id)
            if target_backend is None:
                missing_backend_error = ServiceStartupError(
                    "no backend is configured for service type",
                    code="service_backend_unavailable",
                    details={"port": requested.port, "service_type": requested.service_type.value},
                )
                if slot.instance is None or slot.state == ServiceState.STOPPED:
                    self._record_failure(slot, missing_backend_error, operation_id, requested_spec=requested)
                self._finish_operation(slot, operation_id, error=missing_backend_error)
                raise missing_backend_error
            if slot.instance is not None and slot.state != ServiceState.STOPPED:
                try:
                    self._stop_for_replacement_locked(slot, operation_id)
                except Exception as exc:
                    error = self._as_stop_error(exc, slot)
                    self._record_failure(slot, error, operation_id)
                    self._finish_operation(slot, operation_id, error=error)
                    raise error from exc
            try:
                return self._provision_locked(
                    slot,
                    requested,
                    target_backend,
                    target_backend_id,
                    operation_id,
                )
            except Exception as exc:
                error = self._as_start_error(exc, slot, requested)
                self._record_failure(slot, error, operation_id, requested_spec=requested)
                self._finish_operation(slot, operation_id, error=error)
                raise error from exc

    def stop_service(self, port: int) -> ServiceStatus:
        """Stop a manager-owned service on ``port``."""

        with self._lifecycle_call():
            return self._stop_service(port)

    def _stop_service(self, port: int) -> ServiceStatus:
        checked_port = _validate_port(port)
        self._assert_lifecycle_open()
        slot = self._get_slot(checked_port)
        if slot is None:
            raise ServiceNotRunningError(
                "service port is not managed", code="service_not_managed", details={"port": checked_port}
            )
        with slot.lifecycle_lock:
            self._assert_lifecycle_open()
            return self._stop_locked(slot)

    def check_health(self, port: int) -> ServiceStatus:
        """Perform one explicit health check against a ready manager-owned instance."""

        with self._lifecycle_call():
            return self._check_health(port)

    def _check_health(self, port: int) -> ServiceStatus:
        checked_port = _validate_port(port)
        self._assert_lifecycle_open()
        slot = self._get_slot(checked_port)
        if slot is None:
            raise ServiceNotRunningError(
                "service is not ready", code="service_not_ready", details={"port": checked_port}
            )
        with slot.lifecycle_lock:
            self._assert_lifecycle_open()
            if slot.state != ServiceState.READY or slot.instance is None or slot.backend is None:
                raise ServiceNotRunningError(
                    "service is not ready", code="service_not_ready", details={"port": checked_port}
                )
            operation_id = self._start_operation(slot)
            self._emit_operation_started(slot, operation_id)
            try:
                slot.backend.check_health(slot.instance)
            except Exception as exc:
                error = self._as_health_error(exc, slot)
                self._record_failure(slot, error, operation_id)
                self._finish_operation(slot, operation_id, error=error)
                raise error from exc
            self._finish_operation(slot, operation_id)
            return self._status_snapshot(slot)

    def get_status(self, port: int) -> ServiceStatus:
        """Return a fresh status snapshot for a managed port."""

        checked_port = _validate_port(port)
        slot = self._get_slot(checked_port)
        if slot is None:
            raise ServiceNotRunningError(
                "service port is not managed", code="service_not_managed", details={"port": checked_port}
            )
        return self._status_snapshot(slot)

    def list_statuses(self) -> tuple[ServiceStatus, ...]:
        """Return fresh snapshots ordered by requested port."""

        with self._registry_lock:
            slots = tuple(self._slots[port] for port in sorted(self._slots))
        return tuple(self._status_snapshot(slot) for slot in slots)

    def get_operation(self, operation_id: str) -> OperationStatus:
        """Return a fresh operation snapshot by identifier."""

        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ServiceError("operation ID is invalid", code="service_operation_not_found")
        normalized_id = operation_id.strip()
        with self._registry_lock:
            operation = self._operation_by_id.get(normalized_id)
        if operation is None:
            raise ServiceError("operation was not found", code="service_operation_not_found")
        return self._copy_operation(operation)

    def list_operations(self, port: int | None = None) -> tuple[OperationStatus, ...]:
        """Return operation snapshots in creation order, optionally for one port."""

        checked_port = None if port is None else _validate_port(port)
        with self._registry_lock:
            operations = tuple(
                operation for operation in self._operations if checked_port is None or operation.port == checked_port
            )
        return tuple(self._copy_operation(operation) for operation in operations)

    def get_diagnostics(self, port: int) -> ServiceDiagnostics:
        """Return generic and backend diagnostics without changing lifecycle state."""

        checked_port = _validate_port(port)
        with self._registry_lock:
            slot = self._slots.get(checked_port)
            if slot is None:
                raise ServiceNotRunningError(
                    "service port is not managed", code="service_not_managed", details={"port": checked_port}
                )
            instance, backend = slot.instance, slot.backend
            port_value, service_type, state, backend_id, updated_at = (
                slot.port,
                (slot.instance_service_type or slot.service_type) if instance is not None else slot.service_type,
                slot.state,
                (slot.backend_id if instance is not None else slot.target_backend_id) or "unknown",
                slot.updated_at,
            )
        details: dict[str, Any] = {}
        if instance is not None and backend is not None:
            try:
                values = backend.diagnostics(instance)
                if not isinstance(values, Mapping):
                    raise TypeError("backend diagnostics must be a mapping")
                details = {
                    str(key): value for key, value in values.items() if str(key) not in _RESERVED_DIAGNOSTIC_KEYS
                }
            except ServiceError:
                raise
            except Exception as exc:
                raise ServiceError(
                    "backend diagnostics failed",
                    code="service_diagnostics_failed",
                    details={"port": checked_port, "exception_type": type(exc).__name__},
                    cause=exc,
                ) from exc
        try:
            return ServiceDiagnostics(
                port=port_value,
                service_type=service_type,
                state=state,
                backend_id=backend_id,
                details=details,
                updated_at=updated_at,
            )
        except Exception as exc:
            if isinstance(exc, ServiceError):
                raise
            raise ServiceError(
                "backend diagnostics were invalid",
                code="service_diagnostics_failed",
                details={"port": checked_port, "exception_type": type(exc).__name__},
                cause=exc,
            ) from exc

    def get_logs(self, port: int, *, tail_lines: int = 200) -> ServiceLogSnapshot:
        """Return one bounded backend log tail without changing lifecycle state."""

        checked_port = _validate_port(port)
        if type(tail_lines) is not int or not 1 <= tail_lines <= 5000:
            raise ValueError("tail_lines must be an integer between 1 and 5000")
        with self._registry_lock:
            slot = self._slots.get(checked_port)
            if slot is None:
                raise ServiceNotRunningError(
                    "service port is not managed", code="service_not_managed", details={"port": checked_port}
                )
            instance, backend = slot.instance, slot.backend
            port_value, service_type, backend_id, updated_at = (
                slot.port,
                slot.instance_service_type or slot.service_type,
                slot.backend_id or "unknown",
                slot.updated_at,
            )
        if instance is None or backend is None:
            raise ServiceNotRunningError(
                "service logs are unavailable", code="service_logs_unavailable", details={"port": checked_port}
            )
        try:
            text = backend.read_logs(instance, tail_lines=tail_lines)
            if not isinstance(text, str):
                raise TypeError("backend logs must be text")
            lines = text.splitlines(keepends=True)
            bounded_text = "".join(lines[-tail_lines:])
            return ServiceLogSnapshot(
                port=port_value,
                service_type=service_type,
                backend_id=backend_id,
                text=bounded_text,
                tail_lines=tail_lines,
                updated_at=updated_at,
            )
        except ServiceError:
            raise
        except Exception as exc:
            raise ServiceError(
                "backend log retrieval failed",
                code="service_logs_failed",
                details={"port": checked_port, "exception_type": type(exc).__name__},
                cause=exc,
            ) from exc

    def shutdown(self) -> tuple[ServiceStatus, ...]:
        """Best-effort stop every owned service and permanently close the manager."""

        with self._lifecycle_call():
            return self._shutdown()

    def _shutdown(self) -> tuple[ServiceStatus, ...]:
        with self._shutdown_lock:
            with self._registry_lock:
                if self._cleanup_complete:
                    return tuple(self._status_snapshot(slot) for slot in self._ordered_slots_locked())
                self._closing = True
                self._closed = True
                slots = self._ordered_slots_locked()
            self._emit("service.shutdown.started", EventLevel.INFO, "service manager shutdown started")
            failures: list[ServiceError] = []
            try:
                for slot in slots:
                    with slot.lifecycle_lock:
                        if slot.state == ServiceState.STOPPED:
                            continue
                        try:
                            self._stop_locked(slot, allow_closing=True)
                        except ServiceError as exc:
                            failures.append(exc)
            finally:
                with self._registry_lock:
                    self._closing = False
                    statuses = tuple(self._status_snapshot(slot) for slot in self._ordered_slots_locked())
            if failures:
                error = ServiceError(
                    "service manager shutdown was incomplete",
                    code="service_shutdown_incomplete",
                    details={
                        "failed_ports": sorted(
                            port for failure in failures if isinstance((port := failure.details.get("port")), int)
                        ),
                        "error_codes": [failure.code for failure in failures],
                    },
                )
                self._emit(
                    "service.shutdown.incomplete",
                    EventLevel.ERROR,
                    "service manager shutdown was incomplete",
                    data=error.details,
                    error=error,
                )
                raise error
            with self._registry_lock:
                self._cleanup_complete = True
            self._unregister_atexit()
            self._emit("service.shutdown.completed", EventLevel.INFO, "service manager shutdown completed")
            return statuses

    def __enter__(self) -> ServiceManager:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc_type is None:
            self.shutdown()
        else:
            try:
                self.shutdown()
            except BaseException:
                pass

    def _reuse_locked(self, slot: _Slot) -> ServiceStatus:
        operation_id = self._start_operation(slot)
        self._emit_operation_started(slot, operation_id)
        assert slot.backend is not None and slot.instance is not None
        try:
            slot.backend.check_health(slot.instance)
        except Exception as exc:
            error = self._as_health_error(exc, slot)
            self._record_failure(slot, error, operation_id)
            self._finish_operation(slot, operation_id, error=error)
            raise error from exc
        self._emit(
            "service.reused",
            EventLevel.INFO,
            "healthy service reused",
            operation_id=operation_id,
            data=self._slot_event_data(slot, operation_id),
        )
        self._finish_operation(slot, operation_id)
        return self._status_snapshot(slot)

    def _provision_locked(
        self,
        slot: _Slot,
        requested: ServiceSpec,
        backend: ServiceBackend,
        target_backend_id: str,
        operation_id: str,
    ) -> ServiceStatus:
        try:
            if self._port_inspector.is_in_use(requested.port):
                raise ServiceConflictError(
                    "requested port is already in use by an unmanaged listener",
                    code="service_port_in_use",
                    details={"port": requested.port},
                )
        except ServiceConflictError:
            raise
        except Exception as exc:
            raise ServiceConflictError(
                "requested port could not be inspected",
                code="service_port_probe_failed",
                details={"port": requested.port, "exception_type": type(exc).__name__},
                cause=exc,
            ) from exc
        self._prepare_new_spec(slot, requested, target_backend_id, operation_id)
        try:
            resolved = resolve_runtime_settings(requested, self._hardware)
        except Exception as exc:
            raise self._as_start_error(exc, slot, requested) from exc
        if target_backend_id != resolved.backend:
            raise ServiceStartupError(
                "backend identity does not match resolved runtime settings",
                code="service_backend_contract_invalid",
                details={
                    "port": requested.port,
                    "service_type": requested.service_type.value,
                    "backend_id": target_backend_id,
                    "resolved_backend": resolved.backend,
                },
            )
        self._set_resolved_settings(slot, resolved)
        reporter = _ProgressReporter(
            self,
            slot,
            operation_id,
            _START_PROGRESS_STATES,
            service_type=requested.service_type,
            backend_id=target_backend_id,
        )
        try:
            returned_instance = backend.start(requested, resolved, reporter)
        except Exception as exc:
            raise self._as_start_error(exc, slot, requested) from exc
        try:
            instance = self._validate_instance(returned_instance, requested, resolved)
        except ServiceStartupError as validation_error:
            if isinstance(returned_instance, BackendInstance):
                cleanup_error = self._cleanup_invalid_instance(
                    slot,
                    backend,
                    returned_instance,
                    operation_id,
                )
                if cleanup_error is not None:
                    raise ServiceStartupError(
                        "backend returned an invalid instance and cleanup failed",
                        code="service_backend_contract_invalid",
                        details={
                            "port": requested.port,
                            "service_type": requested.service_type.value,
                            "cleanup_error_code": cleanup_error.code,
                        },
                        cause=validation_error,
                    ) from cleanup_error
            raise
        self._set_instance(slot, backend, instance)
        try:
            backend.check_health(instance)
        except Exception as exc:
            raise self._as_health_error(exc, slot) from exc
        self._transition(
            slot,
            state=ServiceState.READY,
            operation_id=operation_id,
            endpoint=instance.endpoint,
            started_at=self._now(),
            error=None,
        )
        self._finish_operation(slot, operation_id)
        return self._status_snapshot(slot)

    def _stop_for_replacement_locked(self, slot: _Slot, operation_id: str) -> None:
        self._stop_instance_locked(slot, operation_id)

    def _stop_locked(self, slot: _Slot, *, allow_closing: bool = False) -> ServiceStatus:
        if slot.state == ServiceState.STOPPED:
            return self._status_snapshot(slot)
        if not allow_closing:
            self._assert_lifecycle_open()
        operation_id = self._start_operation(slot)
        self._emit_operation_started(slot, operation_id)
        try:
            if slot.instance is not None:
                self._stop_instance_locked(slot, operation_id)
            else:
                self._transition(slot, state=ServiceState.STOPPED, operation_id=operation_id, endpoint=None, error=None)
            self._finish_operation(slot, operation_id)
        except Exception as exc:
            error = self._as_stop_error(exc, slot)
            self._record_failure(slot, error, operation_id)
            self._finish_operation(slot, operation_id, error=error)
            raise error from exc
        return self._status_snapshot(slot)

    def _stop_instance_locked(self, slot: _Slot, operation_id: str) -> None:
        if slot.instance is None or slot.backend is None:
            self._transition(slot, state=ServiceState.STOPPED, operation_id=operation_id, endpoint=None, error=None)
            return
        instance_service_type = slot.instance_service_type or slot.service_type
        instance_backend_id = slot.backend_id or self._backend_id(slot.backend)
        self._transition(
            slot,
            state=ServiceState.STOPPING,
            operation_id=operation_id,
            event_service_type=instance_service_type,
            event_backend_id=instance_backend_id,
            endpoint=None,
            error=None,
        )
        reporter = _ProgressReporter(
            self,
            slot,
            operation_id,
            _STOP_PROGRESS_STATES,
            service_type=instance_service_type,
            backend_id=instance_backend_id,
        )
        try:
            slot.backend.stop(slot.instance, reporter)
        except Exception as exc:
            raise self._as_stop_error(exc, slot) from exc
        self._transition(
            slot,
            state=ServiceState.STOPPED,
            operation_id=operation_id,
            event_service_type=instance_service_type,
            event_backend_id=instance_backend_id,
            endpoint=None,
            error=None,
        )

    def _prepare_new_spec(
        self,
        slot: _Slot,
        spec: ServiceSpec,
        target_backend_id: str,
        operation_id: str,
    ) -> None:
        now = self._now()
        with self._registry_lock:
            slot.service_type = spec.service_type
            slot.target_backend_id = target_backend_id or None
            slot.requested_spec = self._copy_spec(spec)
            slot.resolved_settings = None
            slot.endpoint = None
            slot.error = None
            slot.started_at = None
            slot.operation_id = operation_id
            slot.updated_at = self._non_decreasing(now, slot.updated_at)
        self._transition(slot, state=ServiceState.RESOLVING, operation_id=operation_id, endpoint=None, error=None)

    def _set_resolved_settings(self, slot: _Slot, settings: ResolvedRuntimeSettings) -> None:
        copied = ResolvedRuntimeSettings.model_validate(settings.model_dump())
        now = self._now()
        with self._registry_lock:
            slot.resolved_settings = copied
            slot.updated_at = self._non_decreasing(now, slot.updated_at)

    def _set_instance(self, slot: _Slot, backend: ServiceBackend, instance: BackendInstance) -> None:
        now = self._now()
        with self._registry_lock:
            slot.backend = backend
            slot.backend_id = self._backend_id(backend)
            slot.target_backend_id = self._backend_id(backend)
            slot.instance = instance
            slot.instance_service_type = instance.endpoint.service_type
            slot.resolved_settings = ResolvedRuntimeSettings.model_validate(instance.resolved_settings.model_dump())
            slot.updated_at = self._non_decreasing(now, slot.updated_at)

    def _cleanup_invalid_instance(
        self,
        slot: _Slot,
        backend: ServiceBackend,
        instance: BackendInstance,
        operation_id: str,
    ) -> ServiceError | None:
        instance_service_type = (
            instance.endpoint.service_type if isinstance(instance.endpoint, ServiceEndpoint) else slot.service_type
        )
        instance_backend_id = self._backend_id(backend)
        reporter = _ProgressReporter(
            self,
            slot,
            operation_id,
            _STOP_PROGRESS_STATES,
            service_type=instance_service_type,
            backend_id=instance_backend_id,
        )
        try:
            backend.stop(instance, reporter)
        except Exception as exc:
            error = self._as_stop_error(exc, slot)
            now = self._now()
            with self._registry_lock:
                slot.backend = backend
                slot.backend_id = self._backend_id(backend)
                slot.target_backend_id = instance_backend_id
                slot.instance = instance
                slot.instance_service_type = instance_service_type
                slot.updated_at = self._non_decreasing(now, slot.updated_at)
            return error
        return None

    def _validate_instance(
        self,
        value: object,
        spec: ServiceSpec,
        initial_settings: ResolvedRuntimeSettings,
    ) -> BackendInstance:
        if not isinstance(value, BackendInstance):
            raise ServiceStartupError("backend returned an invalid instance", code="service_backend_contract_invalid")
        try:
            endpoint = ServiceEndpoint.model_validate(value.endpoint.model_dump())
            settings = ResolvedRuntimeSettings.model_validate(value.resolved_settings.model_dump())
        except Exception as exc:
            raise ServiceStartupError(
                "backend returned invalid instance fields",
                code="service_backend_contract_invalid",
                cause=exc,
            ) from exc
        if (
            endpoint.port != spec.port
            or endpoint.service_type != spec.service_type
            or settings.backend != initial_settings.backend
        ):
            raise ServiceStartupError(
                "backend instance does not match the requested service",
                code="service_backend_contract_invalid",
                details={"port": spec.port, "service_type": spec.service_type.value},
            )
        return BackendInstance(endpoint=endpoint, resolved_settings=settings, handle=value.handle)

    def _start_operation(
        self,
        slot: _Slot,
        *,
        service_type: ServiceType | None = None,
        backend_id: str | None = None,
    ) -> str:
        raw_operation_id = self._operation_id_factory()
        if not isinstance(raw_operation_id, str) or not raw_operation_id.strip():
            raise ServiceError("operation ID factory returned an invalid ID", code="service_operation_invalid")
        operation_id = raw_operation_id.strip()
        now = self._now()
        with self._registry_lock:
            if operation_id in self._operation_by_id:
                raise ServiceError("operation ID factory returned a duplicate ID", code="service_operation_invalid")
            operation_service_type = service_type or slot.instance_service_type or slot.service_type
            operation_backend_id = (
                backend_id if backend_id is not None else slot.backend_id or slot.target_backend_id or ""
            )
            timestamp = self._non_decreasing(now, slot.updated_at)
            pending = OperationStatus(
                operation_id=operation_id,
                port=slot.port,
                state=OperationState.PENDING,
                updated_at=timestamp,
            )
            running = self._operation_with(
                pending,
                state=OperationState.RUNNING,
                service_state=slot.state,
                started_at=timestamp,
                updated_at=timestamp,
            )
            self._operations.append(running)
            self._operation_by_id[operation_id] = running
            self._operation_identities[operation_id] = (
                operation_service_type,
                operation_backend_id,
            )
            slot.operation_id = operation_id
            slot.updated_at = timestamp
        return operation_id

    def _finish_operation(self, slot: _Slot, operation_id: str, *, error: ServiceError | None = None) -> None:
        now = self._now()
        with self._registry_lock:
            operation = self._operation_by_id[operation_id]
            timestamp = self._non_decreasing(now, operation.updated_at)
            finished = self._operation_with(
                operation,
                state=OperationState.FAILED if error is not None else OperationState.SUCCEEDED,
                service_state=slot.state,
                error=None if error is None else error.to_info(),
                updated_at=timestamp,
                finished_at=timestamp,
            )
            self._replace_operation_locked(finished)
        if error is None:
            self._emit(
                "service.operation.succeeded",
                EventLevel.INFO,
                "service operation succeeded",
                operation_id=operation_id,
                data=self._slot_event_data(slot, operation_id),
            )
        else:
            self._emit(
                "service.operation.failed",
                EventLevel.ERROR,
                "service operation failed",
                operation_id=operation_id,
                data=self._slot_event_data(slot, operation_id),
                error=error,
            )

    def _transition(
        self,
        slot: _Slot,
        *,
        state: ServiceState,
        operation_id: str,
        event_service_type: ServiceType | None = None,
        event_backend_id: str | None = None,
        endpoint: Any = ...,
        error: Any = ...,
        started_at: Any = ...,
        progress: Any = ...,
        message: Any = ...,
    ) -> None:
        now = self._now()
        with self._registry_lock:
            old_state = slot.state
            slot.state = state
            slot.operation_id = operation_id
            if endpoint is not ...:
                slot.endpoint = endpoint
            if error is not ...:
                slot.error = error
            if started_at is not ...:
                slot.started_at = started_at
            slot.updated_at = self._non_decreasing(now, slot.updated_at)
            operation = self._operation_by_id[operation_id]
            operation_values: dict[str, Any] = {
                "service_state": state,
                "updated_at": self._non_decreasing(slot.updated_at, operation.updated_at),
            }
            if progress is not ...:
                operation_values["progress"] = progress
            if message is not ...:
                operation_values["message"] = message
            self._replace_operation_locked(self._operation_with(operation, **operation_values))
            operation_service_type, operation_backend_id = self._operation_identities[operation_id]
            data = self._slot_event_data_locked(
                slot,
                service_type=event_service_type or operation_service_type,
                backend_id=operation_backend_id if event_backend_id is None else event_backend_id,
            )
            data.update({"old_state": old_state.value, "new_state": state.value})
        self._emit(
            "service.state.changed", EventLevel.INFO, "service state changed", operation_id=operation_id, data=data
        )

    def _record_failure(
        self,
        slot: _Slot,
        error: ServiceError,
        operation_id: str,
        *,
        requested_spec: ServiceSpec | None = None,
    ) -> None:
        if requested_spec is not None:
            with self._registry_lock:
                slot.service_type = requested_spec.service_type
                slot.requested_spec = self._copy_spec(requested_spec)
                slot.resolved_settings = slot.resolved_settings if slot.instance is not None else None
                slot.started_at = None
        self._transition(
            slot,
            state=ServiceState.FAILED,
            operation_id=operation_id,
            endpoint=None,
            error=error.to_info(),
        )

    def _status_snapshot(self, slot: _Slot) -> ServiceStatus:
        with self._registry_lock:
            value = ServiceStatus(
                port=slot.port,
                service_type=slot.service_type,
                state=slot.state,
                endpoint=slot.endpoint,
                requested_spec=slot.requested_spec,
                resolved_settings=slot.resolved_settings,
                operation_id=slot.operation_id,
                error=slot.error,
                started_at=slot.started_at,
                updated_at=slot.updated_at,
            )
        return ServiceStatus.model_validate(value.model_dump())

    @staticmethod
    def _copy_spec(spec: ServiceSpec) -> ServiceSpec:
        from arcadia.models import LlamaServiceSpec, SamServiceSpec

        if not isinstance(spec, (LlamaServiceSpec, SamServiceSpec)):
            raise ValueError("spec must be a public service specification")
        return type(spec).model_validate(copy.deepcopy(spec.model_dump()))

    @staticmethod
    def _copy_operation(operation: OperationStatus) -> OperationStatus:
        return OperationStatus.model_validate(operation.model_dump())

    @staticmethod
    def _operation_with(operation: OperationStatus, **updates: Any) -> OperationStatus:
        values = operation.model_dump()
        values.update(updates)
        return OperationStatus.model_validate(values)

    def _replace_operation_locked(self, operation: OperationStatus) -> None:
        self._operation_by_id[operation.operation_id] = operation
        for index, existing in enumerate(self._operations):
            if existing.operation_id == operation.operation_id:
                self._operations[index] = operation
                return
        raise RuntimeError("operation history is inconsistent")

    def _get_or_create_slot(self, spec: ServiceSpec) -> _Slot:
        now = self._now()
        with self._registry_lock:
            if self._closing or self._closed:
                raise ServiceError("service manager is closed", code="service_manager_closed")
            slot = self._slots.get(spec.port)
            if slot is None:
                slot = _Slot(
                    port=spec.port,
                    service_type=spec.service_type,
                    target_backend_id=None,
                    state=ServiceState.STOPPED,
                    requested_spec=None,
                    resolved_settings=None,
                    backend=None,
                    backend_id=None,
                    instance_service_type=None,
                    instance=None,
                    endpoint=None,
                    error=None,
                    started_at=None,
                    updated_at=now,
                )
                self._slots[spec.port] = slot
            return slot

    def _get_slot(self, port: int) -> _Slot | None:
        with self._registry_lock:
            return self._slots.get(port)

    def _ordered_slots_locked(self) -> tuple[_Slot, ...]:
        return tuple(self._slots[port] for port in sorted(self._slots))

    @contextmanager
    def _lifecycle_call(self) -> Generator[None, None, None]:
        if getattr(self._lifecycle_local, "active", False):
            raise ServiceError(
                "reentrant service lifecycle operations are not allowed",
                code="service_lifecycle_reentrant",
            )
        self._lifecycle_local.active = True
        try:
            yield
        finally:
            self._lifecycle_local.active = False

    def _assert_lifecycle_open(self) -> None:
        with self._registry_lock:
            if self._closing or self._closed:
                raise ServiceError("service manager is closed", code="service_manager_closed")

    def _as_start_error(self, exc: BaseException, slot: _Slot, spec: ServiceSpec) -> ServiceError:
        if isinstance(exc, ServiceError):
            return exc
        return ServiceStartupError(
            "service startup failed",
            code="service_startup_failed",
            details={"port": spec.port, "service_type": spec.service_type.value, "exception_type": type(exc).__name__},
            cause=exc,
        )

    def _as_health_error(self, exc: BaseException, slot: _Slot) -> ServiceError:
        if isinstance(exc, ServiceError):
            return exc
        return ServiceHealthError(
            "service health check failed",
            code="service_health_failed",
            details={"port": slot.port, "service_type": slot.service_type.value, "exception_type": type(exc).__name__},
            cause=exc,
        )

    def _as_stop_error(self, exc: BaseException, slot: _Slot) -> ServiceError:
        if isinstance(exc, ServiceError):
            return exc
        return ServiceError(
            "service stop failed",
            code="service_stop_failed",
            details={"port": slot.port, "service_type": slot.service_type.value, "exception_type": type(exc).__name__},
            cause=exc,
        )

    @staticmethod
    def _non_decreasing(candidate: datetime, previous: datetime) -> datetime:
        return candidate if candidate >= previous else previous

    def _now(self) -> datetime:
        value = _normalize_datetime(self._clock())
        if value is None:
            raise ValueError("clock must return an aware datetime")
        return value

    def _emit_operation_started(self, slot: _Slot, operation_id: str) -> None:
        self._emit(
            "service.operation.started",
            EventLevel.INFO,
            "service operation started",
            operation_id=operation_id,
            data=self._slot_event_data(slot, operation_id),
        )

    def _slot_event_data(self, slot: _Slot, operation_id: str | None = None) -> dict[str, Any]:
        with self._registry_lock:
            if operation_id is None:
                service_type = slot.instance_service_type or slot.service_type
                backend_id = slot.backend_id or slot.target_backend_id or ""
            else:
                service_type, backend_id = self._operation_identities[operation_id]
            return self._slot_event_data_locked(slot, service_type=service_type, backend_id=backend_id)

    @staticmethod
    def _slot_event_data_locked(
        slot: _Slot,
        *,
        service_type: ServiceType,
        backend_id: str,
    ) -> dict[str, Any]:
        return {
            "port": slot.port,
            "service_type": service_type.value,
            "backend_id": backend_id,
            "state": slot.state.value,
        }

    def _emit(
        self,
        kind: str,
        level: EventLevel,
        message: str,
        *,
        data: dict[str, Any] | None = None,
        operation_id: str | None = None,
        error: ServiceError | None = None,
    ) -> None:
        try:
            event = ArcadiaEvent(
                kind=kind,
                level=level,
                source=_SOURCE,
                message=message,
                data={} if data is None else data,
                operation_id=operation_id,
                error=None if error is None else error.to_info(),
            )
            self._event_emitter.emit(event)
        except Exception:
            pass

    def _unregister_atexit(self) -> None:
        callback = self._atexit_callback
        if callback is not None:
            atexit.unregister(callback)
            self._atexit_callback = None
