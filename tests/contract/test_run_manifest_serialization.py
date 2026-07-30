"""Public manifest serialization contract tests."""

from datetime import UTC, datetime

from arcadia.models import AnalysisSpec, AnalysisState, AnalysisStatus
from arcadia.storage import RunManifest, dumps_manifest, loads_manifest


def test_manifest_serialization_contract() -> None:
    now = datetime(2025, 1, 1, tzinfo=UTC)
    manifest = RunManifest(
        run_id="contract-run",
        created_at=now,
        updated_at=now,
        analysis_spec=AnalysisSpec(tool_name="contract", input_path="input", output_root="output"),
        analysis_status=AnalysisStatus(run_id="contract-run", tool_name="contract", state=AnalysisState.PENDING),
        configuration={"prompt": "héllo"},
    )
    serialized = dumps_manifest(manifest)
    assert serialized.endswith("\n")
    assert loads_manifest(serialized) == manifest
