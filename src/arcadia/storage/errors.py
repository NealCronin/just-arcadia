"""Typed failures raised by the filesystem-backed run store."""

from __future__ import annotations

from arcadia.models import ArcadiaError

__all__ = [
    "StorageError",
    "RunNotFoundError",
    "RunConflictError",
    "RunCorruptError",
]


class StorageError(ArcadiaError):
    """A generic run-storage failure."""

    _default_code = "storage_error"


class RunNotFoundError(StorageError):
    """A requested run directory does not exist."""

    _default_code = "run_not_found"


class RunConflictError(StorageError):
    """A run path or immutable run field conflicts with existing state."""

    _default_code = "run_conflict"


class RunCorruptError(StorageError):
    """A run contains malformed, incomplete, or inconsistent persisted data."""

    _default_code = "run_corrupt"
