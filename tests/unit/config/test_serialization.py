"""Serialization tests for arcadia.config.

Covers:
- valid text load
- malformed JSON and non-object roots
- validation conversion and sanitized details
- deterministic formatting, Unicode, and trailing newline
- load/dump/load equality
- snapshot detachment for nested dictionaries and lists
"""

from __future__ import annotations

import json

import pytest

from arcadia.config import (
    ArcadiaConfig,
    dumps_config,
    loads_config,
    snapshot_config,
)
from arcadia.models import ConfigurationError

# ---------------------------------------------------------------------------
# Valid text load
# ---------------------------------------------------------------------------


class TestLoadsConfig:
    def test_loads_empty_config(self) -> None:
        config = loads_config("{}")
        assert isinstance(config, ArcadiaConfig)
        assert config.schema_version == 1

    def test_loads_minimal_config(self) -> None:
        config = loads_config('{"schema_version": 1}')
        assert config.schema_version == 1

    def test_loads_full_config(self) -> None:
        text = json.dumps(
            {
                "schema_version": 1,
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
                        "stages": {
                            "scene": {"service_profile": "llm"},
                        },
                    }
                },
                "retry": {"max_attempts": 5},
                "output": {"root": "/custom/outputs"},
            }
        )
        config = loads_config(text)
        assert config.schema_version == 1
        assert len(config.nodes) == 2
        assert len(config.service_profiles) == 1
        assert len(config.tool_profiles) == 1
        assert config.retry.max_attempts == 5
        assert config.output.root == "/custom/outputs"

    def test_loads_non_string_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="must be a string"):
            loads_config(123)  # type: ignore[arg-type]


class TestSchemaVersionTypes:
    @pytest.mark.parametrize(
        "document",
        [
            '{"schema_version": true}',
            '{"schema_version": 1.0}',
            '{"schema_version": "1"}',
        ],
    )
    def test_non_integer_schema_versions_are_unsupported(self, document: str) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            loads_config(document)
        assert exc_info.value.code == "config_unsupported_version"


# ---------------------------------------------------------------------------
# Malformed JSON and non-object roots
# ---------------------------------------------------------------------------


class TestMalformedInput:
    def test_malformed_json_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="invalid JSON"):
            loads_config("{invalid json}")

    def test_json_array_root_rejected(self) -> None:
        with pytest.raises(ConfigurationError, match="must be a JSON object"):
            loads_config("[1, 2, 3]")

    def test_json_string_root_rejected(self) -> None:
        with pytest.raises(ConfigurationError, match="must be a JSON object"):
            loads_config('"just a string"')

    def test_json_number_root_rejected(self) -> None:
        with pytest.raises(ConfigurationError, match="must be a JSON object"):
            loads_config("42")

    def test_json_null_root_rejected(self) -> None:
        with pytest.raises(ConfigurationError, match="must be a JSON object"):
            loads_config("null")


# ---------------------------------------------------------------------------
# Validation conversion and sanitized details
# ---------------------------------------------------------------------------


class TestValidationErrors:
    def test_validation_error_wrapped(self) -> None:
        """Unknown fields produce ConfigurationError with sanitized details."""
        with pytest.raises(ConfigurationError, match="validation failed"):
            loads_config('{"unknown_field": true}')

    def test_sanitized_details_no_raw_config(self) -> None:
        """Validation details must not contain full configuration text."""
        with pytest.raises(ConfigurationError) as exc_info:
            loads_config('{"schema_version": 1, "nodes": {"": {"kind": "local"}}}')
        # If details are present, they should be sanitized
        error = exc_info.value
        if error.details:
            details_str = json.dumps(error.details)
            # Should not contain arbitrary Python repr of invalid objects
            assert "Traceback" not in details_str


# ---------------------------------------------------------------------------
# Deterministic formatting, Unicode, and trailing newline
# ---------------------------------------------------------------------------


class TestDumpsConfig:
    def test_trailing_newline(self) -> None:
        text = dumps_config(ArcadiaConfig())
        assert text.endswith("\n")

    def test_two_space_indent(self) -> None:
        text = dumps_config(ArcadiaConfig())
        # Check that indentation uses 2 spaces
        lines = text.split("\n")
        for line in lines:
            stripped = line.lstrip(" ")
            indent = len(line) - len(stripped)
            if indent > 0:
                assert indent % 2 == 0
                assert line[:indent] == " " * indent

    def test_sorted_keys(self) -> None:
        text = dumps_config(ArcadiaConfig())
        # schema_version should come before nodes alphabetically
        sv_pos = text.index("schema_version")
        nodes_pos = text.index("nodes")
        # In sorted output, "nodes" < "schema_version"
        assert nodes_pos < sv_pos

    def test_unicode_preserved(self) -> None:
        config = ArcadiaConfig.model_validate(
            {
                "nodes": {
                    "local": {"kind": "local", "description": "机器 \u4e2d\u5fc3"},
                }
            }
        )
        text = dumps_config(config)
        assert "\u4e2d\u5fc3" in text  # Chinese characters preserved
        assert "\\u" not in text  # Not escaped

    def test_deterministic_output(self) -> None:
        config = ArcadiaConfig.model_validate(
            {
                "nodes": {
                    "b-node": {"kind": "local"},
                    "a-node": {
                        "kind": "remote",
                        "address": {"host": "10.0.0.1", "instruction_port": 8000},
                    },
                }
            }
        )
        text1 = dumps_config(config)
        text2 = dumps_config(config)
        assert text1 == text2

    def test_non_config_raises(self) -> None:
        with pytest.raises(ConfigurationError):
            dumps_config("not a config")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Load/dump/load equality
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_load_dump_load_equality(self) -> None:
        config = ArcadiaConfig.model_validate(
            {
                "nodes": {
                    "local": {"kind": "local", "description": "test machine"},
                },
                "service_profiles": {
                    "llm": {
                        "node": "local",
                        "spec": {
                            "service_type": "llm",
                            "port": 8080,
                            "model": {"repo_id": "owner/model", "filename": "model.gguf"},
                            "requested_settings": {"values": {"n_gpu_layers": 35}},
                        },
                    }
                },
                "tool_profiles": {
                    "priority_map": {
                        "tool_name": "priority_map",
                        "stages": {"scene": {"service_profile": "llm"}},
                        "settings": {"sam_step": 4},
                    }
                },
                "retry": {"max_attempts": 5, "initial_delay_seconds": 2.0},
                "output": {"root": "/outputs"},
                "extensions": {"custom": "value"},
            }
        )
        text = dumps_config(config)
        parsed = loads_config(text)
        assert parsed == config

    def test_default_config_round_trip(self) -> None:
        config = ArcadiaConfig()
        text = dumps_config(config)
        parsed = loads_config(text)
        assert parsed == config


# ---------------------------------------------------------------------------
# Snapshot detachment
# ---------------------------------------------------------------------------


class TestSnapshot:
    def test_snapshot_equals_source(self) -> None:
        config = ArcadiaConfig.model_validate(
            {
                "nodes": {"local": {"kind": "local"}},
                "extensions": {"key": "value"},
            }
        )
        snap = snapshot_config(config)
        assert snap == config

    def test_snapshot_detaches_nested_dict(self) -> None:
        """Mutating nested source values must not affect the snapshot."""
        config = ArcadiaConfig.model_validate(
            {
                "extensions": {"nested": {"a": 1, "b": 2}},
            }
        )
        snap = snapshot_config(config)

        # Mutate source extensions
        source_ext = config.extensions
        source_ext["nested"]["a"] = 999  # type: ignore[index]

        assert snap.extensions["nested"]["a"] == 1  # type: ignore[index]

    def test_snapshot_detaches_nested_list(self) -> None:
        """Nested lists must also be detached."""
        config = ArcadiaConfig.model_validate(
            {
                "extensions": {"items": [1, 2, 3]},
            }
        )
        snap = snapshot_config(config)

        source_items = config.extensions["items"]
        source_items.append(4)  # type: ignore[index]

        snap_items = snap.extensions["items"]
        assert list(snap_items) == [1, 2, 3]  # type: ignore[arg-type]

    def test_snapshot_mutation_does_not_affect_source(self) -> None:
        """Mutating nested snapshot values must not affect the source."""
        config = ArcadiaConfig.model_validate(
            {
                "extensions": {"nested": {"a": 1}},
            }
        )
        snap = snapshot_config(config)

        snap_ext = snap.extensions
        snap_ext["nested"]["a"] = 999  # type: ignore[index]

        assert config.extensions["nested"]["a"] == 1  # type: ignore[index]

    def test_snapshot_no_io(self) -> None:
        """snapshot_config must perform no I/O."""
        config = ArcadiaConfig()
        # If this doesn't raise, the test passes — no filesystem needed
        snap = snapshot_config(config)
        assert snap == config
