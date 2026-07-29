"""File I/O functions for arcadia.config.

Provides load, save, serialization, and snapshot utilities for ArcadiaConfig.
All public functions raise ConfigurationError on failure, never raw exceptions.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from arcadia.config.models import CONFIG_SCHEMA_VERSION, ArcadiaConfig
from arcadia.models import ConfigurationError

__all__ = [
    "load_config",
    "loads_config",
    "save_config",
    "dumps_config",
    "snapshot_config",
]


def _sanitize_validation_error(exc: Exception) -> list[dict[str, Any]]:
    """Extract sanitized validation details from a Pydantic ValidationError."""
    details: list[dict[str, Any]] = []
    # Pydantic ValidationError has .errors() method
    if hasattr(exc, "errors") and callable(exc.errors):
        for err in exc.errors():  # type: ignore[union-attr]
            detail = {
                "location": str(err.get("loc", "")),
                "message": str(err.get("msg", "")),
                "type": str(err.get("type", "")),
            }
            details.append(detail)
    if not details:
        details.append(
            {
                "location": "",
                "message": str(exc) if str(exc) else "validation failed",
                "type": type(exc).__name__,
            }
        )
    return details


def loads_config(text: str) -> ArcadiaConfig:
    """Parse JSON text into a validated ArcadiaConfig.

    Raises ConfigurationError for any parsing or validation failure.
    """
    if not isinstance(text, str):
        raise ConfigurationError(
            "config text must be a string",
            code="config_invalid_format",
        )

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ConfigurationError(
            f"invalid JSON: {e}",
            code="config_invalid_json",
            cause=e,
        ) from e

    if not isinstance(data, dict):
        raise ConfigurationError(
            "configuration root must be a JSON object",
            code="config_invalid_format",
        )

    # Check schema version before full validation
    version = data.get("schema_version", CONFIG_SCHEMA_VERSION)
    if version != CONFIG_SCHEMA_VERSION:
        raise ConfigurationError(
            f"unsupported schema version: {version}",
            code="config_unsupported_version",
        )

    try:
        return ArcadiaConfig.model_validate(data)
    except Exception as e:
        # Import here to avoid circular — ArcadiaConfig already imported above
        from pydantic import ValidationError

        if isinstance(e, ValidationError):
            details = _sanitize_validation_error(e)
            raise ConfigurationError(
                "configuration validation failed",
                code="config_validation_failed",
                details={"validation_errors": details},
                cause=e,
            ) from e
        if isinstance(e, ConfigurationError):
            raise
        raise ConfigurationError(
            str(e) if str(e) else "configuration validation failed",
            code="config_validation_failed",
            cause=e,
        ) from e


def dumps_config(config: ArcadiaConfig) -> str:
    """Serialize an ArcadiaConfig to deterministic, human-readable JSON.

    Uses two-space indentation, sorted keys, preserved Unicode, and a trailing newline.
    """
    if not isinstance(config, ArcadiaConfig):
        raise ConfigurationError(
            "dumps_config requires an ArcadiaConfig instance",
            code="config_validation_failed",
        )

    try:
        data = config.model_dump(mode="json")
    except Exception as e:
        raise ConfigurationError(
            f"serialization failed: {e}",
            code="config_serialization_failed",
            cause=e,
        ) from e

    try:
        return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    except (TypeError, ValueError) as e:
        raise ConfigurationError(
            f"serialization failed: {e}",
            code="config_serialization_failed",
            cause=e,
        ) from e


def load_config(path: str | os.PathLike[str]) -> ArcadiaConfig:
    """Load and validate an ArcadiaConfig from a JSON file.

    Reads explicit UTF-8. Never creates, modifies, or migrates the file.
    """
    p = Path(path)

    try:
        raw = p.read_bytes()
    except FileNotFoundError as e:
        raise ConfigurationError(
            f"configuration file not found: {path}",
            code="config_not_found",
            cause=e,
        ) from e
    except IsADirectoryError as e:
        raise ConfigurationError(
            f"configuration path is a directory: {path}",
            code="config_read_failed",
            cause=e,
        ) from e
    except PermissionError as e:
        raise ConfigurationError(
            f"permission denied reading configuration: {path}",
            code="config_read_failed",
            cause=e,
        ) from e
    except OSError as e:
        raise ConfigurationError(
            f"failed to read configuration file: {path}",
            code="config_read_failed",
            cause=e,
        ) from e

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ConfigurationError(
            f"configuration file is not valid UTF-8: {path}",
            code="config_decode_failed",
            cause=e,
        ) from e

    return loads_config(text)


def save_config(config: ArcadiaConfig, path: str | os.PathLike[str]) -> None:
    """Atomically save an ArcadiaConfig to a JSON file.

    Uses a temporary file in the destination directory, fsyncs, then replaces.
    On failure, leaves any existing file unchanged and cleans up the temp file.
    """
    p = Path(path)

    # Serialize first — fail before touching the filesystem
    content = dumps_config(config)

    # Create parent directories if needed
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise ConfigurationError(
            f"failed to create parent directories for: {path}",
            code="config_write_failed",
            cause=e,
        ) from e

    temp_path: Path | None = None
    try:
        # Write to a temporary file in the same directory
        fd, temp_str = tempfile.mkstemp(dir=str(p.parent), prefix=".arcadia-config-", suffix=".json.tmp")
        temp_path = Path(temp_str)

        try:
            os.write(fd, content.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)

        # Atomic replacement
        os.replace(str(temp_path), str(p))
        temp_path = None  # Successfully replaced, don't clean up

    except OSError as e:
        # Clean up temp file if it exists
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass

        # Try to restore existing file if we had its stat
        # (os.replace is atomic, so if it failed, the original should still be there)
        raise ConfigurationError(
            f"failed to write configuration file: {path}",
            code="config_write_failed",
            cause=e,
        ) from e


def snapshot_config(config: ArcadiaConfig) -> ArcadiaConfig:
    """Create a detached deep copy through JSON serialization and revalidation.

    Mutating nested source values does not affect the snapshot, and vice versa.
    No I/O or runtime resolution occurs.
    """
    text = dumps_config(config)
    return loads_config(text)
