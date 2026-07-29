"""Unit tests for arcadia.models.errors.

Covers typed error defaults/retryability, cause retention, to_info(),
JSON compatibility of details, and exception hierarchy.
"""

import pytest
from pydantic import ValidationError

from arcadia.models.errors import (
    AnalysisError,
    ArcadiaError,
    ArcadiaErrorInfo,
    ArtifactError,
    ConfigurationError,
    InferenceError,
    InferenceTimeoutError,
    InstructionError,
    ServiceConflictError,
    ServiceError,
    ServiceHealthError,
    ServiceNotRunningError,
    ServiceStartupError,
)

ERROR_TABLE = [
    (ConfigurationError, "configuration_error", False),
    (ServiceError, "service_error", False),
    (ServiceConflictError, "service_conflict", False),
    (ServiceStartupError, "service_startup_failed", False),
    (ServiceHealthError, "service_health_failed", False),
    (ServiceNotRunningError, "service_not_running", False),
    (InstructionError, "instruction_error", False),
    (InferenceError, "inference_error", False),
    (InferenceTimeoutError, "inference_timeout", True),
    (AnalysisError, "analysis_error", False),
    (ArtifactError, "artifact_error", False),
]


class TestErrorDefaults:
    @pytest.mark.parametrize("error_class,expected_code,expected_retryable", ERROR_TABLE)
    def test_default_code_and_retryability(
        self, error_class: type, expected_code: str, expected_retryable: bool
    ) -> None:
        err = error_class("something broke")
        assert err.code == expected_code
        assert err.retryable is expected_retryable

    def test_inference_timeout_is_retryable(self) -> None:
        assert InferenceTimeoutError("timed out").retryable is True

    def test_other_errors_are_not_retryable(self) -> None:
        assert ConfigurationError("bad").retryable is False


class TestArcadiaErrorBehavior:
    def test_str_returns_message(self) -> None:
        assert str(ArcadiaError("boom")) == "boom"

    def test_str_returns_message_with_code(self) -> None:
        err = ArcadiaError("boom", code="custom")
        assert str(err) == "boom"
        assert err.code == "custom"

    @pytest.mark.parametrize("message", ["", "   "])
    def test_empty_message_rejected(self, message: str) -> None:
        with pytest.raises(ValueError):
            ArcadiaError(message)

    def test_custom_code_and_retryable(self) -> None:
        err = ArcadiaError("boom", code="my_error", retryable=True)
        assert err.code == "my_error"
        assert err.retryable is True

    def test_message_normalization_in_args(self) -> None:
        err = ArcadiaError("  boom  ")
        assert str(err) == "boom"
        assert err.args[0] == "boom"
        assert err.message == "boom"


class TestCauseRetention:
    def test_cause_retained(self) -> None:
        inner = ValueError("original")
        outer = ArcadiaError("wrapper", cause=inner)
        assert outer.cause is inner

    def test_no_cause_defaults_none(self) -> None:
        assert ArcadiaError("boom").cause is None


class TestToInfo:
    def test_to_info_basic(self) -> None:
        err = ArcadiaError("boom", code="custom", retryable=True, details={"k": "v"})
        info = err.to_info()
        assert isinstance(info, ArcadiaErrorInfo)
        assert info.code == "custom"
        assert info.message == "boom"
        assert info.retryable is True
        assert info.details == {"k": "v"}

    def test_to_info_with_subclass_defaults(self) -> None:
        info = ConfigurationError("bad").to_info()
        assert info.code == "configuration_error"
        assert info.retryable is False

    def test_to_info_omits_cause(self) -> None:
        err = ArcadiaError("boom", cause=ValueError("inner"))
        info = err.to_info()
        dumped = info.model_dump()
        assert "cause" not in dumped


class TestDetails:
    def test_details_default_empty(self) -> None:
        assert ArcadiaError("boom").details == {}

    @pytest.mark.parametrize(
        "value",
        [float("nan"), float("inf"), b"bytes", {1, 2, 3}, object()],
    )
    def test_non_json_details_rejected(self, value: object) -> None:
        with pytest.raises((ValidationError, ValueError)):
            ArcadiaError("boom", details={"k": value})

    def test_details_defensively_copied(self) -> None:
        err = ArcadiaError("boom", details={"key": "value"})
        d = err.details
        d["key"] = "changed"
        assert err.details == {"key": "value"}

    def test_details_deep_copied_nested(self) -> None:
        err = ArcadiaError("boom", details={"nested": [1, 2, 3]})
        d = err.details
        d["nested"].append(4)
        assert err.details == {"nested": [1, 2, 3]}


class TestArcadiaErrorInfo:
    def test_valid_construction(self) -> None:
        info = ArcadiaErrorInfo(code="test", message="msg", retryable=True, details={"k": "v"})
        assert info.code == "test"
        assert info.retryable is True

    @pytest.mark.parametrize("code", ["", "  "])
    def test_empty_code_rejected(self, code: str) -> None:
        with pytest.raises(ValidationError):
            ArcadiaErrorInfo(code=code, message="msg")

    def test_empty_message_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ArcadiaErrorInfo(code="test", message="  ")

    def test_unknown_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ArcadiaErrorInfo(code="test", message="msg", extra="nope")

    def test_json_round_trip(self) -> None:
        info = ArcadiaErrorInfo(code="test", message="msg", retryable=True, details={"k": "v"})
        restored = ArcadiaErrorInfo.model_validate(info.model_dump(mode="json"))
        assert restored.code == info.code
        assert restored.retryable == info.retryable
        assert restored.details == info.details


class TestExceptionHierarchy:
    def test_is_exception(self) -> None:
        assert isinstance(ArcadiaError("boom"), Exception)

    def test_subclass_is_base_error(self) -> None:
        err = ConfigurationError("bad")
        assert isinstance(err, ArcadiaError)
        assert isinstance(err, ConfigurationError)

    def test_can_be_raised_and_caught_as_base(self) -> None:
        with pytest.raises(ArcadiaError):
            raise InferenceError("failed")
