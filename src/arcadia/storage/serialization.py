"""Deterministic JSON serialization for run manifests."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from arcadia.storage.errors import RunCorruptError, StorageError
from arcadia.storage.models import RUN_MANIFEST_SCHEMA_VERSION, RunManifest

__all__ = ["dumps_manifest", "loads_manifest"]


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _validation_details(exc: ValidationError) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for error in exc.errors():
        location = [str(part) for part in error.get("loc", ())]
        details.append(
            {
                "location": location,
                "type": str(error.get("type", "validation_error")),
                "message": str(error.get("msg", "validation failed")),
            }
        )
    return details


def dumps_manifest(manifest: RunManifest) -> str:
    """Return one deterministic, human-readable manifest JSON document."""
    try:
        if not isinstance(manifest, RunManifest):
            raise TypeError("manifest must be a RunManifest")
        payload = manifest.model_dump(mode="json")
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    except Exception as exc:
        if isinstance(exc, StorageError):
            raise
        raise StorageError(
            "manifest serialization failed",
            code="storage_serialization_failed",
            details={"exception_type": type(exc).__name__},
            cause=exc,
        ) from exc


def loads_manifest(text: str) -> RunManifest:
    """Parse and validate a manifest, translating all failures to storage errors."""
    if not isinstance(text, str):
        raise RunCorruptError(
            "manifest content must be text",
            details={"exception_type": "TypeError"},
        )
    try:
        payload = json.loads(text, parse_constant=_reject_json_constant)
    except Exception as exc:
        details: dict[str, Any] = {"exception_type": type(exc).__name__}
        if isinstance(exc, json.JSONDecodeError):
            details.update({"line": exc.lineno, "column": exc.colno})
        raise RunCorruptError("manifest JSON is malformed", details=details, cause=exc) from exc

    if not isinstance(payload, dict):
        raise RunCorruptError(
            "manifest JSON root must be an object",
            details={"root_type": type(payload).__name__},
        )
    schema_version = payload.get("schema_version")
    if type(schema_version) is not int or schema_version != RUN_MANIFEST_SCHEMA_VERSION:
        raise RunCorruptError(
            "manifest schema version is unsupported",
            details={"schema_version_type": type(schema_version).__name__, "schema_version": schema_version},
        )
    try:
        return RunManifest.model_validate(payload)
    except ValidationError as exc:
        raise RunCorruptError(
            "manifest validation failed",
            details={"errors": _validation_details(exc)},
            cause=exc,
        ) from exc
    except Exception as exc:
        raise RunCorruptError(
            "manifest validation failed",
            details={"exception_type": type(exc).__name__},
            cause=exc,
        ) from exc
