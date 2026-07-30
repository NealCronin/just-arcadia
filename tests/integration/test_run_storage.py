"""Integration tests for the real filesystem run store."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest

from arcadia.models import (
    AnalysisSpec,
    AnalysisState,
    AnalysisStatus,
    ArtifactError,
    ArtifactRecord,
    ArtifactVisibility,
)
from arcadia.storage import RunConflictError, RunCorruptError, RunManifest, RunStore


def make_manifest(run_id: str = "run-1", *, updated_at: datetime | None = None) -> RunManifest:
    now = datetime(2025, 1, 1, 12, tzinfo=UTC)
    return RunManifest(
        run_id=run_id,
        created_at=now,
        updated_at=updated_at or now,
        analysis_spec=AnalysisSpec(tool_name="tool", input_path="input", output_root="output"),
        analysis_status=AnalysisStatus(run_id=run_id, tool_name="tool", state=AnalysisState.PENDING),
    )


def artifact(artifact_id: str, relative_path: str = "nested/result.txt") -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id=artifact_id,
        name=Path(relative_path).name,
        relative_path=relative_path,
        media_type="text/plain",
        visibility=ArtifactVisibility.FINAL,
        created_at=datetime(2025, 1, 1, 12, tzinfo=UTC),
    )


def test_create_produces_exact_layout_and_open_is_read_only(tmp_path: Path) -> None:
    store = RunStore.create(tmp_path / "new-root", make_manifest())
    assert sorted(path.name for path in store.paths.run_dir.iterdir()) == [
        "artifacts.jsonl",
        "events.jsonl",
        "manifest.json",
        "outputs",
    ]
    assert store.paths.event_log_path.read_bytes() == b""
    assert store.paths.artifact_index_path.read_bytes() == b""
    before = {path: path.stat().st_mtime_ns for path in store.paths.run_dir.iterdir()}
    reopened = RunStore.open(store.paths.run_dir)
    after = {path: path.stat().st_mtime_ns for path in store.paths.run_dir.iterdir()}
    assert reopened.read_manifest() == store.read_manifest()
    assert before == after


def test_create_does_not_adopt_existing_paths(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    existing = root / "run-1"
    existing.mkdir()
    marker = existing / "marker"
    marker.write_text("keep")
    with pytest.raises(RunConflictError):
        RunStore.create(root, make_manifest())
    assert marker.read_text() == "keep"


def test_manifest_updates_preserve_immutable_fields(tmp_path: Path) -> None:
    store = RunStore.create(tmp_path, make_manifest())
    newer = make_manifest(updated_at=datetime(2025, 1, 1, 13, 1, tzinfo=UTC))
    store.write_manifest(newer)
    assert store.read_manifest().updated_at == newer.updated_at
    with pytest.raises(RunConflictError):
        store.write_manifest(make_manifest(run_id="other", updated_at=newer.updated_at))
    with pytest.raises(RunConflictError):
        store.write_manifest(make_manifest(updated_at=datetime(2025, 1, 1, 12, 30, tzinfo=UTC)))


def test_artifact_paths_and_incremental_recording(tmp_path: Path) -> None:
    store = RunStore.create(tmp_path, make_manifest())
    output = store.paths.outputs_dir / "nested" / "result.txt"
    output.parent.mkdir()
    output.write_text("result")
    record = artifact("a")
    assert store.record_artifact(record)
    assert not store.record_artifact(record)
    assert store.list_artifacts() == (record,)
    assert store.artifact_path("nested/result.txt", must_exist=True) == output
    with pytest.raises(ArtifactError):
        store.artifact_path("../escape.txt")
    with pytest.raises(ArtifactError):
        store.artifact_path("nested/missing.txt", must_exist=True)
    with pytest.raises(ArtifactError):
        store.artifact_path("nested\\result.txt")


def test_concurrent_artifact_records_are_complete(tmp_path: Path) -> None:
    store = RunStore.create(tmp_path, make_manifest())
    output = store.paths.outputs_dir / "results"
    output.mkdir()
    records = []
    for index in range(20):
        path = output / f"{index}.txt"
        path.write_text(str(index))
        records.append(artifact(str(index), f"results/{index}.txt"))
    with ThreadPoolExecutor(max_workers=8) as executor:
        result = list(executor.map(store.record_artifact, records))
    assert all(result)
    listed = store.list_artifacts()
    assert {record.artifact_id for record in listed} == {str(index) for index in range(20)}
    assert all(line.endswith(b"\n") for line in store.paths.artifact_index_path.read_bytes().splitlines(keepends=True))


def test_open_rejects_corrupt_or_incomplete_runs(tmp_path: Path) -> None:
    store = RunStore.create(tmp_path, make_manifest())
    store.paths.artifact_index_path.write_text("\n")
    with pytest.raises(RunCorruptError):
        RunStore.open(store.paths.run_dir)
