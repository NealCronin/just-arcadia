"""Typed failures raised by :mod:`arcadia.hardware`."""

from arcadia.models import ArcadiaError

__all__ = ["HardwareError", "HardwareDetectionError", "RuntimeResolutionError"]


class HardwareError(ArcadiaError):
    """A generic hardware capability failure."""

    _default_code = "hardware_error"


class HardwareDetectionError(HardwareError):
    """Hardware inspection could not produce a valid snapshot."""

    _default_code = "hardware_detection_failed"


class RuntimeResolutionError(HardwareError):
    """Requested runtime settings cannot be resolved safely."""

    _default_code = "runtime_resolution_failed"
