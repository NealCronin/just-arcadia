"""Integration tests for arcadia.config file I/O.

Using temporary directories and failure injection, covers:
- missing and undecodable files
- normal round trip
- parent creation
- load leaves content and modification time unchanged
- atomic replacement
- simulated write and os.replace failures preserve the old file
- temporary cleanup
- typed error codes and retained causes
- no POSIX-only permission assumptions
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from arcadia.config import (
    ArcadiaConfig,
    load_config,
    save_config,
)
from arcadia.models import ConfigurationError


def _make_config() -> ArcadiaConfig:
    return ArcadiaConfig.model_validate(
        {
            "nodes": {
                "local": {"kind": "local"},
                "remote": {
                    "kind": "remote",
                    "address": {"host": "10.0.0.1", "instruction_port": 8000},
                },
            },
            "service_profiles": {
                "llm": {
                    "node": "local",
                    "spec": {
                        "service_type": "llm",
                        "port": 8080,
                        "model": {"repo_id": "owner/model", "filename": "model.gguf"},
                    },
                }
            },
            "tool_profiles": {
                "priority_map": {
                    "tool_name": "priority_map",
                    "stages": {"scene": {"service_profile": "llm"}},
                }
            },
        }
    )


# ---------------------------------------------------------------------------
# Missing and undecodable files
# ---------------------------------------------------------------------------


class TestLoadErrors:
    def test_missing_file(self) -> None:
        with pytest.raises(ConfigurationError, match="not found"):
            load_config("/nonexistent/path/config.json")

    def test_missing_file_error_code(self) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            load_config("/nonexistent/path/config.json")
        assert exc_info.value.code == "config_not_found"

    def test_missing_file_retains_cause(self) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            load_config("/nonexistent/path/config.json")
        assert exc_info.value.__cause__ is not None
        assert isinstance(exc_info.value.__cause__, FileNotFoundError)

    def test_undecodable_file(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        config_path.write_bytes(b"\x80\x81\x82\xff")  # Invalid UTF-8
        with pytest.raises(ConfigurationError, match="not valid UTF-8"):
            load_config(str(config_path))

    def test_undecodable_error_code(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        config_path.write_bytes(b"\x80\x81\x82\xff")
        with pytest.raises(ConfigurationError) as exc_info:
            load_config(str(config_path))
        assert exc_info.value.code == "config_decode_failed"

    def test_directory_path_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigurationError, match="directory"):
            load_config(str(tmp_path))


# ---------------------------------------------------------------------------
# Normal round trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_save_and_load(self, tmp_path: Path) -> None:
        config = _make_config()
        config_path = tmp_path / "config.json"

        save_config(config, str(config_path))
        loaded = load_config(str(config_path))

        assert loaded == config

    def test_save_and_load_with_path_object(self, tmp_path: Path) -> None:
        config = _make_config()
        config_path = tmp_path / "config.json"

        save_config(config, config_path)
        loaded = load_config(config_path)

        assert loaded == config


# ---------------------------------------------------------------------------
# Parent creation
# ---------------------------------------------------------------------------


class TestParentCreation:
    def test_save_creates_parent_directories(self, tmp_path: Path) -> None:
        config = ArcadiaConfig()
        nested = tmp_path / "deep" / "nested" / "dir" / "config.json"

        save_config(config, str(nested))
        assert nested.exists()

        loaded = load_config(str(nested))
        assert isinstance(loaded, ArcadiaConfig)


# ---------------------------------------------------------------------------
# Load leaves content and modification time unchanged
# ---------------------------------------------------------------------------


class TestLoadNonMutating:
    def test_load_does_not_modify_content(self, tmp_path: Path) -> None:
        config = _make_config()
        config_path = tmp_path / "config.json"
        save_config(config, str(config_path))

        original_content = config_path.read_bytes()
        original_mtime = config_path.stat().st_mtime

        # Load multiple times
        for _ in range(3):
            load_config(str(config_path))

        assert config_path.read_bytes() == original_content
        # Modification time should not have changed (within tolerance)
        assert abs(config_path.stat().st_mtime - original_mtime) < 1.0

    def test_load_does_not_truncate_on_failure(self, tmp_path: Path) -> None:
        config = _make_config()
        config_path = tmp_path / "config.json"
        save_config(config, str(config_path))

        # Try to load invalid content — replace file with bad JSON
        config_path.write_text("not json")
        with pytest.raises(ConfigurationError):
            load_config(str(config_path))

        # File should still have the bad content we wrote, not be truncated
        assert config_path.read_text() == "not json"


# ---------------------------------------------------------------------------
# Atomic replacement
# ---------------------------------------------------------------------------


class TestAtomicReplacement:
    def test_atomic_replace_updates_file(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"

        # Save initial config
        config1 = ArcadiaConfig.model_validate({"nodes": {"a": {"kind": "local"}}})
        save_config(config1, str(config_path))

        # Save updated config
        config2 = ArcadiaConfig.model_validate({"nodes": {"b": {"kind": "local"}}})
        save_config(config2, str(config_path))

        # Load and verify
        loaded = load_config(str(config_path))
        assert loaded == config2
        assert "b" in loaded.nodes

    def test_no_temporary_files_left(self, tmp_path: Path) -> None:
        config = ArcadiaConfig()
        config_path = tmp_path / "config.json"

        save_config(config, str(config_path))

        # Check no temp files remain
        temp_files = list(tmp_path.glob(".arcadia-config-*"))
        assert len(temp_files) == 0


# ---------------------------------------------------------------------------
# Failure injection: write and os.replace failures preserve old file
# ---------------------------------------------------------------------------


class TestFailureInjection:
    def test_write_failure_preserves_existing(self, tmp_path: Path, monkeypatch: Any) -> None:
        """Simulated write failure must not destroy the existing file."""
        config_path = tmp_path / "config.json"

        # Save initial config
        original = ArcadiaConfig()
        save_config(original, str(config_path))
        original_content = config_path.read_bytes()

        # Monkeypatch os.write to fail
        def failing_write(fd: int, data: bytes) -> int:
            raise OSError("simulated write failure")

        monkeypatch.setattr(os, "write", failing_write)

        new_config = ArcadiaConfig.model_validate({"nodes": {"new": {"kind": "local"}}})
        with pytest.raises(ConfigurationError, match="write"):
            save_config(new_config, str(config_path))

        # Original file should still be intact
        assert config_path.read_bytes() == original_content

    def test_partial_writes_are_completed(self, tmp_path: Path, monkeypatch: Any) -> None:
        """A successful short os.write result must be followed by more writes."""
        config_path = tmp_path / "config.json"
        real_write = os.write
        write_calls = 0

        def partial_write(fd: int, data: bytes) -> int:
            nonlocal write_calls
            write_calls += 1
            return real_write(fd, data[:1])

        monkeypatch.setattr(os, "write", partial_write)

        expected = ArcadiaConfig()
        save_config(expected, config_path)

        assert write_calls > 1
        assert load_config(config_path) == expected

    def test_replace_failure_preserves_existing(self, tmp_path: Path, monkeypatch: Any) -> None:
        """Simulated os.replace failure must not destroy the existing file."""
        config_path = tmp_path / "config.json"

        # Save initial config
        original = ArcadiaConfig()
        save_config(original, str(config_path))
        original_content = config_path.read_bytes()

        replace_called = False

        def failing_replace(src: str, dst: str) -> None:
            nonlocal replace_called
            replace_called = True
            raise OSError("simulated replace failure")

        monkeypatch.setattr(os, "replace", failing_replace)

        new_config = ArcadiaConfig.model_validate({"nodes": {"new": {"kind": "local"}}})
        with pytest.raises(ConfigurationError, match="write"):
            save_config(new_config, str(config_path))

        assert replace_called
        # Original file should still be intact
        assert config_path.read_bytes() == original_content

    def test_temporary_cleaned_up_on_failure(self, tmp_path: Path, monkeypatch: Any) -> None:
        """Failed writes must clean up temporary files."""
        config_path = tmp_path / "config.json"

        # Monkeypatch os.replace to fail after write succeeds
        def failing_replace(src: str, dst: str) -> None:
            raise OSError("simulated replace failure")

        monkeypatch.setattr(os, "replace", failing_replace)

        config = ArcadiaConfig()
        with pytest.raises(ConfigurationError):
            save_config(config, str(config_path))

        # No temp files should remain
        temp_files = list(tmp_path.glob(".arcadia-config-*"))
        assert len(temp_files) == 0


# ---------------------------------------------------------------------------
# Typed error codes and retained causes
# ---------------------------------------------------------------------------


class TestErrorCodes:
    def test_invalid_json_error_code(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        config_path.write_text("not json")

        with pytest.raises(ConfigurationError) as exc_info:
            load_config(str(config_path))

        assert exc_info.value.code == "config_invalid_json"
        assert exc_info.value.__cause__ is not None

    def test_validation_error_code(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"unknown_field": True}))

        with pytest.raises(ConfigurationError) as exc_info:
            load_config(str(config_path))

        assert exc_info.value.code == "config_validation_failed"

    def test_unsupported_version_error_code(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"schema_version": 99}))

        with pytest.raises(ConfigurationError) as exc_info:
            load_config(str(config_path))

        assert exc_info.value.code == "config_unsupported_version"


# ---------------------------------------------------------------------------
# No POSIX-only permission assumptions
# ---------------------------------------------------------------------------


class TestNoPosixAssumptions:
    def test_save_to_readonly_parent_fails_gracefully(self, tmp_path: Path, monkeypatch: Any) -> None:
        """Write failures in parent directory must raise ConfigurationError, not OS-specific errors."""
        config = ArcadiaConfig()
        target = tmp_path / "readonly" / "config.json"

        # Create parent but make it read-only
        target.parent.mkdir(exist_ok=True)
        os.chmod(str(target.parent), 0o444)

        try:
            with pytest.raises(ConfigurationError):
                save_config(config, str(target))
        finally:
            # Restore permissions for cleanup
            os.chmod(str(target.parent), 0o755)
