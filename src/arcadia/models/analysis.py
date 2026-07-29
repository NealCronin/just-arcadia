"""Analysis domain models for arcadia.models.

These models describe a single run of a fixed-sequence research pipeline.
They carry status and stage progress but no execution logic, filesystem
access, or service behavior.

This module must not import HTTP, subprocess, filesystem, UI, or heavy
inference libraries.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, field_validator, model_validator

from arcadia.models.common import (
    ModelBase,
    _normalize_datetime,
    _validate_json_mapping,
    _validate_non_empty_str,
)
from arcadia.models.errors import ArcadiaErrorInfo

__all__ = [
    "AnalysisState",
    "StageState",
    "AnalysisSpec",
    "StageStatus",
    "AnalysisStatus",
]


class AnalysisState(StrEnum):
    """Top-level state of an analysis run."""

    PENDING = "pending"
    PREPARING = "preparing"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class StageState(StrEnum):
    """State of an individual stage within an analysis."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class AnalysisSpec(ModelBase):
    """Specification for a single analysis run."""

    tool_name: str
    input_path: str
    output_root: str
    tool_settings: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tool_name", "input_path", "output_root", mode="before")
    @classmethod
    def _validate_strings(cls, value: Any) -> str:
        return _validate_non_empty_str(value, "field")

    @field_validator("tool_settings", mode="before")
    @classmethod
    def _validate_tool_settings(cls, value: Any) -> Any:
        return _validate_json_mapping(value)


class StageStatus(ModelBase):
    """Status of one stage within an analysis run."""

    name: str
    state: StageState
    attempt: int = 1
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: ArcadiaErrorInfo | None = None

    @field_validator("name", mode="before")
    @classmethod
    def _validate_name(cls, value: Any) -> str:
        return _validate_non_empty_str(value, "name")

    @field_validator("attempt", mode="before")
    @classmethod
    def _validate_attempt(cls, value: Any) -> int:
        if isinstance(value, bool):
            raise ValueError("attempt must be an integer, not a bool")
        if not isinstance(value, int):
            raise ValueError("attempt must be an integer")
        if value < 1:
            raise ValueError("attempt must be at least 1")
        return value

    @field_validator("started_at", "finished_at", mode="before")
    @classmethod
    def _validate_timestamps(cls, value: Any) -> datetime | None:
        return _normalize_datetime(value)

    @model_validator(mode="after")
    def _validate_state_timestamps(self) -> StageStatus:
        state = self.state
        if state == StageState.PENDING:
            if self.started_at is not None or self.finished_at is not None:
                raise ValueError("pending stage must not have start or finish timestamps")
        if state == StageState.RUNNING:
            if self.started_at is None:
                raise ValueError("running stage must have a start time")
            if self.finished_at is not None:
                raise ValueError("running stage must not have a finish time")
        if state in (StageState.COMPLETED, StageState.FAILED):
            if self.started_at is None or self.finished_at is None:
                raise ValueError("terminal stage must have start and finish times")
        if state == StageState.SKIPPED:
            if (self.started_at is None) != (self.finished_at is None):
                raise ValueError("skipped stage must have either no timestamps or both")
        if state == StageState.FAILED and self.error is None:
            raise ValueError("failed stage must have an error")
        if state == StageState.COMPLETED and self.error is not None:
            raise ValueError("completed stage must not have an error")
        if state != StageState.FAILED and self.error is not None:
            raise ValueError("non-failed stage must not have an error")
        if self.started_at is not None and self.finished_at is not None:
            if self.started_at > self.finished_at:
                raise ValueError("started_at cannot be after finished_at")
        return self


class AnalysisStatus(ModelBase):
    """Full status of an analysis run, including stage breakdown."""

    run_id: str
    tool_name: str
    state: AnalysisState
    current_stage: str | None = None
    stages: tuple[StageStatus, ...] = ()
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: ArcadiaErrorInfo | None = None

    @field_validator("run_id", "tool_name", "current_stage", mode="before")
    @classmethod
    def _validate_str_fields(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _validate_non_empty_str(value, "field")

    @field_validator("started_at", "finished_at", mode="before")
    @classmethod
    def _validate_timestamps(cls, value: Any) -> datetime | None:
        return _normalize_datetime(value)

    @model_validator(mode="after")
    def _validate_state_timestamps(self) -> AnalysisStatus:
        state = self.state
        if state == AnalysisState.PENDING:
            if self.started_at is not None or self.finished_at is not None:
                raise ValueError("pending analysis must not have start or finish timestamps")
            if self.current_stage is not None:
                raise ValueError("pending analysis must not have a current stage")
        if state in (AnalysisState.PREPARING, AnalysisState.RUNNING):
            if self.started_at is None:
                raise ValueError(f"{state.value} analysis must have a start time")
            if self.finished_at is not None:
                raise ValueError(f"{state.value} analysis must not have a finish time")
        if state in (AnalysisState.COMPLETED, AnalysisState.FAILED):
            if self.started_at is None or self.finished_at is None:
                raise ValueError("completed/failed analysis must have start and finish times")
            if self.current_stage is not None:
                raise ValueError("completed/failed analysis must not have a current stage")
        if state == AnalysisState.FAILED and self.error is None:
            raise ValueError("failed analysis must have an error")
        if state == AnalysisState.COMPLETED and self.error is not None:
            raise ValueError("completed analysis must not have an error")
        if state != AnalysisState.FAILED and self.error is not None:
            raise ValueError("non-failed analysis must not have an error")
        # Stage name uniqueness
        stage_names = [s.name for s in self.stages]
        if len(stage_names) != len(set(stage_names)):
            raise ValueError("stage names must be unique")
        # Cross-checks: analysis state must be consistent with stage states
        if state == AnalysisState.COMPLETED:
            for s in self.stages:
                if s.state in (StageState.RUNNING, StageState.PENDING, StageState.FAILED):
                    raise ValueError(f"completed analysis cannot contain a stage in {s.state.value} state")
        if state == AnalysisState.FAILED:
            for s in self.stages:
                if s.state == StageState.RUNNING:
                    raise ValueError("failed analysis cannot contain a stage in running state")
        # current_stage must reference a running stage
        if self.current_stage is not None:
            current = next((s for s in self.stages if s.name == self.current_stage), None)
            if current is None:
                raise ValueError("current_stage must match a listed stage name")
            if current.state != StageState.RUNNING:
                raise ValueError("current_stage must reference a stage in running state")
        if self.started_at is not None and self.finished_at is not None:
            if self.started_at > self.finished_at:
                raise ValueError("started_at cannot be after finished_at")
        return self
