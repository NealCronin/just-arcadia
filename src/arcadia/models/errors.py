"""Typed error hierarchy for arcadia.models.

Every ARCADIA error carries a stable code, a human-readable message,
structured JSON-compatible details, and an indication of retryability.
Causes are retained for debugging but are never serialized across module
boundaries.

This module must not import HTTP, subprocess, filesystem, UI, or heavy
inference libraries.
"""

from __future__ import annotations

from typing import Any

from pydantic import field_validator

from arcadia.models.common import ModelBase, JsonValue, _validate_json_mapping

__all__ = [
    "ArcadiaErrorInfo",
    "ArcadiaError",
    "ConfigurationError",
    "ServiceError",
    "ServiceConflictError",
    "ServiceStartupError",
    "ServiceHealthError",
    "ServiceNotRunningError",
    "InstructionError",
    "InferenceError",
    "InferenceTimeoutError",
    "AnalysisError",
    "ArtifactError",
]


class ArcadiaErrorInfo(ModelBase):
    """Structured error information that crosses module boundaries."""

    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = {}

    @field_validator("code")
    @classmethod
    def _code_non_empty(cls, value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("code must be a non-empty string")
        return value

    @field_validator("message")
    @classmethod
    def _message_non_empty(cls, value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("message must be a non-empty string")
        return value

    @field_validator("details", mode="before")
    @classmethod
    def _validate_details(cls, value: Any) -> Any:
        return _validate_json_mapping(value)


class ArcadiaError(Exception):
    """Base typed exception for all ARCADIA failures.

    Parameters
    ----------
    message :
        Human-readable summary of the failure.
    code :
        Stable error code. When ``None``, the subclass default is used.
    retryable :
        Whether the failure may succeed on retry. When ``None``, the
        subclass default is used.
    details :
        JSON-compatible structured details, defensively copied.
    cause :
        Original exception or value, retained for debugging but not
        serialized.
    """

    #: Default code used when none is supplied at construction time.
    _default_code: str = "arcadia_error"

    #: Default retryability used when none is supplied at construction time.
    _default_retryable: bool = False

    def __init__(
        self,
        message: Any,
        *,
        code: str | None = None,
        retryable: bool | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | Any | None = None,
    ) -> None:
        super().__init__(message)
        if not isinstance(message, str):
            message = str(message)
        message = message.strip()
        if not message:
            raise ValueError("message must not be empty")

        self._message: str = message
        code_str: str = (
            code.strip() if isinstance(code, str) and code.strip() else ""
        )
        self._code: str = code_str or self._default_code
        self._retryable: bool = bool(retryable) if retryable is not None else self._default_retryable
        self._cause: BaseException | Any | None = cause

        if details is None:
            self._details: dict[str, Any] = {}
        else:
            self._details = _validate_json_mapping(details)

    @property
    def code(self) -> str:
        return self._code

    @property
    def message(self) -> str:
        return self._message

    @property
    def retryable(self) -> bool:
        return self._retryable

    @property
    def details(self) -> dict[str, Any]:
        # Return a copy so callers cannot mutate the internal state.
        return dict(self._details)

    @property
    def cause(self) -> BaseException | Any | None:
        return self._cause

    def __str__(self) -> str:
        return self._message

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._message!r}, code={self._code!r})"

    def to_info(self) -> ArcadiaErrorInfo:
        """Return an :class:`ArcadiaErrorInfo` snapshot of this error."""
        return ArcadiaErrorInfo(
            code=self._code,
            message=self._message,
            retryable=self._retryable,
            details=self._details,
        )


class ConfigurationError(ArcadiaError):
    """A configuration or user-input error."""

    _default_code = "configuration_error"


class ServiceError(ArcadiaError):
    """A generic service lifecycle or provisioning failure."""

    _default_code = "service_error"


class ServiceConflictError(ArcadiaError):
    """A service specification conflicts with the current running service."""

    _default_code = "service_conflict"


class ServiceStartupError(ArcadiaError):
    """A service failed to start."""

    _default_code = "service_startup_failed"


class ServiceHealthError(ArcadiaError):
    """A service failed its health check."""

    _default_code = "service_health_failed"


class ServiceNotRunningError(ArcadiaError):
    """An operation was attempted on a service that is not running."""

    _default_code = "service_not_running"


class InstructionError(ArcadiaError):
    """An instruction server request failed."""

    _default_code = "instruction_error"


class InferenceError(ArcadiaError):
    """A model inference request failed."""

    _default_code = "inference_error"


class InferenceTimeoutError(ArcadiaError):
    """A model inference request timed out."""

    _default_code = "inference_timeout"
    _default_retryable = True


class AnalysisError(ArcadiaError):
    """An analysis execution failed."""

    _default_code = "analysis_error"


class ArtifactError(ArcadiaError):
    """An artifact recording or retrieval error."""

    _default_code = "artifact_error"
