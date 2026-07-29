"""Configuration module for ARCADIA.

Provides the human-editable JSON configuration layer: validated models for
compute nodes, service profiles, tool profiles, retry and output settings,
plus file I/O functions with atomic save support.

Importing :mod:`arcadia` does not eagerly import this module.
"""

from arcadia.config.files import (
    dumps_config,
    load_config,
    loads_config,
    save_config,
    snapshot_config,
)
from arcadia.config.models import (
    CONFIG_SCHEMA_VERSION,
    ArcadiaConfig,
    NodeConfig,
    NodeKind,
    OutputSettings,
    RetryPolicy,
    ServiceProfile,
    StageBinding,
    ToolProfile,
)

__all__ = [
    # Constants
    "CONFIG_SCHEMA_VERSION",
    # Models
    "NodeKind",
    "NodeConfig",
    "ServiceProfile",
    "StageBinding",
    "ToolProfile",
    "RetryPolicy",
    "OutputSettings",
    "ArcadiaConfig",
    # File I/O
    "load_config",
    "loads_config",
    "save_config",
    "dumps_config",
    "snapshot_config",
]
