from datetime import UTC, datetime
from pathlib import Path

from arcadia.hardware import (
    CpuInfo,
    HardwareCapabilities,
    MemoryInfo,
    OperatingSystem,
    PlatformInfo,
    resolve_runtime_settings,
)
from arcadia.models import (
    AnalysisSpec,
    AnalysisState,
    AnalysisStatus,
    HuggingFaceFileSpec,
    LlamaServiceSpec,
    RequestedRuntimeSettings,
    ServiceType,
)
from arcadia.storage import RunManifest, RunStore


def test_hardware_and_resolved_settings_survive_manifest_round_trip(tmp_path: Path) -> None:
    now = datetime(2025, 1, 1, tzinfo=UTC)
    spec = LlamaServiceSpec(
        service_type=ServiceType.LLM,
        port=8080,
        model=HuggingFaceFileSpec(repo_id="org/model", filename="model.gguf"),
        requested_settings=RequestedRuntimeSettings(values={"threads": 2}),
    )
    capabilities = HardwareCapabilities(
        detected_at=now,
        platform=PlatformInfo(
            operating_system=OperatingSystem.LINUX,
            release="6.0",
            version="build",
            machine="x86_64",
            python_version="3.11",
        ),
        cpu=CpuInfo(logical_cores=4, architecture="x86_64"),
        memory=MemoryInfo(total_bytes=32, available_bytes=16),
    )
    manifest = RunManifest(
        run_id="hardware-run",
        created_at=now,
        updated_at=now,
        analysis_spec=AnalysisSpec(tool_name="tool", input_path="input", output_root="output"),
        analysis_status=AnalysisStatus(run_id="hardware-run", tool_name="tool", state=AnalysisState.PENDING),
        service_specs={"llm": spec},
        resolved_settings={"llm": resolve_runtime_settings(spec, capabilities)},
        hardware=capabilities.model_dump(mode="json"),
    )
    store = RunStore.create(tmp_path, manifest)
    reread = store.read_manifest()
    assert HardwareCapabilities.model_validate(reread.hardware) == capabilities
    assert reread.resolved_settings == manifest.resolved_settings
