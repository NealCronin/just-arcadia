"""Controlled Session 07 boundaries shared by contract and integration tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from arcadia.models import HuggingFaceFileSpec, ServiceState


class RecordingProgress:
    def __init__(self) -> None:
        self.reports: list[tuple[ServiceState, float | None, str]] = []

    def report(self, *, state: ServiceState, progress: float | None = None, message: str = "") -> None:
        self.reports.append((state, progress, message))


class FakeResolver:
    def __init__(self, model_path: Path, projector_path: Path | None = None, *, error_role: str | None = None) -> None:
        self.model_path = model_path
        self.projector_path = projector_path
        self.error_role = error_role
        self.calls: list[tuple[str, HuggingFaceFileSpec]] = []

    def resolve(self, file_spec: HuggingFaceFileSpec, *, role: str, progress: Any) -> Path:
        self.calls.append((role, file_spec))
        progress.report(state=ServiceState.RESOLVING, message=f"Resolving {role} file")
        if role == self.error_role:
            raise OSError(f"{role} resolution failed")
        if role == "projector":
            assert self.projector_path is not None
            return self.projector_path
        return self.model_path


class FakeProcess:
    def __init__(self, *, pid: int = 4321, return_code: int | None = None) -> None:
        self._pid = pid
        self.return_code = return_code
        self.terminate_calls = 0
        self.close_calls = 0

    @property
    def pid(self) -> int:
        return self._pid

    def poll(self) -> int | None:
        return self.return_code

    def terminate_tree(self, *, stop_timeout_seconds: float, kill_timeout_seconds: float) -> None:
        self.terminate_calls += 1
        self.return_code = 0

    def close(self) -> None:
        self.close_calls += 1


class FakeLauncher:
    def __init__(
        self, process: FakeProcess | None = None, *, error: Exception | None = None, log_text: bytes = b"one\ntwo\n"
    ) -> None:
        self.process = FakeProcess() if process is None else process
        self.error = error
        self.log_text = log_text
        self.calls: list[dict[str, Any]] = []

    def launch(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        log_path: Path,
        environment_updates: Mapping[str, str],
    ) -> FakeProcess:
        self.calls.append(
            {
                "command": list(command),
                "cwd": cwd,
                "log_path": log_path,
                "environment_updates": dict(environment_updates),
            }
        )
        if self.error is not None:
            raise self.error
        log_path.write_bytes(self.log_text)
        return self.process


class FakeHealth:
    def __init__(self, failures: Sequence[Exception] | None = None) -> None:
        self.failures = [] if failures is None else list(failures)
        self.calls: list[tuple[str, int, float]] = []

    def probe(self, host: str, port: int, *, timeout_seconds: float) -> None:
        self.calls.append((host, port, timeout_seconds))
        if self.failures:
            raise self.failures.pop(0)
