"""Unit tests for arcadia.config models.

Covers:
- default config
- valid/invalid local and remote nodes
- second local node rejection
- name trimming and control-character rejection
- valid LLM, visual-LLM, and SAM profiles
- unknown node and service-profile references
- profile reuse and same-port alternatives
- requested settings preservation
- root/nested extensions and invalid JSON values
- unknown field rejection
- retry boundaries and boolean rejection
- output validation without path access
- version 1 and unsupported versions
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from arcadia.config import (
    ArcadiaConfig,
    NodeConfig,
    NodeKind,
    OutputSettings,
    RetryPolicy,
    StageBinding,
    ToolProfile,
)
from arcadia.models import ConfigurationError

# ---------------------------------------------------------------------------
# Default config
# ---------------------------------------------------------------------------


class TestDefaultConfig:
    def test_default_config_creates(self) -> None:
        config = ArcadiaConfig()
        assert config.schema_version == 1
        assert config.nodes == {}
        assert config.service_profiles == {}
        assert config.tool_profiles == {}
        assert isinstance(config.retry, RetryPolicy)
        assert isinstance(config.output, OutputSettings)

    def test_default_retry_policy(self) -> None:
        config = ArcadiaConfig()
        assert config.retry.max_attempts == 3
        assert config.retry.initial_delay_seconds == 1.0
        assert config.retry.multiplier == 2.0
        assert config.retry.maximum_delay_seconds == 10.0

    def test_default_output_settings(self) -> None:
        config = ArcadiaConfig()
        assert config.output.root == "./outputs"


# ---------------------------------------------------------------------------
# Node validation
# ---------------------------------------------------------------------------


class TestNodeValidation:
    def test_valid_local_node(self) -> None:
        node = NodeConfig(kind=NodeKind.LOCAL)
        assert node.kind == NodeKind.LOCAL
        assert node.address is None

    def test_valid_local_node_with_description(self) -> None:
        node = NodeConfig(kind=NodeKind.LOCAL, description="my machine")
        assert node.description == "my machine"

    def test_local_node_rejects_address(self) -> None:
        with pytest.raises(ValidationError):
            NodeConfig(kind=NodeKind.LOCAL, address={"host": "localhost", "instruction_port": 8000})

    def test_valid_remote_node(self) -> None:
        node = NodeConfig(
            kind=NodeKind.REMOTE,
            address={"host": "192.168.1.10", "instruction_port": 8000},
        )
        assert node.kind == NodeKind.REMOTE

    def test_address_rejects_arbitrary_object(self) -> None:
        class FakeAddress:
            host = "localhost"
            instruction_port = 8000

        with pytest.raises(ValidationError):
            NodeConfig(kind=NodeKind.REMOTE, address=FakeAddress())

    def test_address_is_node_address(self) -> None:
        node = NodeConfig(
            kind=NodeKind.REMOTE,
            address={"host": "localhost", "instruction_port": 8000},
        )
        assert type(node.address).__name__ == "NodeAddress"
        assert node.address is not None

    def test_remote_node_requires_address(self) -> None:
        with pytest.raises(ValidationError):
            NodeConfig(kind=NodeKind.REMOTE)

    def test_remote_node_with_none_address(self) -> None:
        with pytest.raises(ValidationError):
            NodeConfig(kind=NodeKind.REMOTE, address=None)

    def test_node_name_validation_in_config(self) -> None:
        # Names with only whitespace are rejected
        config_data: dict[str, Any] = {
            "nodes": {
                "  ": {"kind": "local"},
            }
        }
        with pytest.raises(ValidationError):
            ArcadiaConfig.model_validate(config_data)

    def test_node_name_with_control_chars_rejected(self) -> None:
        config_data: dict[str, Any] = {
            "nodes": {
                "node\x00bad": {"kind": "local"},
            }
        }
        with pytest.raises(ValidationError):
            ArcadiaConfig.model_validate(config_data)

    def test_description_with_control_chars_rejected(self) -> None:
        with pytest.raises(ValidationError):
            NodeConfig(kind=NodeKind.LOCAL, description="has\x01control")

    def test_description_empty_allowed(self) -> None:
        node = NodeConfig(kind=NodeKind.LOCAL, description="")
        assert node.description == ""

    def test_description_trimmed(self) -> None:
        node = NodeConfig(kind=NodeKind.LOCAL, description="  trimmed  ")
        assert node.description == "trimmed"


# ---------------------------------------------------------------------------
# Cross-reference: at most one local node
# ---------------------------------------------------------------------------


class TestLocalNodeLimit:
    def test_single_local_node_ok(self) -> None:
        config = ArcadiaConfig.model_validate(
            {
                "nodes": {
                    "local1": {"kind": "local"},
                }
            }
        )

        assert len(config.nodes) == 1

    def test_two_local_nodes_rejected(self) -> None:
        data: dict[str, Any] = {
            "nodes": {
                "local1": {"kind": "local"},
                "local2": {"kind": "local"},
            }
        }
        with pytest.raises(ValidationError):
            ArcadiaConfig.model_validate(data)

    def test_one_local_one_remote_ok(self) -> None:
        config = ArcadiaConfig.model_validate(
            {
                "nodes": {
                    "local1": {"kind": "local"},
                    "remote1": {"kind": "remote", "address": {"host": "10.0.0.1", "instruction_port": 8000}},
                }
            }
        )
        assert len(config.nodes) == 2


class TestNamedMappingKeys:
    def test_non_string_node_key_rejected(self) -> None:
        with pytest.raises(ValidationError, match="node name must be a string"):
            ArcadiaConfig.model_validate({"nodes": {1: {"kind": "local"}}})

    def test_trimmed_node_key_collision_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duplicate normalized node name"):
            ArcadiaConfig.model_validate(
                {
                    "nodes": {
                        "local": {"kind": "local"},
                        " local ": {"kind": "remote", "address": {"host": "host", "instruction_port": 8000}},
                    }
                }
            )

    def test_non_string_service_profile_key_rejected(self) -> None:
        with pytest.raises(ValidationError, match="service profile name must be a string"):
            ArcadiaConfig.model_validate(
                {
                    "nodes": {"local": {"kind": "local"}},
                    "service_profiles": {
                        1: {
                            "node": "local",
                            "spec": {
                                "service_type": "sam3",
                                "port": 8000,
                                "checkpoint_path": "checkpoint.pt",
                            },
                        }
                    },
                }
            )

    def test_trimmed_service_profile_key_collision_rejected(self) -> None:
        profile = {
            "node": "local",
            "spec": {
                "service_type": "sam3",
                "port": 8000,
                "checkpoint_path": "checkpoint.pt",
            },
        }
        with pytest.raises(ValidationError, match="duplicate normalized service profile name"):
            ArcadiaConfig.model_validate(
                {
                    "nodes": {"local": {"kind": "local"}},
                    "service_profiles": {"profile": profile, " profile ": profile},
                }
            )

    def test_non_string_tool_profile_key_rejected(self) -> None:
        with pytest.raises(ValidationError, match="tool profile name must be a string"):
            ArcadiaConfig.model_validate({"tool_profiles": {1: {"tool_name": "tool"}}})

    def test_trimmed_tool_profile_key_collision_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duplicate normalized tool profile name"):
            ArcadiaConfig.model_validate(
                {
                    "tool_profiles": {
                        "tool": {"tool_name": "tool"},
                        " tool ": {"tool_name": "other"},
                    }
                }
            )

    def test_non_string_stage_key_rejected(self) -> None:
        with pytest.raises(ValidationError, match="stage name must be a string"):
            ArcadiaConfig.model_validate(
                {
                    "tool_profiles": {
                        "tool": {
                            "tool_name": "tool",
                            "stages": {1: {"service_profile": "profile"}},
                        }
                    }
                }
            )

    def test_trimmed_stage_key_collision_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duplicate normalized stage name"):
            ArcadiaConfig.model_validate(
                {
                    "tool_profiles": {
                        "tool": {
                            "tool_name": "tool",
                            "stages": {
                                "stage": {"service_profile": "profile"},
                                " stage ": {"service_profile": "profile"},
                            },
                        }
                    }
                }
            )


# ---------------------------------------------------------------------------
# Service profile validation
# ---------------------------------------------------------------------------


class TestServiceProfile:
    def test_valid_llm_profile(self) -> None:
        config = ArcadiaConfig.model_validate(
            {
                "nodes": {"local": {"kind": "local"}},
                "service_profiles": {
                    "llm-profile": {
                        "node": "local",
                        "spec": {
                            "service_type": "llm",
                            "port": 8080,
                            "model": {
                                "repo_id": "owner/model",
                                "filename": "model.gguf",
                            },
                        },
                    }
                },
            }
        )
        sp = config.service_profiles["llm-profile"]
        assert sp.node == "local"

    def test_valid_visual_llm_profile(self) -> None:
        config = ArcadiaConfig.model_validate(
            {
                "nodes": {"local": {"kind": "local"}},
                "service_profiles": {
                    "vlm-profile": {
                        "node": "local",
                        "spec": {
                            "service_type": "visual_llm",
                            "port": 8081,
                            "model": {"repo_id": "owner/vlm", "filename": "vlm.gguf"},
                            "projector": {"repo_id": "owner/projector", "filename": "proj.gguf"},
                        },
                    }
                },
            }
        )
        assert "vlm-profile" in config.service_profiles

    def test_valid_sam_profile(self) -> None:
        config = ArcadiaConfig.model_validate(
            {
                "nodes": {"local": {"kind": "local"}},
                "service_profiles": {
                    "sam-profile": {
                        "node": "local",
                        "spec": {
                            "service_type": "sam3",
                            "port": 8082,
                            "checkpoint_path": "/models/sam3.pt",
                        },
                    }
                },
            }
        )
        assert "sam-profile" in config.service_profiles

    def test_unknown_node_reference_rejected(self) -> None:
        data: dict[str, Any] = {
            "nodes": {"local": {"kind": "local"}},
            "service_profiles": {
                "bad-profile": {
                    "node": "nonexistent",
                    "spec": {
                        "service_type": "llm",
                        "port": 8080,
                        "model": {"repo_id": "owner/model", "filename": "model.gguf"},
                    },
                }
            },
        }
        with pytest.raises(ValidationError, match="unknown node"):
            ArcadiaConfig.model_validate(data)

    def test_profile_reuse_same_node_and_port(self) -> None:
        """Multiple profiles may target the same node and port (alternative configs)."""
        config = ArcadiaConfig.model_validate(
            {
                "nodes": {"local": {"kind": "local"}},
                "service_profiles": {
                    "profile-a": {
                        "node": "local",
                        "spec": {
                            "service_type": "llm",
                            "port": 8080,
                            "model": {"repo_id": "owner/model-a", "filename": "a.gguf"},
                        },
                    },
                    "profile-b": {
                        "node": "local",
                        "spec": {
                            "service_type": "llm",
                            "port": 8080,
                            "model": {"repo_id": "owner/model-b", "filename": "b.gguf"},
                        },
                    },
                },
            }
        )
        assert len(config.service_profiles) == 2


# ---------------------------------------------------------------------------
# Stage binding and tool profile validation
# ---------------------------------------------------------------------------


class TestStageBinding:
    def test_valid_stage_binding(self) -> None:
        binding = StageBinding(service_profile="my-profile")
        assert binding.service_profile == "my-profile"

    def test_unknown_service_profile_reference_rejected(self) -> None:
        data: dict[str, Any] = {
            "nodes": {"local": {"kind": "local"}},
            "service_profiles": {
                "profile-a": {
                    "node": "local",
                    "spec": {
                        "service_type": "llm",
                        "port": 8080,
                        "model": {"repo_id": "owner/model", "filename": "model.gguf"},
                    },
                }
            },
            "tool_profiles": {
                "my-tool": {
                    "tool_name": "priority_map",
                    "stages": {
                        "scene": {"service_profile": "nonexistent"},
                    },
                }
            },
        }
        with pytest.raises(ValidationError, match="unknown service profile"):
            ArcadiaConfig.model_validate(data)

    def test_stage_binding_empty_service_profile_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StageBinding(service_profile="  ")


class TestToolProfile:
    def test_valid_tool_profile(self) -> None:
        tp = ToolProfile(tool_name="priority_map")
        assert tp.tool_name == "priority_map"
        assert tp.stages == {}

    def test_tool_name_empty_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ToolProfile(tool_name="  ")

    def test_tool_profile_with_stages(self) -> None:
        data: dict[str, Any] = {
            "nodes": {"local": {"kind": "local"}},
            "service_profiles": {
                "vlm": {
                    "node": "local",
                    "spec": {
                        "service_type": "visual_llm",
                        "port": 8080,
                        "model": {"repo_id": "owner/vlm", "filename": "vlm.gguf"},
                        "projector": {"repo_id": "owner/proj", "filename": "proj.gguf"},
                    },
                },
                "sam": {
                    "node": "local",
                    "spec": {
                        "service_type": "sam3",
                        "port": 8081,
                        "checkpoint_path": "/models/sam3.pt",
                    },
                },
            },
            "tool_profiles": {
                "priority_map": {
                    "tool_name": "priority_map",
                    "stages": {
                        "scene_understanding": {"service_profile": "vlm"},
                        "segmentation": {"service_profile": "sam"},
                    },
                    "settings": {"sam_step": 4, "resize": 1024},
                }
            },
        }
        config = ArcadiaConfig.model_validate(data)
        tp = config.tool_profiles["priority_map"]
        assert len(tp.stages) == 2
        assert tp.stages["scene_understanding"].service_profile == "vlm"
        assert tp.stages["segmentation"].service_profile == "sam"

    def test_profile_reuse_in_stages(self) -> None:
        """Multiple stages may reference the same service profile."""
        data: dict[str, Any] = {
            "nodes": {"local": {"kind": "local"}},
            "service_profiles": {
                "vlm": {
                    "node": "local",
                    "spec": {
                        "service_type": "visual_llm",
                        "port": 8080,
                        "model": {"repo_id": "owner/vlm", "filename": "vlm.gguf"},
                        "projector": {"repo_id": "owner/proj", "filename": "proj.gguf"},
                    },
                }
            },
            "tool_profiles": {
                "my-tool": {
                    "tool_name": "test",
                    "stages": {
                        "stage1": {"service_profile": "vlm"},
                        "stage2": {"service_profile": "vlm"},
                    },
                }
            },
        }
        config = ArcadiaConfig.model_validate(data)
        assert len(config.tool_profiles["my-tool"].stages) == 2


# ---------------------------------------------------------------------------
# Requested settings preservation
# ---------------------------------------------------------------------------


class TestRequestedSettings:
    def test_requested_settings_survive_round_trip(self) -> None:
        data: dict[str, Any] = {
            "nodes": {"local": {"kind": "local"}},
            "service_profiles": {
                "llm": {
                    "node": "local",
                    "spec": {
                        "service_type": "llm",
                        "port": 8080,
                        "model": {"repo_id": "owner/model", "filename": "model.gguf"},
                        "requested_settings": {
                            "values": {"n_gpu_layers": 35, "n_ctx": 4096},
                        },
                    },
                }
            },
        }
        config = ArcadiaConfig.model_validate(data)
        spec = config.service_profiles["llm"].spec
        # The requested_settings dict is mutable within the model
        assert spec.requested_settings.values["n_gpu_layers"] == 35  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Extensions
# ---------------------------------------------------------------------------


class TestExtensions:
    def test_root_extensions(self) -> None:
        config = ArcadiaConfig.model_validate(
            {
                "extensions": {"custom_key": "custom_value", "nested": {"a": 1}},
            }
        )
        assert config.extensions["custom_key"] == "custom_value"

    def test_node_extensions(self) -> None:
        config = ArcadiaConfig.model_validate(
            {
                "nodes": {
                    "local": {"kind": "local", "extensions": {"gpu": "cuda"}},
                }
            }
        )
        assert config.nodes["local"].extensions["gpu"] == "cuda"

    def test_service_profile_extensions(self) -> None:
        config = ArcadiaConfig.model_validate(
            {
                "nodes": {"local": {"kind": "local"}},
                "service_profiles": {
                    "llm": {
                        "node": "local",
                        "spec": {
                            "service_type": "llm",
                            "port": 8080,
                            "model": {"repo_id": "owner/model", "filename": "model.gguf"},
                        },
                        "extensions": {"custom": True},
                    }
                },
            }
        )
        assert config.service_profiles["llm"].extensions["custom"] is True

    def test_invalid_json_in_extensions_rejected(self) -> None:
        # bytes are not JSON-compatible
        with pytest.raises(ValidationError):
            ArcadiaConfig.model_validate({"extensions": {"key": b"not-json"}})

    def test_nan_in_extensions_rejected(self) -> None:
        import math

        with pytest.raises(ValidationError):
            ArcadiaConfig.model_validate({"extensions": {"key": math.nan}})


# ---------------------------------------------------------------------------
# Unknown field rejection
# ---------------------------------------------------------------------------


class TestUnknownFields:
    def test_unknown_root_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ArcadiaConfig.model_validate({"unknown_field": "value"})

    def test_unknown_node_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            NodeConfig.model_validate({"kind": "local", "unknown": True})

    def test_unknown_retry_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RetryPolicy.model_validate({"max_attempts": 3, "unknown": True})


# ---------------------------------------------------------------------------
# Retry policy validation
# ---------------------------------------------------------------------------


class TestRetryPolicy:
    def test_min_max_attempts(self) -> None:
        policy = RetryPolicy(max_attempts=1)
        assert policy.max_attempts == 1

    def test_max_attempts_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RetryPolicy(max_attempts=0)

    def test_max_attempts_boolean_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RetryPolicy(max_attempts=True)

    def test_negative_delay_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RetryPolicy(initial_delay_seconds=-1.0)

    def test_infinite_delay_rejected(self) -> None:
        import math

        with pytest.raises(ValidationError):
            RetryPolicy(initial_delay_seconds=math.inf)

    def test_multiplier_below_one_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RetryPolicy(multiplier=0.5)

    def test_maximum_delay_below_initial_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RetryPolicy(initial_delay_seconds=5.0, maximum_delay_seconds=2.0)

    def test_delay_boolean_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RetryPolicy(initial_delay_seconds=True)


# ---------------------------------------------------------------------------
# Output settings validation
# ---------------------------------------------------------------------------


class TestOutputSettings:
    def test_custom_root(self) -> None:
        settings = OutputSettings(root="/custom/outputs")
        assert settings.root == "/custom/outputs"

    def test_empty_root_rejected(self) -> None:
        with pytest.raises(ValidationError):
            OutputSettings(root="")

    def test_root_with_null_byte_rejected(self) -> None:
        with pytest.raises(ValidationError):
            OutputSettings(root="path\x00bad")

    def test_root_with_cr_rejected(self) -> None:
        with pytest.raises(ValidationError):
            OutputSettings(root="path\rbad")

    def test_root_with_lf_rejected(self) -> None:
        with pytest.raises(ValidationError):
            OutputSettings(root="path\nbad")


# ---------------------------------------------------------------------------
# Schema version
# ---------------------------------------------------------------------------


class TestSchemaVersion:
    def test_version_1_ok(self) -> None:
        config = ArcadiaConfig(schema_version=1)
        assert config.schema_version == 1

    def test_missing_version_defaults_to_1(self) -> None:
        config = ArcadiaConfig.model_validate({})
        assert config.schema_version == 1

    def test_unsupported_version_rejected(self) -> None:
        with pytest.raises(ConfigurationError, match="unsupported schema version"):
            ArcadiaConfig.model_validate({"schema_version": 2})

    def test_zero_version_rejected(self) -> None:
        with pytest.raises(ConfigurationError, match="unsupported schema version"):
            ArcadiaConfig.model_validate({"schema_version": 0})
