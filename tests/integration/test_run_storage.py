"""Integration tests for the real filesystem run store."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import arcadia.storage.store as store_module
from arcadia.models import (
    AnalysisSpec,
    AnalysisState,
    AnalysisStatus,
    ArtifactError,
    ArtifactRecord,
    ArtifactVisibility,
)
from arcadia.storage import RunConflictError, RunCorruptError, RunManifest, RunStore, StorageError


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


def test_create_cleans_new_run_after_manifest_fsync_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_fsync(_: int) -> None:
        raise OSError("injected fsync failure")

    monkeypatch.setattr(store_module.os, "fsync", fail_fsync)
    with pytest.raises(StorageError, match="could not create run directory") as exc_info:
        RunStore.create(tmp_path, make_manifest())
    assert exc_info.value.code == "storage_write_failed"
    assert not (tmp_path / "run-1").exists()


@pytest.mark.parametrize("failure_target", ["fsync", "replace"])
def test_manifest_failure_preserves_old_bytes_and_cleans_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_target: str
) -> None:
    store = RunStore.create(tmp_path, make_manifest())
    old_bytes = store.paths.manifest_path.read_bytes()
    replacement = make_manifest(updated_at=datetime(2025, 1, 1, 13, tzinfo=UTC))

    def fail(*_: object, **__: object) -> None:
        raise OSError(f"injected {failure_target} failure")

    monkeypatch.setattr(store_module.os, failure_target, fail)
    with pytest.raises(StorageError, match="could not atomically replace manifest") as exc_info:
        store.write_manifest(replacement)
    assert exc_info.value.code == "storage_write_failed"
    assert store.paths.manifest_path.read_bytes() == old_bytes
    assert not list(store.paths.run_dir.glob(".manifest-*.tmp"))


def test_manifest_flush_failure_preserves_old_bytes_and_cleans_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = RunStore.create(tmp_path, make_manifest())
    old_bytes = store.paths.manifest_path.read_bytes()
    original_fdopen = os.fdopen

    class FlushFailingFile:
        def __init__(self, wrapped: Any) -> None:
            self._wrapped = wrapped

        def __enter__(self) -> "FlushFailingFile":
            return self

        def __exit__(self, *args: object) -> None:
            self._wrapped.close()

        def write(self, data: bytes) -> int:
            return self._wrapped.write(data)

        def flush(self) -> None:
            raise OSError("injected flush failure")

        def fileno(self) -> int:
            return self._wrapped.fileno()

    def fail_flush(fd: int, mode: str) -> FlushFailingFile:
        return FlushFailingFile(original_fdopen(fd, mode))

    monkeypatch.setattr(store_module.os, "fdopen", fail_flush)
    with pytest.raises(StorageError):
        store.write_manifest(make_manifest(updated_at=datetime(2025, 1, 1, 13, tzinfo=UTC)))
    assert store.paths.manifest_path.read_bytes() == old_bytes
    assert not list(store.paths.run_dir.glob(".manifest-*.tmp"))


def test_manifest_short_writes_complete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = RunStore.create(tmp_path, make_manifest())
    original_fdopen = os.fdopen

    class ShortWritingFile:
        def __init__(self, wrapped: Any) -> None:
            self._wrapped = wrapped

        def __enter__(self) -> "ShortWritingFile":
            return self

        def __exit__(self, *args: object) -> None:
            self._wrapped.close()

        def write(self, data: bytes) -> int:
            return self._wrapped.write(data[:1])

        def flush(self) -> None:
            self._wrapped.flush()

        def fileno(self) -> int:
            return self._wrapped.fileno()

    def short_write(fd: int, mode: str) -> ShortWritingFile:
        return ShortWritingFile(original_fdopen(fd, mode))

    monkeypatch.setattr(store_module.os, "fdopen", short_write)
    replacement = make_manifest(updated_at=datetime(2025, 1, 1, 13, tzinfo=UTC))
    store.write_manifest(replacement)
    assert store.read_manifest() == replacement


def test_concurrent_manifest_replacements_remain_valid(tmp_path: Path) -> None:
    store = RunStore.create(tmp_path, make_manifest())
    timestamp = datetime(2025, 1, 1, 13, tzinfo=UTC)
    replacements = [
        make_manifest(updated_at=timestamp).model_copy(update={"metadata": {"writer": index}}) for index in range(20)
    ]
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(store.write_manifest, replacements))
    result = store.read_manifest()
    assert result.updated_at == timestamp
    assert result.metadata in (replacement.metadata for replacement in replacements)


def test_artifact_conflicts_and_append_failures_preserve_prior_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = RunStore.create(tmp_path, make_manifest())
    output = store.paths.outputs_dir / "nested"
    output.mkdir()
    (output / "first.txt").write_text("first")
    (output / "second.txt").write_text("second")
    first = artifact("same", "nested/first.txt")
    second = artifact("same", "nested/second.txt")
    assert store.record_artifact(first)
    with pytest.raises(ArtifactError) as exc_info:
        store.record_artifact(second)
    assert exc_info.value.code == "artifact_conflict"
    before = store.paths.artifact_index_path.read_bytes()

    def partial_then_fail(handle: Any, data: bytes) -> None:
        handle.write(data[:3])
        raise OSError("injected partial append failure")

    monkeypatch.setattr(store_module, "_write_all", partial_then_fail)
    with pytest.raises(ArtifactError) as exc_info:
        store.record_artifact(artifact("new", "nested/second.txt"))
    assert exc_info.value.code == "artifact_registration_failed"
    assert exc_info.value.details["restored"] is True
    assert store.paths.artifact_index_path.read_bytes() == before
    assert store.list_artifacts() == (first,)


def test_artifact_fsync_failure_preserves_prior_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = RunStore.create(tmp_path, make_manifest())
    output = store.paths.outputs_dir / "result.txt"
    output.write_text("result")

    def fail_fsync(_: int) -> None:
        raise OSError("injected fsync failure")

    monkeypatch.setattr(store_module.os, "fsync", fail_fsync)
    with pytest.raises(ArtifactError) as exc_info:
        store.record_artifact(artifact("a", "result.txt"), fsync=True)
    assert exc_info.value.code == "artifact_registration_failed"
    assert store.paths.artifact_index_path.read_bytes() == b""


def test_artifact_path_rejects_symlink_escape(tmp_path: Path) -> None:
    store = RunStore.create(tmp_path, make_manifest())
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "escaped.txt").write_text("outside")
    link = store.paths.outputs_dir / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    with pytest.raises(ArtifactError):
        store.artifact_path("escape/escaped.txt")
    with pytest.raises(ArtifactError):
        store.record_artifact(artifact("escaped", "escape/escaped.txt"))


@pytest.mark.parametrize(
    "index_text",
    [
        "\\n",
        "{not json}\\n",
        "[]\\n",
        '{"artifact_id":"a","unknown":true}\\n',
    ],
)
def test_artifact_index_corruption_variants_are_rejected(tmp_path: Path, index_text: str) -> None:
    store = RunStore.create(tmp_path, make_manifest())
    store.paths.artifact_index_path.write_text(index_text)
    with pytest.raises(RunCorruptError):
        store.list_artifacts()


def test_duplicate_artifact_index_ids_are_rejected(tmp_path: Path) -> None:
    store = RunStore.create(tmp_path, make_manifest())
    output = store.paths.outputs_dir / "nested"
    output.mkdir()
    (output / "result.txt").write_text("result")
    payload = artifact("duplicate").model_dump(mode="json")
    line = json.dumps(payload, sort_keys=True)
    store.paths.artifact_index_path.write_text(f"{line}\\n{line}\\n")
    with pytest.raises(RunCorruptError):
        store.list_artifacts()
