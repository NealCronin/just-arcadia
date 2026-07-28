"""Unit tests for arcadia.models.analysis and arcadia.models.artifacts.

Covers analysis/stage state coherence, artifact path validation, and
datetime normalization.
"""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from arcadia.models.analysis import (
    AnalysisSpec,
    AnalysisState,
    AnalysisStatus,
    StageState,
    StageStatus,
)
from arcadia.models.artifacts import ArtifactRecord
from arcadia.models.common import ArtifactVisibility
from arcadia.models.errors import ArcadiaErrorInfo


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# AnalysisSpec
# ---------------------------------------------------------------------------


class TestAnalysisSpec:
    def test_valid_spec(self) -> None:
        spec = AnalysisSpec(
            tool_name="priority_map",
            input_path="/data/input",
            output_root="/data/output",
            tool_settings={"threshold": 0.5},
        )
        assert spec.tool_name == "priority_map"
        assert spec.tool_settings == {"threshold": 0.5}

    @pytest.mark.parametrize("name,path,root", [("", "/in", "/out"), ("tool", "", "/out"), ("tool", "/in", "")])
    def test_empty_string_fields_rejected(self, name: str, path: str, root: str) -> None:
        with pytest.raises(ValidationError):
            AnalysisSpec(tool_name=name, input_path=path, output_root=root)

    def test_unknown_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AnalysisSpec(
                tool_name="tool",
                input_path="/in",
                output_root="/out",
                extra="nope",
            )


# ---------------------------------------------------------------------------
# StageStatus coherence
# ---------------------------------------------------------------------------


class TestStageStatusCoherence:
    def test_pending_no_timestamps_ok(self) -> None:
        stage = StageStatus(name="stage1", state=StageState.pending)
        assert stage.started_at is None
        assert stage.finished_at is None

    def test_pending_with_start_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StageStatus(name="s", state=StageState.pending, started_at=_now())

    def test_running_requires_start_no_finish(self) -> None:
        now = _now()
        # Missing start
        with pytest.raises(ValidationError):
            StageStatus(name="s", state=StageState.running, updated_at=None)
        # With finish is rejected (no finish_at field, but started_at + state running)
        # Actually StageStatus has started_at and finished_at
        with pytest.raises(ValidationError):
            StageStatus(name="s", state=StageState.running, started_at=now, finished_at=now)

    def test_terminal_requires_timestamps(self) -> None:
        with pytest.raises(ValidationError):
            StageStatus(name="s", state=StageState.completed, started_at=_now())

    def test_completed_rejects_error(self) -> None:
        now = _now()
        later = now + timedelta(seconds=10)
        with pytest.raises(ValidationError):
            StageStatus(
                name="s",
                state=StageState.completed,
                started_at=now,
                finished_at=later,
                error=ArcadiaErrorInfo(code="err", message="fail"),
            )

    def test_failed_requires_error(self) -> None:
        now = _now()
        later = now + timedelta(seconds=10)
        with pytest.raises(ValidationError):
            StageStatus(name="s", state=StageState.failed, started_at=now, finished_at=later)

    def test_attempt_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            StageStatus(name="s", state=StageState.pending, attempt=0)

    def test_bool_attempt_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StageStatus(name="s", state=StageState.pending, attempt=True)

    def test_started_after_finished_rejected(self) -> None:
        now = _now()
        earlier = now - timedelta(seconds=10)
        with pytest.raises(ValidationError):
            StageStatus(
                name="s",
                state=StageState.completed,
                started_at=now,
                finished_at=earlier,
            )

    def test_naive_datetime_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StageStatus(name="s", state=StageState.running, started_at=datetime(2024, 1, 1))

    def test_skipped_no_timestamps_ok(self) -> None:
        stage = StageStatus(name="s", state=StageState.skipped)
        assert stage.started_at is None
        assert stage.finished_at is None

    def test_skipped_both_timestamps_ok(self) -> None:
        now = _now()
        later = now + timedelta(seconds=10)
        stage = StageStatus(
            name="s",
            state=StageState.skipped,
            started_at=now,
            finished_at=later,
        )
        assert stage.started_at == now

    def test_skipped_only_start_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StageStatus(name="s", state=StageState.skipped, started_at=_now())


# ---------------------------------------------------------------------------
# AnalysisStatus coherence
# ---------------------------------------------------------------------------


class TestAnalysisStatusCoherence:
    def test_pending_no_timestamps_ok(self) -> None:
        status = AnalysisStatus(run_id="run-1", tool_name="tool", state=AnalysisState.pending)
        assert status.started_at is None
        assert status.finished_at is None

    def test_preparing_requires_start(self) -> None:
        with pytest.raises(ValidationError):
            AnalysisStatus(run_id="r", tool_name="t", state=AnalysisState.preparing)

    def test_running_requires_start(self) -> None:
        with pytest.raises(ValidationError):
            AnalysisStatus(run_id="r", tool_name="t", state=AnalysisState.running)

    def test_running_with_finish_rejected(self) -> None:
        now = _now()
        later = now + timedelta(seconds=10)
        with pytest.raises(ValidationError):
            AnalysisStatus(
                run_id="r",
                tool_name="t",
                state=AnalysisState.running,
                started_at=now,
                finished_at=later,
            )

    def test_completed_requires_timestamps(self) -> None:
        with pytest.raises(ValidationError):
            AnalysisStatus(
                run_id="r",
                tool_name="t",
                state=AnalysisState.completed,
                started_at=_now(),
            )

    def test_completed_rejects_error(self) -> None:
        now = _now()
        later = now + timedelta(seconds=10)
        with pytest.raises(ValidationError):
            AnalysisStatus(
                run_id="r",
                tool_name="t",
                state=AnalysisState.completed,
                started_at=now,
                finished_at=later,
                error=ArcadiaErrorInfo(code="e", message="f"),
            )

    def test_failed_requires_error(self) -> None:
        now = _now()
        later = now + timedelta(seconds=10)
        with pytest.raises(ValidationError):
            AnalysisStatus(
                run_id="r",
                tool_name="t",
                state=AnalysisState.failed,
                started_at=now,
                finished_at=later,
            )

    def test_empty_run_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AnalysisStatus(run_id="", tool_name="t", state=AnalysisState.pending)

    def test_empty_tool_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AnalysisStatus(run_id="r", tool_name="", state=AnalysisState.pending)

    def test_pending_rejects_current_stage(self) -> None:
        with pytest.raises(ValidationError):
            AnalysisStatus(
                run_id="r",
                tool_name="t",
                state=AnalysisState.pending,
                current_stage="stage1",
            )

    def test_completed_rejects_current_stage(self) -> None:
        now = _now()
        later = now + timedelta(seconds=10)
        with pytest.raises(ValidationError):
            AnalysisStatus(
                run_id="r",
                tool_name="t",
                state=AnalysisState.completed,
                started_at=now,
                finished_at=later,
                current_stage="stage1",
            )

    def test_current_stage_must_match_listed_stage(self) -> None:
        now = _now()
        with pytest.raises(ValidationError):
            AnalysisStatus(
                run_id="r",
                tool_name="t",
                state=AnalysisState.running,
                started_at=now,
                current_stage="nonexistent",
            )

    def test_duplicate_stage_names_rejected(self) -> None:
        stage = StageStatus(name="dup", state=StageState.pending)
        with pytest.raises(ValidationError):
            AnalysisStatus(
                run_id="r",
                tool_name="t",
                state=AnalysisState.pending,
                stages=(stage, stage),
            )


# ---------------------------------------------------------------------------
# ArtifactRecord path validation
# ---------------------------------------------------------------------------


class TestArtifactRecord:
    def test_valid_record(self) -> None:
        record = ArtifactRecord(
            artifact_id="art-1",
            name="output.json",
            relative_path="results/output.json",
            media_type="application/json",
            visibility=ArtifactVisibility.final,
            created_at=_now(),
        )
        assert record.artifact_id == "art-1"
        assert record.relative_path == "results/output.json"

    @pytest.mark.parametrize(
        "path",
        ["/absolute/path", "../escape.json", "dir\\model.bin", "dir/./file.txt"],
    )
    def test_unsafe_paths_rejected(self, path: str) -> None:
        with pytest.raises(ValidationError):
            ArtifactRecord(
                artifact_id="art-1",
                name="output.json",
                relative_path=path,
                media_type="application/json",
                visibility=ArtifactVisibility.final,
                created_at=_now(),
            )

    def test_empty_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ArtifactRecord(
                artifact_id="",
                name="out",
                relative_path="out",
                media_type="text",
                visibility=ArtifactVisibility.internal,
                created_at=_now(),
            )

    def test_metadata_defensively_copied(self) -> None:
        original = {"key": "value"}
        record = ArtifactRecord(
            artifact_id="art-1",
            name="out",
            relative_path="out",
            media_type="text",
            visibility=ArtifactVisibility.internal,
            created_at=_now(),
            metadata=original,
        )
        record.metadata["key"] = "changed"
        assert original == {"key": "value"}

    def test_naive_datetime_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ArtifactRecord(
                artifact_id="art-1",
                name="out",
                relative_path="out",
                media_type="text",
                visibility=ArtifactVisibility.internal,
                created_at=datetime(2024, 1, 1),
            )
