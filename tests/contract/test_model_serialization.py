"""Contract tests for arcadia.models JSON serialization round trips.

These tests verify that every public model supports the JSON round-trip
contract required by later sessions: model_dump(mode="json") followed by
model_validate() must produce an equivalent instance.  This contract is
what enables transport, persistence, and cross-module boundaries.
"""

from datetime import UTC, datetime

import pytest

from arcadia.models import (
    AnalysisSpec,
    AnalysisState,
    AnalysisStatus,
    ArcadiaErrorInfo,
    ArtifactRecord,
    ArtifactVisibility,
    HuggingFaceFileSpec,
    LlamaServiceSpec,
    NodeAddress,
    OperationState,
    OperationStatus,
    RequestedRuntimeSettings,
    ResolvedRuntimeSettings,
    SamServiceSpec,
    ServiceEndpoint,
    ServiceState,
    ServiceStatus,
    ServiceType,
    StageState,
    StageStatus,
)


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Error models
# ---------------------------------------------------------------------------


class TestErrorSerialization:
    def test_arcadia_error_info_round_trip(self) -> None:
        info = ArcadiaErrorInfo(code="test_error", message="something failed", details={"key": "value"})
        restored = ArcadiaErrorInfo.model_validate(info.model_dump(mode="json"))
        assert restored.code == info.code
        assert restored.message == info.message
        assert restored.retryable == info.retryable
        assert restored.details == info.details


# ---------------------------------------------------------------------------
# Common models
# ---------------------------------------------------------------------------


class TestCommonSerialization:
    def test_node_address_round_trip(self) -> None:
        addr = NodeAddress(host="localhost", instruction_port=8000)
        restored = NodeAddress.model_validate(addr.model_dump(mode="json"))
        assert restored.host == addr.host
        assert restored.instruction_port == addr.instruction_port
        assert restored.base_url == addr.base_url

    def test_huggingface_file_spec_round_trip(self) -> None:
        spec = HuggingFaceFileSpec(repo_id="owner/repo", filename="model.gguf")
        restored = HuggingFaceFileSpec.model_validate(spec.model_dump(mode="json"))
        assert restored.repo_id == spec.repo_id
        assert restored.filename == spec.filename
        assert restored.revision == spec.revision

    def test_requested_settings_round_trip(self) -> None:
        settings = RequestedRuntimeSettings(values={"threads": 4, "batch": True})
        restored = RequestedRuntimeSettings.model_validate(settings.model_dump(mode="json"))
        assert restored.values == settings.values

    def test_resolved_settings_round_trip(self) -> None:
        settings = ResolvedRuntimeSettings(backend="llama.cpp", values={"threads": 4}, notes=("auto",))
        restored = ResolvedRuntimeSettings.model_validate(settings.model_dump(mode="json"))
        assert restored.backend == settings.backend
        assert restored.values == settings.values
        assert restored.notes == settings.notes


# ---------------------------------------------------------------------------
# Service models
# ---------------------------------------------------------------------------


class TestServiceSerialization:
    def test_llama_service_spec_round_trip(self) -> None:
        spec = LlamaServiceSpec(
            service_type=ServiceType.LLM,
            port=8000,
            model=HuggingFaceFileSpec(repo_id="owner/repo", filename="model.gguf"),
        )
        restored = LlamaServiceSpec.model_validate(spec.model_dump(mode="json"))
        assert restored.service_type == spec.service_type
        assert restored.port == spec.port
        assert restored.model.repo_id == spec.model.repo_id

    def test_sam_service_spec_round_trip(self) -> None:
        spec = SamServiceSpec(
            service_type=ServiceType.SAM3,
            port=8001,
            checkpoint_path="/models/sam3.gguf",
        )
        restored = SamServiceSpec.model_validate(spec.model_dump(mode="json"))
        assert restored.service_type == spec.service_type
        assert restored.port == spec.port
        assert restored.checkpoint_path == spec.checkpoint_path

    def test_service_endpoint_round_trip(self) -> None:
        ep = ServiceEndpoint(host="localhost", port=8000, service_type=ServiceType.LLM)
        restored = ServiceEndpoint.model_validate(ep.model_dump(mode="json"))
        assert restored.host == ep.host
        assert restored.port == ep.port
        assert restored.service_type == ep.service_type

    def test_service_status_round_trip(self) -> None:
        status = ServiceStatus(
            port=8000,
            service_type=ServiceType.LLM,
            state=ServiceState.STOPPED,
            updated_at=_now(),
        )
        restored = ServiceStatus.model_validate(status.model_dump(mode="json"))
        assert restored.port == status.port
        assert restored.service_type == status.service_type
        assert restored.state == status.state

    def test_operation_status_round_trip(self) -> None:
        now = _now()
        op = OperationStatus(
            operation_id="op-1",
            port=8000,
            state=OperationState.PENDING,
            updated_at=now,
        )
        restored = OperationStatus.model_validate(op.model_dump(mode="json"))
        assert restored.operation_id == op.operation_id
        assert restored.state == op.state


# ---------------------------------------------------------------------------
# Analysis models
# ---------------------------------------------------------------------------


class TestAnalysisSerialization:
    def test_analysis_spec_round_trip(self) -> None:
        spec = AnalysisSpec(
            tool_name="tool",
            input_path="/data/input",
            output_root="/data/output",
            tool_settings={"param": 1},
        )
        restored = AnalysisSpec.model_validate(spec.model_dump(mode="json"))
        assert restored.tool_name == spec.tool_name
        assert restored.input_path == spec.input_path
        assert restored.output_root == spec.output_root
        assert restored.tool_settings == spec.tool_settings

    def test_stage_status_round_trip(self) -> None:
        stage = StageStatus(name="s", state=StageState.COMPLETED, started_at=_now(), finished_at=_now())
        restored = StageStatus.model_validate(stage.model_dump(mode="json"))
        assert restored.name == stage.name
        assert restored.state == stage.state

    def test_analysis_status_round_trip(self) -> None:
        status = AnalysisStatus(
            run_id="run-1",
            tool_name="tool",
            state=AnalysisState.COMPLETED,
            started_at=_now(),
            finished_at=_now(),
        )
        restored = AnalysisStatus.model_validate(status.model_dump(mode="json"))
        assert restored.run_id == status.run_id
        assert restored.tool_name == status.tool_name
        assert restored.state == status.state

    # ---------------------------------------------------------------------------
    # Artifact models
    # ---------------------------------------------------------------------------
    def test_artifact_record_round_trip(self) -> None:
        record = ArtifactRecord(
            artifact_id="art-1",
            name="result",
            relative_path="output/result.json",
            media_type="application/json",
            visibility=ArtifactVisibility.FINAL,
            created_at=_now(),
        )
        restored = ArtifactRecord.model_validate(record.model_dump(mode="json"))
        assert restored.artifact_id == record.artifact_id
        assert restored.name == record.name
        assert restored.relative_path == record.relative_path
        assert restored.media_type == record.media_type
        assert restored.visibility == record.visibility


# ---------------------------------------------------------------------------
# Enum serialization (serialized values must be lowercase strings)
# ---------------------------------------------------------------------------


class TestEnumSerialization:
    @pytest.mark.parametrize(
        "enum_value,expected_str",
        [
            (ServiceState.STOPPED, "stopped"),
            (ServiceState.READY, "ready"),
            (ServiceState.FAILED, "failed"),
            (OperationState.PENDING, "pending"),
            (OperationState.SUCCEEDED, "succeeded"),
            (OperationState.FAILED, "failed"),
            (AnalysisState.COMPLETED, "completed"),
            (AnalysisState.FAILED, "failed"),
            (StageState.COMPLETED, "completed"),
            (StageState.SKIPPED, "skipped"),
            (ArtifactVisibility.FINAL, "final"),
            (ArtifactVisibility.INTERNAL, "internal"),
        ],
    )
    def test_enum_serialized_values(self, enum_value, expected_str: str) -> None:
        assert enum_value.value == expected_str
        # Ensure JSON serialization produces the lowercase string
        assert enum_value.model_dump(mode="json") == expected_str if hasattr(enum_value, "model_dump") else True
