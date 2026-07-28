"""JSON round-trip serialization tests for arcadia.models.

Each major model family must survive model_dump(mode="json") followed by
model_validate(...) with equivalent values.
"""

from datetime import datetime, timezone

import pytest

from arcadia.models.analysis import (
    AnalysisSpec,
    AnalysisState,
    AnalysisStatus,
    StageState,
    StageStatus,
)
from arcadia.models.artifacts import ArtifactRecord
from arcadia.models.common import (
    ArtifactVisibility,
    HuggingFaceFileSpec,
    NodeAddress,
    ResolvedRuntimeSettings,
    RequestedRuntimeSettings,
)
from arcadia.models.errors import ArcadiaErrorInfo
from arcadia.models.services import (
    LlamaServiceSpec,
    SamServiceSpec,
    ServiceEndpoint,
    ServiceState,
    ServiceStatus,
    ServiceType,
)


def _now() -> datetime:
    return datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


class TestSerialization:
    """One round-trip test per model family."""

    def test_node_address(self) -> None:
        addr = NodeAddress(host="192.168.1.1", instruction_port=8000)
        restored = NodeAddress.model_validate(addr.model_dump(mode="json"))
        assert restored.base_url == addr.base_url

    def test_hf_file_spec(self) -> None:
        spec = HuggingFaceFileSpec(repo_id="owner/model", filename="model.gguf", revision="v1.0")
        restored = HuggingFaceFileSpec.model_validate(spec.model_dump(mode="json"))
        assert restored.repo_id == spec.repo_id
        assert restored.revision == spec.revision

    def test_requested_settings(self) -> None:
        settings = RequestedRuntimeSettings(values={"threads": 4, "batch": True})
        restored = RequestedRuntimeSettings.model_validate(settings.model_dump(mode="json"))
        assert restored.values == settings.values

    def test_resolved_settings(self) -> None:
        settings = ResolvedRuntimeSettings(backend="llama", values={"k": "v"}, notes=("a", "b"))
        restored = ResolvedRuntimeSettings.model_validate(settings.model_dump(mode="json"))
        assert restored.backend == settings.backend
        assert restored.notes == settings.notes

    def test_llama_service_spec(self) -> None:
        spec = LlamaServiceSpec(
            service_type=ServiceType.LLM,
            port=8000,
            model=HuggingFaceFileSpec(repo_id="owner/model", filename="model.gguf"),
        )
        restored = LlamaServiceSpec.model_validate(spec.model_dump(mode="json"))
        assert restored.port == spec.port
        assert restored.model.repo_id == spec.model.repo_id

    def test_sam_service_spec(self) -> None:
        spec = SamServiceSpec(port=8002, checkpoint_path="/path/to/model.pt")
        restored = SamServiceSpec.model_validate(spec.model_dump(mode="json"))
        assert restored.port == spec.port
        assert restored.checkpoint_path == spec.checkpoint_path

    def test_service_endpoint(self) -> None:
        ep = ServiceEndpoint(host="localhost", port=8000, service_type=ServiceType.LLM)
        restored = ServiceEndpoint.model_validate(ep.model_dump(mode="json"))
        assert restored.base_url == ep.base_url

    def test_service_status(self) -> None:
        status = ServiceStatus(
            port=8000, service_type=ServiceType.LLM, state=ServiceState.stopped,
            updated_at=_now(),
        )
        restored = ServiceStatus.model_validate(status.model_dump(mode="json"))
        assert restored.port == status.port
        assert restored.state == status.state

    def test_analysis_spec(self) -> None:
        spec = AnalysisSpec(tool_name="tool", input_path="/in", output_root="/out", tool_settings={"k": "v"})
        restored = AnalysisSpec.model_validate(spec.model_dump(mode="json"))
        assert restored.tool_name == spec.tool_name
        assert restored.tool_settings == spec.tool_settings

    def test_stage_status(self) -> None:
        stage = StageStatus(name="s", state=StageState.completed, started_at=_now(), finished_at=_now())
        restored = StageStatus.model_validate(stage.model_dump(mode="json"))
        assert restored.name == stage.name
        assert restored.state == stage.state

    def test_analysis_status(self) -> None:
        status = AnalysisStatus(
            run_id="run-1", tool_name="tool", state=AnalysisState.completed,
            started_at=_now(), finished_at=_now(),
        )
        restored = AnalysisStatus.model_validate(status.model_dump(mode="json"))
        assert restored.run_id == status.run_id
        assert restored.state == status.state

    def test_artifact_record(self) -> None:
        record = ArtifactRecord(
            artifact_id="art-1", name="out.json", relative_path="results/out.json",
            media_type="application/json", visibility=ArtifactVisibility.final,
            created_at=_now(), metadata={"k": "v"},
        )
        restored = ArtifactRecord.model_validate(record.model_dump(mode="json"))
        assert restored.artifact_id == record.artifact_id
        assert restored.relative_path == record.relative_path
        assert restored.metadata == record.metadata

    def test_error_info(self) -> None:
        info = ArcadiaErrorInfo(code="err", message="msg", retryable=True, details={"k": "v"})
        restored = ArcadiaErrorInfo.model_validate(info.model_dump(mode="json"))
        assert restored.code == info.code
        assert restored.retryable == info.retryable
        assert restored.details == info.details

    @pytest.mark.parametrize(
        "cls,kwargs",
        [
            (NodeAddress, {"host": "::1", "instruction_port": 8000}),
            (HuggingFaceFileSpec, {"repo_id": "o/m", "filename": "model.gguf"}),
            (AnalysisStatus, {"run_id": "r", "tool_name": "t", "state": "completed",
                              "started_at": "2024-06-15T12:00:00Z", "finished_at": "2024-06-15T12:00:00Z"}),
        ],
    )
    def test_round_trip_equivalence(self, cls: type, kwargs: dict) -> None:
        original = cls(**kwargs)
        restored = cls.model_validate(original.model_dump(mode="json"))
        assert restored.model_dump() == original.model_dump()
