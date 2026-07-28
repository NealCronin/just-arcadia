"""Domain models and typed errors for ARCADIA.

This is the lowest dependency layer of the ARCADIA package. It provides the
stable, validated vocabulary shared by all other modules.

Importing :mod:`arcadia` does not eagerly import this module.
"""

from arcadia.models.analysis import (
    AnalysisSpec,
    AnalysisStatus,
    AnalysisState,
    StageState,
    StageStatus,
)
from arcadia.models.artifacts import ArtifactRecord
from arcadia.models.common import (
    ArtifactVisibility,
    HuggingFaceFileSpec,
    NodeAddress,
    ResolvedRuntimeSettings,
    RequestedRuntimeSettings,
)
from arcadia.models.errors import (
    AnalysisError,
    ArcadiaError,
    ArcadiaErrorInfo,
    ArtifactError,
    ConfigurationError,
    InferenceError,
    InferenceTimeoutError,
    InstructionError,
    ServiceConflictError,
    ServiceError,
    ServiceHealthError,
    ServiceNotRunningError,
    ServiceStartupError,
)
from arcadia.models.services import (
    LlamaServiceSpec,
    OperationState,
    OperationStatus,
    SamServiceSpec,
    ServiceEndpoint,
    ServiceSpec,
    ServiceState,
    ServiceStatus,
    ServiceType,
    parse_service_spec,
)

__all__ = [
    # Errors
    "ArcadiaError",
    "ArcadiaErrorInfo",
    "ConfigurationError",
    "ServiceError",
    "ServiceConflictError",
    "ServiceStartupError",
    "ServiceHealthError",
    "ServiceNotRunningError",
    "InstructionError",
    "InferenceError",
    "InferenceTimeoutError",
    "AnalysisError",
    "ArtifactError",
    # Common
    "NodeAddress",
    "HuggingFaceFileSpec",
    "RequestedRuntimeSettings",
    "ResolvedRuntimeSettings",
    # Services
    "ServiceType",
    "ServiceState",
    "OperationState",
    "LlamaServiceSpec",
    "SamServiceSpec",
    "ServiceSpec",
    "ServiceEndpoint",
    "ServiceStatus",
    "OperationStatus",
    "parse_service_spec",
    # Analysis
    "AnalysisState",
    "StageState",
    "AnalysisSpec",
    "AnalysisStatus",
    "StageStatus",
    # Artifacts
    "ArtifactVisibility",
    "ArtifactRecord",
]
