"""Synchronous managed llama.cpp service backend."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
import time
import weakref
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from arcadia.models import (
    HuggingFaceFileSpec,
    LlamaServiceSpec,
    ResolvedRuntimeSettings,
    ServiceEndpoint,
    ServiceError,
    ServiceHealthError,
    ServiceStartupError,
    ServiceState,
)
from arcadia.services import BackendInstance, BackendProgressReporter

from .config import LlamaCppBackendConfig
from .files import FileResolver, FileRole, HuggingFaceFileResolver
from .health import HealthProbe, HttpModelsHealthProbe
from .process import OwnedProcess, ProcessLauncher, SubprocessLauncher
from .settings import translate_settings

LLAMA_CPP_BACKEND_ID = "llama_cpp"
_SPLIT_GGUF = re.compile(r"-\d{5}-of-\d{5}\.gguf$", re.IGNORECASE)
_GLOB_CHARACTERS = frozenset("*?[]")


@dataclass(slots=True, weakref_slot=True)
class _LlamaCppHandle:
    owner: object
    process: OwnedProcess
    runtime_path: Path
    config_path: Path
    log_path: Path
    endpoint: ServiceEndpoint
    bind_host: str
    model_identity: dict[str, str]
    projector_identity: dict[str, str] | None
    started_at: datetime
    stopped_at: datetime | None = None
    stopped: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)
    finalizer: weakref.finalize | None = field(default=None, repr=False)


class LlamaCppBackend:
    """Resolve exact GGUF files and own one llama.cpp server per returned handle."""

    def __init__(
        self,
        *,
        config: LlamaCppBackendConfig | None = None,
        file_resolver: object | None = None,
        process_launcher: object | None = None,
        health_probe: object | None = None,
        clock: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        selected = LlamaCppBackendConfig() if config is None else config
        if not isinstance(selected, LlamaCppBackendConfig):
            raise TypeError("config must be a LlamaCppBackendConfig")
        self._config = selected
        self._file_resolver = cast(
            FileResolver,
            file_resolver if file_resolver is not None else HuggingFaceFileResolver(cache_dir=selected.cache_dir),
        )
        self._process_launcher = cast(
            ProcessLauncher,
            process_launcher if process_launcher is not None else SubprocessLauncher(),
        )
        self._health_probe = cast(HealthProbe, health_probe if health_probe is not None else HttpModelsHealthProbe())
        self._clock = clock if clock is not None else lambda: datetime.now(UTC)
        self._sleeper = sleeper if sleeper is not None else time.sleep
        self._owner = object()

    @property
    def backend_id(self) -> str:
        return LLAMA_CPP_BACKEND_ID

    def start(
        self,
        spec: object,
        resolved_settings: ResolvedRuntimeSettings,
        progress: BackendProgressReporter,
    ) -> BackendInstance:
        self._validate_start_inputs(spec, resolved_settings)
        assert isinstance(spec, LlamaServiceSpec)
        self._validate_filename(spec.model)
        if spec.projector is not None:
            self._validate_filename(spec.projector)

        runtime_path: Path | None = None
        config_path: Path | None = None
        log_path: Path | None = None
        process: OwnedProcess | None = None
        try:
            model_path = self._resolve_file(spec.model, role="model", progress=progress)
            projector_path = (
                self._resolve_file(spec.projector, role="projector", progress=progress)
                if spec.projector is not None
                else None
            )
            translated = translate_settings(
                resolved_settings,
                bind_host=self._config.bind_host,
                port=spec.port,
                model_path=model_path,
                projector_path=projector_path,
            )
            runtime_path = self._create_runtime_path()
            config_path = runtime_path / "server-config.json"
            log_path = runtime_path / "server.log"
            self._write_config(config_path, translated.server_config)
            log_path.touch(mode=0o600, exist_ok=False)
            command = [
                self._config.python_executable,
                "-m",
                "llama_cpp.server",
                "--config_file",
                str(config_path),
            ]
            try:
                launcher = self._process_launcher
                process = launcher.launch(
                    command,
                    cwd=runtime_path,
                    log_path=log_path,
                    environment_updates=translated.environment_updates,
                )
            except Exception as exc:
                raise ServiceStartupError(
                    "Failed to launch llama.cpp server",
                    code="llama_cpp_process_launch_failed",
                    details={"exception_type": type(exc).__name__},
                    cause=exc,
                ) from exc

            progress.report(state=ServiceState.STARTING, message="Starting llama.cpp server")
            self._await_readiness(process, spec.port)
            self._remove_config(config_path)
            advertise_host = self._config.advertise_host
            assert advertise_host is not None
            endpoint = ServiceEndpoint(host=advertise_host, port=spec.port, service_type=spec.service_type)
            handle = _LlamaCppHandle(
                owner=self._owner,
                process=process,
                runtime_path=runtime_path,
                config_path=config_path,
                log_path=log_path,
                endpoint=endpoint,
                bind_host=self._config.bind_host,
                model_identity=self._identity(spec.model),
                projector_identity=None if spec.projector is None else self._identity(spec.projector),
                started_at=self._now(),
            )
            handle.finalizer = weakref.finalize(
                handle,
                self._final_cleanup,
                process,
                runtime_path,
                config_path,
                self._config.stop_timeout_seconds,
                self._config.kill_timeout_seconds,
            )
            detached_settings = ResolvedRuntimeSettings.model_validate(resolved_settings.model_dump(mode="python"))
            return BackendInstance(endpoint=endpoint, resolved_settings=detached_settings, handle=handle)
        except ServiceError as primary:
            cleanup_error = self._cleanup_attempt(process, runtime_path, config_path)
            if cleanup_error is not None:
                raise self._with_cleanup_cause(primary, cleanup_error) from primary
            raise
        except Exception as exc:
            cleanup_error = self._cleanup_attempt(process, runtime_path, config_path)
            cause: BaseException = (
                exc if cleanup_error is None else ExceptionGroup("startup and cleanup failed", [exc, cleanup_error])
            )
            raise ServiceStartupError(
                "Failed to prepare llama.cpp server runtime",
                code="llama_cpp_process_launch_failed",
                details={"exception_type": type(exc).__name__},
                cause=cause,
            ) from exc
        except BaseException:
            self._cleanup_attempt(process, runtime_path, config_path)
            raise

    def check_health(self, instance: BackendInstance) -> None:
        handle = self._handle(instance, ServiceHealthError)
        try:
            return_code = handle.process.poll()
        except Exception as exc:
            raise ServiceHealthError(
                "Failed to inspect llama.cpp process",
                code="llama_cpp_health_failed",
                details={"exception_type": type(exc).__name__},
                cause=exc,
            ) from exc
        if return_code is not None:
            raise ServiceHealthError(
                "llama.cpp server process has exited",
                code="llama_cpp_process_exited",
                details={"pid": handle.process.pid, "return_code": return_code},
            )
        try:
            probe = self._health_probe
            health_host = self._config.health_host
            assert health_host is not None
            probe.probe(
                health_host,
                handle.endpoint.port,
                timeout_seconds=self._config.health_timeout_seconds,
            )
        except Exception as exc:
            raise ServiceHealthError(
                "llama.cpp health check failed",
                code="llama_cpp_health_failed",
                details={"exception_type": type(exc).__name__},
                cause=exc,
            ) from exc

    def stop(self, instance: BackendInstance, progress: BackendProgressReporter) -> None:
        handle = self._handle(instance, ServiceError)
        progress.report(state=ServiceState.STOPPING, message="Stopping llama.cpp server")
        with handle.lock:
            if handle.stopped:
                return
            try:
                handle.process.terminate_tree(
                    stop_timeout_seconds=self._config.stop_timeout_seconds,
                    kill_timeout_seconds=self._config.kill_timeout_seconds,
                )
                handle.process.close()
                self._remove_config(handle.config_path)
                handle.stopped = True
                handle.stopped_at = self._now()
            except Exception as exc:
                raise ServiceError(
                    "Failed to stop llama.cpp server",
                    code="llama_cpp_stop_failed",
                    details={"pid": self._safe_pid(handle.process), "exception_type": type(exc).__name__},
                    cause=exc,
                ) from exc

    def diagnostics(self, instance: BackendInstance) -> Mapping[str, Any]:
        handle = self._handle(instance, ServiceError)
        try:
            return_code = handle.process.poll()
            log_size = handle.log_path.stat().st_size
            details: dict[str, Any] = {
                "pid": handle.process.pid,
                "alive": return_code is None,
                "return_code": return_code,
                "bind_host": handle.bind_host[:253],
                "advertise_host": handle.endpoint.host[:253],
                "port": handle.endpoint.port,
                "service_type": handle.endpoint.service_type.value,
                "model_repo_id": handle.model_identity["repo_id"][:256],
                "model_filename": handle.model_identity["filename"][:256],
                "model_revision": handle.model_identity["revision"][:256],
                "log_size_bytes": log_size,
                "started_at": handle.started_at.isoformat(),
            }
            if handle.projector_identity is not None:
                details.update(
                    projector_repo_id=handle.projector_identity["repo_id"][:256],
                    projector_filename=handle.projector_identity["filename"][:256],
                    projector_revision=handle.projector_identity["revision"][:256],
                )
            if handle.stopped_at is not None:
                details["stopped_at"] = handle.stopped_at.isoformat()
            return details
        except Exception as exc:
            raise ServiceError(
                "Failed to collect llama.cpp diagnostics",
                code="llama_cpp_diagnostics_failed",
                details={"exception_type": type(exc).__name__},
                cause=exc,
            ) from exc

    def read_logs(self, instance: BackendInstance, *, tail_lines: int) -> str:
        handle = self._handle(instance, ServiceError)
        if type(tail_lines) is not int or not 1 <= tail_lines <= 5000:
            raise ServiceError(
                "tail_lines must be an integer between 1 and 5000",
                code="llama_cpp_logs_failed",
                details={"tail_lines_valid": False},
            )
        try:
            return self._tail_file(handle.log_path, tail_lines)
        except Exception as exc:
            raise ServiceError(
                "Failed to read llama.cpp logs",
                code="llama_cpp_logs_failed",
                details={"exception_type": type(exc).__name__},
                cause=exc,
            ) from exc

    def _validate_start_inputs(self, spec: object, resolved_settings: object) -> None:
        if not isinstance(spec, LlamaServiceSpec):
            raise ServiceStartupError("llama.cpp requires an LLM service specification", code="llama_cpp_spec_invalid")
        if not isinstance(resolved_settings, ResolvedRuntimeSettings):
            raise ServiceStartupError("resolved settings are invalid", code="llama_cpp_spec_invalid")
        if resolved_settings.backend != LLAMA_CPP_BACKEND_ID:
            raise ServiceStartupError(
                "resolved settings target a different backend",
                code="llama_cpp_backend_mismatch",
                details={"backend": resolved_settings.backend[:120]},
            )

    @staticmethod
    def _validate_filename(file_spec: HuggingFaceFileSpec) -> None:
        if any(character in file_spec.filename for character in _GLOB_CHARACTERS):
            raise ServiceStartupError(
                "llama.cpp model filenames must be exact and cannot contain glob metacharacters",
                code="llama_cpp_spec_invalid",
                details={"filename": file_spec.filename},
            )
        if _SPLIT_GGUF.search(file_spec.filename):
            raise ServiceStartupError(
                "split GGUF files are not supported",
                code="llama_cpp_split_gguf_unsupported",
                details={"filename": file_spec.filename},
            )

    def _resolve_file(
        self,
        file_spec: HuggingFaceFileSpec,
        *,
        role: FileRole,
        progress: BackendProgressReporter,
    ) -> Path:
        try:
            resolver = self._file_resolver
            path = resolver.resolve(file_spec, role=role, progress=progress)
            path = Path(path)
            if not path.is_file():
                raise FileNotFoundError("resolver did not return an existing regular file")
            return path
        except ServiceStartupError:
            raise
        except (ImportError, ModuleNotFoundError) as exc:
            raise ServiceStartupError(
                "llama.cpp backend requires optional dependencies",
                code="llama_cpp_dependency_missing",
                details={"dependency": "huggingface_hub"},
                cause=exc,
            ) from exc
        except Exception as exc:
            raise ServiceStartupError(
                f"Failed to resolve llama.cpp {role} file",
                code="llama_cpp_model_resolve_failed",
                details={
                    "repo_id": file_spec.repo_id,
                    "filename": file_spec.filename,
                    "revision": file_spec.revision,
                    "role": role,
                    "exception_type": type(exc).__name__,
                },
                cause=exc,
            ) from exc

    def _await_readiness(self, process: OwnedProcess, port: int) -> None:
        deadline = time.monotonic() + self._config.startup_timeout_seconds
        last_probe_error: Exception | None = None
        while True:
            return_code = process.poll()
            if return_code is not None:
                raise ServiceStartupError(
                    "llama.cpp server exited before readiness",
                    code="llama_cpp_server_exited",
                    details={"pid": self._safe_pid(process), "return_code": return_code},
                    cause=last_probe_error,
                )
            try:
                health_host = self._config.health_host
                assert health_host is not None
                probe = self._health_probe
                probe.probe(
                    health_host,
                    port,
                    timeout_seconds=self._config.health_timeout_seconds,
                )
                return
            except Exception as exc:
                last_probe_error = exc
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ServiceStartupError(
                    "Timed out waiting for llama.cpp server readiness",
                    code="llama_cpp_startup_timeout",
                    details={"pid": self._safe_pid(process), "timeout_seconds": self._config.startup_timeout_seconds},
                    cause=last_probe_error,
                )
            self._sleeper(min(self._config.poll_interval_seconds, remaining))

    def _create_runtime_path(self) -> Path:
        base = self._config.runtime_dir
        if base is not None:
            base.mkdir(parents=True, exist_ok=True)
        path = Path(tempfile.mkdtemp(prefix="arcadia-llama-cpp-", dir=base))
        try:
            path.chmod(0o700)
        except OSError:
            pass
        return path

    @staticmethod
    def _write_config(path: Path, payload: dict[str, Any]) -> None:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
                stream.write("\n")
        except BaseException:
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise

    @staticmethod
    def _remove_config(path: Path | None) -> None:
        if path is not None:
            path.unlink(missing_ok=True)

    def _cleanup_attempt(
        self,
        process: OwnedProcess | None,
        runtime_path: Path | None,
        config_path: Path | None,
    ) -> Exception | None:
        failures: list[Exception] = []
        if process is not None:
            try:
                process.terminate_tree(
                    stop_timeout_seconds=self._config.stop_timeout_seconds,
                    kill_timeout_seconds=self._config.kill_timeout_seconds,
                )
            except Exception as exc:
                failures.append(exc)
            try:
                process.close()
            except Exception as exc:
                failures.append(exc)
        try:
            self._remove_config(config_path)
            if runtime_path is not None:
                shutil.rmtree(runtime_path, ignore_errors=False)
        except FileNotFoundError:
            pass
        except Exception as exc:
            failures.append(exc)
        if not failures:
            return None
        return failures[0] if len(failures) == 1 else ExceptionGroup("llama.cpp cleanup failures", failures)

    @staticmethod
    def _final_cleanup(
        process: OwnedProcess,
        runtime_path: Path,
        config_path: Path,
        stop_timeout_seconds: float,
        kill_timeout_seconds: float,
    ) -> None:
        try:
            if process.poll() is None:
                process.terminate_tree(
                    stop_timeout_seconds=stop_timeout_seconds,
                    kill_timeout_seconds=kill_timeout_seconds,
                )
            process.close()
        except Exception:
            return
        try:
            config_path.unlink(missing_ok=True)
            shutil.rmtree(runtime_path, ignore_errors=True)
        except Exception:
            pass

    @staticmethod
    def _with_cleanup_cause(primary: ServiceError, cleanup_error: Exception) -> ServiceError:
        cause_items: list[Exception] = []
        if isinstance(primary.cause, Exception):
            cause_items.append(primary.cause)
        cause_items.append(cleanup_error)
        cause: Exception = (
            cause_items[0] if len(cause_items) == 1 else ExceptionGroup("startup and cleanup failed", cause_items)
        )
        return type(primary)(
            primary.message,
            code=primary.code,
            retryable=primary.retryable,
            details=primary.details,
            cause=cause,
        )

    def _handle(self, instance: object, error_type: type[ServiceError]) -> _LlamaCppHandle:
        handle = instance.handle if isinstance(instance, BackendInstance) else None
        if not isinstance(handle, _LlamaCppHandle) or handle.owner is not self._owner:
            raise error_type("llama.cpp backend handle is invalid", code="llama_cpp_handle_invalid")
        return handle

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise TypeError("clock must return datetime")
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _identity(file_spec: HuggingFaceFileSpec) -> dict[str, str]:
        return {
            "repo_id": file_spec.repo_id,
            "filename": file_spec.filename,
            "revision": file_spec.revision,
        }

    @staticmethod
    def _safe_pid(process: OwnedProcess) -> int | None:
        try:
            pid = process.pid
            return pid if type(pid) is int and pid > 0 else None
        except Exception:
            return None

    @staticmethod
    def _tail_file(path: Path, tail_lines: int) -> str:
        block_size = 8192
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            position = stream.tell()
            if position == 0:
                return ""
            chunks: list[bytes] = []
            newline_count = 0
            while position > 0 and newline_count <= tail_lines:
                size = min(block_size, position)
                position -= size
                stream.seek(position)
                chunk = stream.read(size)
                chunks.append(chunk)
                newline_count += chunk.count(b"\n")
            data = b"".join(reversed(chunks))
        return b"".join(data.splitlines(keepends=True)[-tail_lines:]).decode("utf-8", errors="replace")
