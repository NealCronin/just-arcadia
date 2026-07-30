"""Unit tests for run manifests and manifest serialization."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from arcadia.models import (
    AnalysisSpec,
    AnalysisState,
    AnalysisStatus,
    ResolvedRuntimeSettings,
    ServiceEndpoint,
    ServiceType,
)
from arcadia.storage import RunCorruptError, RunManifest, dumps_manifest, loads_manifest


def manifest(**overrides: Any) -> RunManifest:
    now = datetime(2025, 1, 1, 12, tzinfo=UTC)
    values: dict[str, Any] = {
        "run_id": "run-1",
        "created_at": now,
        "updated_at": now,
        "analysis_spec": AnalysisSpec(tool_name="tool", input_path="input", output_root="output"),
        "analysis_status": AnalysisStatus(run_id="run-1", tool_name="tool", state=AnalysisState.PENDING),
    }
    values.update(overrides)
    return RunManifest(**values)


def test_manifest_round_trip_is_lossless_and_deterministic() -> None:
    original = manifest(configuration={"unicode": "✓", "nested": [1, {"ok": True}]}, metadata={"z": 1, "a": 2})
    text = dumps_manifest(original)
    assert text.endswith("\n")
    assert '"unicode": "✓"' in text
    assert text == dumps_manifest(original)
    assert loads_manifest(text) == original


@pytest.mark.parametrize("value", [True, 1.0, "1", 2, None])
def test_schema_version_requires_exact_integer(value: object) -> None:
    with pytest.raises(ValidationError):
        manifest(schema_version=value)


@pytest.mark.parametrize("run_id", ["", ".", "..", "a/b", "a\\b", "C:run", "bad\nrun"])
def test_run_id_rejects_unsafe_components(run_id: str) -> None:
    with pytest.raises(ValidationError):
        manifest(
            run_id=run_id,
            analysis_status=AnalysisStatus(run_id=run_id or "x", tool_name="tool", state=AnalysisState.PENDING),
        )


def test_timestamps_are_utc_and_ordered() -> None:
    created = datetime(2025, 1, 1, 12, tzinfo=UTC)
    result = manifest(created_at=created, updated_at=created)
    assert result.created_at.tzinfo == UTC
    with pytest.raises(ValidationError):
        manifest(created_at=datetime(2025, 1, 1, 12), updated_at=created)
    with pytest.raises(ValidationError):
        manifest(created_at=created, updated_at=created - timedelta(seconds=1))


def test_manifest_identity_and_json_defensive_copy() -> None:
    configuration = {"nested": [{"value": 1}]}
    value = manifest(configuration=configuration)
    configuration["nested"][0]["value"] = 2
    assert value.configuration["nested"][0]["value"] == 1
    with pytest.raises(ValidationError):
        manifest(analysis_status=AnalysisStatus(run_id="different", tool_name="tool", state=AnalysisState.PENDING))
    with pytest.raises(ValidationError):
        manifest(analysis_status=AnalysisStatus(run_id="run-1", tool_name="different", state=AnalysisState.PENDING))


def test_service_records_must_reference_matching_service_specs() -> None:
    service_specs = {
        "vision": {
            "service_type": "visual_llm",
            "port": 8000,
            "model": {"repo_id": "owner/model", "filename": "model.gguf"},
            "projector": {"repo_id": "owner/model", "filename": "projector.gguf"},
        }
    }
    manifest_value = manifest(
        service_specs=service_specs,
        resolved_settings={"vision": ResolvedRuntimeSettings(backend="llama", values={"threads": 4})},
        endpoint_assignments={
            "vision": ServiceEndpoint(host="localhost", port=8000, service_type=ServiceType.VISUAL_LLM)
        },
    )
    assert manifest_value.service_specs["vision"].service_type == ServiceType.VISUAL_LLM
    with pytest.raises(ValidationError):
        manifest(service_specs=service_specs, resolved_settings={"missing": ResolvedRuntimeSettings(backend="llama")})
    with pytest.raises(ValidationError):
        manifest(
            service_specs=service_specs,
            endpoint_assignments={"vision": ServiceEndpoint(host="localhost", port=8000, service_type=ServiceType.LLM)},
        )
    with pytest.raises(ValidationError):
        manifest(service_specs={"svc": service_specs["vision"], " svc ": service_specs["vision"]})


def test_load_errors_are_typed_and_sanitized() -> None:
    with pytest.raises(RunCorruptError) as exc_info:
        loads_manifest('{"schema_version":1,"secret":"not included"')
    assert exc_info.value.code == "run_corrupt"
    assert "secret" not in str(exc_info.value)
    with pytest.raises(RunCorruptError):
        loads_manifest("[]")
