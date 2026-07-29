"""Unit tests for arcadia.models.services.

Covers service spec projector rules, parse_service_spec union dispatch,
service/operation state coherence, and datetime normalization.
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from arcadia.models.common import (
    HuggingFaceFileSpec,
    ResolvedRuntimeSettings,
)
from arcadia.models.errors import ArcadiaErrorInfo
from arcadia.models.services import (
    LlamaServiceSpec,
    OperationState,
    OperationStatus,
    SamServiceSpec,
    ServiceEndpoint,
    ServiceState,
    ServiceStatus,
    ServiceType,
    parse_service_spec,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _spec(st: ServiceType, with_projector: bool = False, port: int = 8000) -> LlamaServiceSpec:
    kwargs: dict = {
        "service_type": st,
        "port": port,
        "model": HuggingFaceFileSpec(repo_id="owner/model", filename="model.gguf"),
    }
    if with_projector:
        kwargs["projector"] = HuggingFaceFileSpec(repo_id="owner/proj", filename="proj.gguf")
    return LlamaServiceSpec(**kwargs)


class TestProjectorRules:
    def test_llm_without_projector_ok(self) -> None:
        spec = _spec(ServiceType.LLM)
        assert spec.projector is None

    def test_visual_llm_with_projector_ok(self) -> None:
        spec = _spec(ServiceType.VISUAL_LLM, with_projector=True)
        assert spec.projector is not None

    def test_visual_llm_without_projector_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _spec(ServiceType.VISUAL_LLM)

    def test_llm_with_projector_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _spec(ServiceType.LLM, with_projector=True)


class TestParseServiceSpec:
    def test_parse_llm(self) -> None:
        spec = parse_service_spec(
            {
                "service_type": "llm",
                "port": 8000,
                "model": {"repo_id": "owner/model", "filename": "model.gguf"},
            }
        )
        assert isinstance(spec, LlamaServiceSpec)
        assert spec.service_type == ServiceType.LLM

    def test_parse_visual_llm(self) -> None:
        spec = parse_service_spec(
            {
                "service_type": "visual_llm",
                "port": 8001,
                "model": {"repo_id": "owner/model", "filename": "model.gguf"},
                "projector": {"repo_id": "owner/proj", "filename": "proj.gguf"},
            }
        )
        assert isinstance(spec, LlamaServiceSpec)
        assert spec.service_type == ServiceType.VISUAL_LLM

    def test_parse_sam(self) -> None:
        spec = parse_service_spec({"service_type": "sam3", "port": 8002, "checkpoint_path": "/path/to/model.pt"})
        assert isinstance(spec, SamServiceSpec)
        assert spec.service_type == ServiceType.SAM3

    def test_unknown_type_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown service_type"):
            parse_service_spec(
                {"service_type": "bogus", "port": 8000, "model": {"repo_id": "x/y", "filename": "m.gguf"}}
            )

    def test_unknown_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            parse_service_spec(
                {
                    "service_type": "llm",
                    "port": 8000,
                    "model": {"repo_id": "owner/model", "filename": "model.gguf"},
                    "extra": "nope",
                }
            )


class TestServiceEndpoint:
    def test_ipv4_base_url(self) -> None:
        ep = ServiceEndpoint(host="192.168.1.1", port=8000, service_type=ServiceType.LLM)
        assert ep.base_url == "http://192.168.1.1:8000"

    def test_ipv6_brackets(self) -> None:
        ep = ServiceEndpoint(host="::1", port=8000, service_type=ServiceType.LLM)
        assert ep.base_url == "http://[::1]:8000"

    def test_bool_port_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ServiceEndpoint(host="localhost", port=True, service_type=ServiceType.LLM)


class TestServiceStatusCoherence:
    def test_ready_requires_endpoint_and_settings(self) -> None:
        now = _now()
        ep = ServiceEndpoint(host="localhost", port=8000, service_type=ServiceType.LLM)
        rs = ResolvedRuntimeSettings(backend="llama", values={})
        # Missing endpoint
        with pytest.raises(ValidationError):
            ServiceStatus(
                port=8000,
                service_type=ServiceType.LLM,
                state=ServiceState.READY,
                resolved_settings=rs,
                updated_at=now,
            )
        # Missing resolved settings
        with pytest.raises(ValidationError):
            ServiceStatus(
                port=8000,
                service_type=ServiceType.LLM,
                state=ServiceState.READY,
                endpoint=ep,
                updated_at=now,
            )
        # Both present: OK
        ServiceStatus(
            port=8000,
            service_type=ServiceType.LLM,
            state=ServiceState.READY,
            endpoint=ep,
            resolved_settings=rs,
            updated_at=now,
        )

    def test_failed_requires_error(self) -> None:
        with pytest.raises(ValidationError):
            ServiceStatus(
                port=8000,
                service_type=ServiceType.LLM,
                state=ServiceState.FAILED,
                updated_at=_now(),
            )

    def test_stopped_rejects_endpoint(self) -> None:
        with pytest.raises(ValidationError):
            ServiceStatus(
                port=8000,
                service_type=ServiceType.LLM,
                state=ServiceState.STOPPED,
                endpoint=ServiceEndpoint(host="localhost", port=8000, service_type=ServiceType.LLM),
                updated_at=_now(),
            )

    def test_started_after_updated_rejected(self) -> None:
        now = _now()
        later = now + timedelta(seconds=10)
        with pytest.raises(ValidationError):
            ServiceStatus(
                port=8000,
                service_type=ServiceType.LLM,
                state=ServiceState.READY,
                endpoint=ServiceEndpoint(host="localhost", port=8000, service_type=ServiceType.LLM),
                resolved_settings=ResolvedRuntimeSettings(backend="llama", values={}),
                started_at=later,
                updated_at=now,
            )

    def test_naive_datetime_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ServiceStatus(
                port=8000,
                service_type=ServiceType.LLM,
                state=ServiceState.STOPPED,
                updated_at=datetime(2024, 1, 1),
            )

    def test_utc_normalization(self) -> None:
        from datetime import timedelta

        tz = timezone(timedelta(hours=5))
        status = ServiceStatus(
            port=8000,
            service_type=ServiceType.LLM,
            state=ServiceState.STOPPED,
            updated_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=tz),
        )
        assert status.updated_at.tzinfo is UTC
        assert status.updated_at.hour == 7  # 12 - 5 = 7

    def test_ready_rejects_error(self) -> None:
        now = _now()
        with pytest.raises(ValidationError):
            ServiceStatus(
                port=8000,
                service_type=ServiceType.LLM,
                state=ServiceState.READY,
                endpoint=ServiceEndpoint(host="localhost", port=8000, service_type=ServiceType.LLM),
                resolved_settings=ResolvedRuntimeSettings(backend="llama", values={}),
                error=ArcadiaErrorInfo(code="err", message="fail"),
                updated_at=now,
            )

    @pytest.mark.parametrize(
        "state",
        [
            ServiceState.RESOLVING,
            ServiceState.DOWNLOADING,
            ServiceState.STARTING,
            ServiceState.STOPPING,
            ServiceState.STOPPED,
        ],
    )
    def test_non_failed_states_reject_error(self, state: ServiceState) -> None:
        now = _now()
        with pytest.raises(ValidationError):
            ServiceStatus(
                port=8000,
                service_type=ServiceType.LLM,
                state=state,
                error=ArcadiaErrorInfo(code="err", message="fail"),
                updated_at=now,
            )

    def test_endpoint_port_mismatch_rejected(self) -> None:
        now = _now()
        with pytest.raises(ValidationError):
            ServiceStatus(
                port=8000,
                service_type=ServiceType.LLM,
                state=ServiceState.STOPPED,
                endpoint=ServiceEndpoint(host="localhost", port=8081, service_type=ServiceType.LLM),
                updated_at=now,
            )

    def test_endpoint_service_type_mismatch_rejected(self) -> None:
        now = _now()
        with pytest.raises(ValidationError):
            ServiceStatus(
                port=8000,
                service_type=ServiceType.LLM,
                state=ServiceState.STOPPED,
                endpoint=ServiceEndpoint(host="localhost", port=8000, service_type=ServiceType.SAM3),
                updated_at=now,
            )

    def test_requested_spec_port_mismatch_rejected(self) -> None:
        now = _now()
        spec = LlamaServiceSpec(
            service_type=ServiceType.LLM,
            port=8081,
            model=HuggingFaceFileSpec(repo_id="o/m", filename="model.gguf"),
        )
        with pytest.raises(ValidationError):
            ServiceStatus(
                port=8000,
                service_type=ServiceType.LLM,
                state=ServiceState.STOPPED,
                requested_spec=spec,
                updated_at=now,
            )

    def test_requested_spec_service_type_mismatch_rejected(self) -> None:
        now = _now()
        spec = SamServiceSpec(port=8000, checkpoint_path="/path/to/model.pt")
        with pytest.raises(ValidationError):
            ServiceStatus(
                port=8000,
                service_type=ServiceType.LLM,
                state=ServiceState.STOPPED,
                requested_spec=spec,
                updated_at=now,
            )


class TestOperationStatusCoherence:
    def test_pending_no_timestamps(self) -> None:
        with pytest.raises(ValidationError):
            OperationStatus(
                operation_id="op-1",
                port=8000,
                state=OperationState.PENDING,
                started_at=_now(),
                updated_at=_now(),
            )

    def test_running_requires_start(self) -> None:
        with pytest.raises(ValidationError):
            OperationStatus(
                operation_id="op-1",
                port=8000,
                state=OperationState.RUNNING,
                updated_at=_now(),
            )

    def test_failed_requires_error(self) -> None:
        now = _now()
        later = now + timedelta(seconds=10)
        with pytest.raises(ValidationError):
            OperationStatus(
                operation_id="op-1",
                port=8000,
                state=OperationState.FAILED,
                started_at=now,
                updated_at=later,
                finished_at=later,
            )

    def test_succeeded_rejects_error(self) -> None:
        now = _now()
        later = now + timedelta(seconds=10)
        with pytest.raises(ValidationError):
            OperationStatus(
                operation_id="op-1",
                port=8000,
                state=OperationState.SUCCEEDED,
                started_at=now,
                updated_at=later,
                finished_at=later,
                error=ArcadiaErrorInfo(code="err", message="fail"),
            )

    @pytest.mark.parametrize("state", [OperationState.PENDING, OperationState.RUNNING])
    def test_non_failed_states_reject_error(self, state: OperationState) -> None:
        now = _now()
        kwargs: dict[str, object] = {
            "operation_id": "op-1",
            "port": 8000,
            "state": state,
            "updated_at": now,
            "error": ArcadiaErrorInfo(code="err", message="fail"),
        }
        if state == OperationState.RUNNING:
            kwargs["started_at"] = now
        with pytest.raises(ValidationError):
            OperationStatus(**kwargs)  # type: ignore[arg-type]

    @pytest.mark.parametrize("progress", [-0.1, 1.1, True])
    def test_progress_out_of_range(self, progress: object) -> None:
        with pytest.raises(ValidationError):
            OperationStatus(
                operation_id="op-1",
                port=8000,
                state=OperationState.RUNNING,
                progress=progress,  # type: ignore[arg-type]
                started_at=_now(),
                updated_at=_now(),
            )

    def test_empty_operation_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            OperationStatus(
                operation_id="",
                port=8000,
                state=OperationState.PENDING,
                updated_at=_now(),
            )

    def test_bool_port_rejected(self) -> None:
        with pytest.raises(ValidationError):
            OperationStatus(
                operation_id="op-1",
                port=True,
                state=OperationState.PENDING,
                updated_at=_now(),
            )
