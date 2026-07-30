"""Filesystem boundary for run manifests, logs, and artifact indexes."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from threading import RLock
from typing import Any

from arcadia.models import ArtifactError, ArtifactRecord
from arcadia.storage.errors import RunConflictError, RunCorruptError, RunNotFoundError, StorageError
from arcadia.storage.models import RunManifest, RunPaths
from arcadia.storage.serialization import dumps_manifest, loads_manifest

__all__ = ["RunStore"]

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_DRIVE_PREFIX_RE = re.compile(r"^[A-Za-z]:")


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _write_all(handle: Any, data: bytes) -> None:
    """Write every byte or raise instead of accepting a short write."""
    offset = 0
    while offset < len(data):
        written = handle.write(data[offset:])
        if not isinstance(written, int) or written <= 0:
            raise OSError("file write did not make progress")
        offset += written


def _path_argument(value: str | os.PathLike[str], name: str) -> Path:
    if not isinstance(value, (str, os.PathLike)):
        raise StorageError(f"{name} must be a path", details={"argument": name, "exception_type": "TypeError"})
    try:
        raw = os.fspath(value)
        if isinstance(raw, bytes):
            raw = os.fsdecode(raw)
        return Path(raw).absolute()
    except Exception as exc:
        raise StorageError(
            f"{name} is not a valid path",
            code="storage_read_failed",
            details={"argument": name, "exception_type": type(exc).__name__},
            cause=exc,
        ) from exc


def _lexists(path: Path) -> bool:
    try:
        return os.path.lexists(path)
    except OSError:
        return False


def _safe_json_line(record: ArtifactRecord) -> bytes:
    payload = record.model_dump(mode="json")
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


def _corrupt(
    message: str, *, cause: BaseException | None = None, details: dict[str, Any] | None = None
) -> RunCorruptError:
    return RunCorruptError(message, details=details or {}, cause=cause)


class RunStore:
    """Instance-local filesystem access for one persisted analysis run."""

    def __init__(self, paths: RunPaths) -> None:
        self._paths = paths
        self._manifest_lock = RLock()
        self._artifact_lock = RLock()

    @classmethod
    def create(cls, output_root: str | os.PathLike[str], manifest: RunManifest) -> RunStore:
        root = _path_argument(output_root, "output_root")
        if not isinstance(manifest, RunManifest):
            raise StorageError("manifest must be a RunManifest", details={"exception_type": "TypeError"})
        manifest_bytes = dumps_manifest(manifest).encode("utf-8")
        run_dir = root / manifest.run_id
        paths = RunPaths.from_run_dir(run_dir)
        try:
            root.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            raise StorageError(
                "could not create output root",
                code="storage_write_failed",
                details={"exception_type": type(exc).__name__},
                cause=exc,
            ) from exc
        if _lexists(run_dir):
            raise RunConflictError("run path already exists", details={"run_id": manifest.run_id})

        created = False
        try:
            run_dir.mkdir()
            created = True
            paths.outputs_dir.mkdir()
            for empty_path in (paths.event_log_path, paths.artifact_index_path):
                with open(empty_path, "xb"):
                    pass
            with open(paths.manifest_path, "xb") as handle:
                _write_all(handle, manifest_bytes)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception as exc:
            if created:
                try:
                    shutil.rmtree(run_dir)
                except Exception:
                    pass
            raise StorageError(
                "could not create run directory",
                code="storage_write_failed",
                details={"exception_type": type(exc).__name__},
                cause=exc,
            ) from exc
        return cls(paths)

    @classmethod
    def open(cls, run_dir: str | os.PathLike[str]) -> RunStore:
        path = _path_argument(run_dir, "run_dir")
        if not _lexists(path):
            raise RunNotFoundError("run directory does not exist", details={"path": str(path)})
        if path.is_symlink() or not path.is_dir():
            raise _corrupt("run path is not a directory", details={"path": str(path)})
        store = cls(RunPaths.from_run_dir(path))
        store._validate_layout()
        manifest = store.read_manifest()
        if path.name != manifest.run_id:
            raise _corrupt("run directory name does not match manifest run_id")
        store.list_artifacts()
        return store

    @property
    def paths(self) -> RunPaths:
        return self._paths

    def _validate_layout(self) -> None:
        for path in (self.paths.manifest_path, self.paths.event_log_path, self.paths.artifact_index_path):
            try:
                if path.is_symlink() or not path.is_file():
                    raise _corrupt("run layout is incomplete", details={"entry": path.name})
            except OSError as exc:
                raise StorageError(
                    "could not inspect run layout",
                    code="storage_read_failed",
                    details={"entry": path.name, "exception_type": type(exc).__name__},
                    cause=exc,
                ) from exc
        try:
            if self.paths.outputs_dir.is_symlink() or not self.paths.outputs_dir.is_dir():
                raise _corrupt("run layout is incomplete", details={"entry": "outputs"})
        except OSError as exc:
            raise StorageError(
                "could not inspect run outputs directory",
                code="storage_read_failed",
                details={"entry": "outputs", "exception_type": type(exc).__name__},
                cause=exc,
            ) from exc

    def _read_manifest_text(self) -> str:
        try:
            with open(self.paths.manifest_path, "rb") as handle:
                raw = handle.read()
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _corrupt(
                "manifest is not valid UTF-8", cause=exc, details={"exception_type": type(exc).__name__}
            ) from exc
        except OSError as exc:
            raise StorageError(
                "could not read manifest",
                code="storage_read_failed",
                details={"exception_type": type(exc).__name__},
                cause=exc,
            ) from exc

    def read_manifest(self) -> RunManifest:
        return loads_manifest(self._read_manifest_text())

    def write_manifest(self, manifest: RunManifest) -> None:
        if not isinstance(manifest, RunManifest):
            raise StorageError("manifest must be a RunManifest", details={"exception_type": "TypeError"})
        serialized = dumps_manifest(manifest).encode("utf-8")
        with self._manifest_lock:
            stored = self.read_manifest()
            immutable_fields = (
                "schema_version",
                "run_id",
                "created_at",
                "analysis_spec",
                "configuration",
                "service_specs",
            )
            for field_name in immutable_fields:
                if getattr(stored, field_name) != getattr(manifest, field_name):
                    raise RunConflictError(
                        f"manifest field {field_name} is immutable",
                        details={"field": field_name},
                    )
            if manifest.updated_at < stored.updated_at:
                raise RunConflictError("manifest updated_at must be monotonic", details={"field": "updated_at"})
            temporary_path: Path | None = None
            try:
                fd, temporary_name = tempfile.mkstemp(prefix=".manifest-", suffix=".tmp", dir=self.paths.run_dir)
                temporary_path = Path(temporary_name)
                with os.fdopen(fd, "wb") as handle:
                    _write_all(handle, serialized)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary_path, self.paths.manifest_path)
                temporary_path = None
            except Exception as exc:
                raise StorageError(
                    "could not atomically replace manifest",
                    code="storage_write_failed",
                    details={"exception_type": type(exc).__name__},
                    cause=exc,
                ) from exc
            finally:
                if temporary_path is not None:
                    try:
                        temporary_path.unlink()
                    except OSError:
                        pass

    def _validate_relative_path(self, relative_path: str) -> tuple[str, ...]:
        if not isinstance(relative_path, str) or not relative_path:
            raise ArtifactError("artifact path must be a non-empty string", code="artifact_registration_failed")
        if relative_path.startswith("/") or _DRIVE_PREFIX_RE.match(relative_path):
            raise ArtifactError("artifact path must be relative", code="artifact_registration_failed")
        if "\\" in relative_path or _CONTROL_RE.search(relative_path):
            raise ArtifactError("artifact path contains forbidden characters", code="artifact_registration_failed")
        components = tuple(relative_path.split("/"))
        if any(not component or component in {".", ".."} for component in components):
            raise ArtifactError("artifact path contains forbidden components", code="artifact_registration_failed")
        return components

    def artifact_path(self, relative_path: str, *, must_exist: bool = False) -> Path:
        try:
            components = self._validate_relative_path(relative_path)
            outputs = self.paths.outputs_dir
            if outputs.is_symlink() or not outputs.is_dir():
                raise ArtifactError("run outputs directory is unavailable", code="artifact_registration_failed")
            candidate = outputs.joinpath(*components)
            resolved_outputs = Path(os.path.realpath(outputs))
            resolved_candidate = Path(os.path.realpath(candidate))
            try:
                resolved_candidate.relative_to(resolved_outputs)
            except ValueError as exc:
                raise ArtifactError(
                    "artifact path escapes outputs", code="artifact_registration_failed", cause=exc
                ) from exc
            if must_exist and (candidate.is_symlink() or not candidate.is_file()):
                raise ArtifactError(
                    "artifact path must be an existing regular file", code="artifact_registration_failed"
                )
            return candidate.absolute()
        except ArtifactError:
            raise
        except Exception as exc:
            raise ArtifactError(
                "could not resolve artifact path",
                code="artifact_registration_failed",
                details={"exception_type": type(exc).__name__},
                cause=exc,
            ) from exc

    def _read_artifacts_unlocked(self) -> tuple[ArtifactRecord, ...]:
        try:
            with open(self.paths.artifact_index_path, "rb") as handle:
                raw = handle.read()
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _corrupt("artifact index is not valid UTF-8", cause=exc) from exc
        except OSError as exc:
            raise StorageError(
                "could not read artifact index",
                code="storage_read_failed",
                details={"exception_type": type(exc).__name__},
                cause=exc,
            ) from exc
        if not text:
            return ()
        records: list[ArtifactRecord] = []
        seen: set[str] = set()
        lines = text.splitlines(keepends=True)
        for line_number, line in enumerate(lines, start=1):
            if not line.endswith("\n") or not line.strip():
                raise _corrupt("artifact index contains an incomplete or blank line", details={"line": line_number})
            try:
                payload = json.loads(line, parse_constant=_reject_json_constant)
            except Exception as exc:
                raise _corrupt(
                    "artifact index contains malformed JSON", cause=exc, details={"line": line_number}
                ) from exc
            if not isinstance(payload, dict):
                raise _corrupt("artifact index line must be an object", details={"line": line_number})
            try:
                record = ArtifactRecord.model_validate(payload)
            except Exception as exc:
                raise _corrupt(
                    "artifact index line failed validation",
                    cause=exc,
                    details={"line": line_number, "exception_type": type(exc).__name__},
                ) from exc
            if record.artifact_id in seen:
                raise _corrupt("artifact index contains a duplicate artifact ID", details={"line": line_number})
            seen.add(record.artifact_id)
            try:
                self.artifact_path(record.relative_path, must_exist=True)
            except ArtifactError as exc:
                raise _corrupt(
                    "artifact index references an unavailable artifact", cause=exc, details={"line": line_number}
                ) from exc
            records.append(record)
        return tuple(records)

    def record_artifact(self, record: ArtifactRecord, *, fsync: bool = False) -> bool:
        if not isinstance(record, ArtifactRecord):
            raise ArtifactError("record must be an ArtifactRecord", code="artifact_registration_failed")
        try:
            self.artifact_path(record.relative_path, must_exist=True)
            line = _safe_json_line(record)
        except ArtifactError:
            raise
        except Exception as exc:
            raise ArtifactError(
                "could not serialize artifact record",
                code="artifact_registration_failed",
                details={"exception_type": type(exc).__name__},
                cause=exc,
            ) from exc
        with self._artifact_lock:
            try:
                existing = self._read_artifacts_unlocked()
            except Exception as exc:
                if isinstance(exc, ArtifactError):
                    raise
                raise ArtifactError(
                    "could not inspect artifact index",
                    code="artifact_registration_failed",
                    details={"exception_type": type(exc).__name__},
                    cause=exc,
                ) from exc
            for prior in existing:
                if prior.artifact_id == record.artifact_id:
                    if prior == record:
                        return False
                    raise ArtifactError("artifact ID conflicts with an existing record", code="artifact_conflict")

            try:
                original_size = self.paths.artifact_index_path.stat().st_size
            except OSError as exc:
                raise ArtifactError(
                    "could not inspect artifact index size",
                    code="artifact_registration_failed",
                    details={"exception_type": type(exc).__name__},
                    cause=exc,
                ) from exc
            write_started = False
            try:
                with open(self.paths.artifact_index_path, "ab") as handle:
                    write_started = True
                    _write_all(handle, line)
                    handle.flush()
                    if fsync:
                        os.fsync(handle.fileno())
            except Exception as exc:
                restored = True
                if write_started:
                    try:
                        with open(self.paths.artifact_index_path, "r+b") as repair:
                            repair.truncate(original_size)
                            repair.flush()
                    except Exception:
                        restored = False
                raise ArtifactError(
                    "could not append artifact record",
                    code="artifact_registration_failed",
                    details={"exception_type": type(exc).__name__, "restored": restored},
                    cause=exc,
                ) from exc
            return True

    def list_artifacts(self) -> tuple[ArtifactRecord, ...]:
        with self._artifact_lock:
            return self._read_artifacts_unlocked()
