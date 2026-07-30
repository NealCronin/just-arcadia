"""Backend and local-port contracts for managed services."""

from __future__ import annotations

import errno
import math
import socket
from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from arcadia.models.common import ResolvedRuntimeSettings, _validate_host, _validate_port
from arcadia.models.services import ServiceSpec, ServiceState
from arcadia.services.models import BackendInstance

__all__ = [
    "BackendProgressReporter",
    "ServiceBackend",
    "PortInspector",
    "TcpPortInspector",
]


@runtime_checkable
class BackendProgressReporter(Protocol):
    """Receives non-terminal progress reported by one backend call."""

    def report(
        self,
        *,
        state: ServiceState,
        progress: float | None = None,
        message: str = "",
    ) -> None:
        """Record one backend lifecycle transition."""
        ...


@runtime_checkable
class ServiceBackend(Protocol):
    """Own backend-specific provisioning and cleanup for one service type."""

    @property
    def backend_id(self) -> str:
        """Return this backend's stable identifier."""
        ...

    def start(
        self,
        spec: ServiceSpec,
        resolved_settings: ResolvedRuntimeSettings,
        progress: BackendProgressReporter,
    ) -> BackendInstance:
        """Synchronously create a backend-owned service instance.

        This call is transactional: before raising, an implementation must
        release every process, listener, model allocation, temporary file,
        and other resource created during the attempt.
        """
        ...

    def check_health(self, instance: BackendInstance) -> None:
        """Raise unless the supplied instance is currently usable."""
        ...

    def stop(self, instance: BackendInstance, progress: BackendProgressReporter) -> None:
        """Idempotently stop a backend-owned instance."""
        ...

    def diagnostics(self, instance: BackendInstance) -> Mapping[str, Any]:
        """Return bounded, JSON-safe backend diagnostics."""
        ...

    def read_logs(self, instance: BackendInstance, *, tail_lines: int) -> str:
        """Return at most the requested final logical log lines."""
        ...


@runtime_checkable
class PortInspector(Protocol):
    """Checks whether a requested local TCP port is occupied."""

    def is_in_use(self, port: int) -> bool:
        """Return whether a listener answered a bounded TCP probe."""
        ...


class TcpPortInspector:
    """Bounded, side-effect-free local TCP listener probe."""

    def __init__(self, *, host: str = "127.0.0.1", timeout_seconds: float = 0.2) -> None:
        self._host = _validate_host(host)
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
            raise ValueError("timeout_seconds must be a finite positive number")
        self._timeout_seconds = float(timeout_seconds)
        if not math.isfinite(self._timeout_seconds) or self._timeout_seconds <= 0.0:
            raise ValueError("timeout_seconds must be a finite positive number")

    def is_in_use(self, port: int) -> bool:
        """Probe one port, treating probe failures as errors rather than free ports."""

        checked_port = _validate_port(port)
        try:
            with socket.create_connection((self._host, checked_port), timeout=self._timeout_seconds):
                return True
        except ConnectionRefusedError:
            return False
        except OSError as exc:
            if exc.errno == errno.ECONNREFUSED:
                return False
            raise RuntimeError("TCP port probe failed") from exc
