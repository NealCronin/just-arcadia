"""Side-effect-free llama.cpp backend configuration."""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path

from arcadia.models.common import _validate_host

_WILDCARD_HOSTS = {"0.0.0.0", "::"}


@dataclass(frozen=True, slots=True)
class LlamaCppBackendConfig:
    """Validated process, network, and runtime-file configuration."""

    bind_host: str = "127.0.0.1"
    advertise_host: str | None = None
    health_host: str | None = None
    startup_timeout_seconds: float = 300.0
    health_timeout_seconds: float = 2.0
    poll_interval_seconds: float = 0.25
    stop_timeout_seconds: float = 10.0
    kill_timeout_seconds: float = 5.0
    cache_dir: Path | None = None
    runtime_dir: Path | None = None
    python_executable: str = sys.executable

    def __post_init__(self) -> None:
        bind_host = _validate_host(self.bind_host)
        advertise_host = self.advertise_host
        if advertise_host is None:
            if bind_host in _WILDCARD_HOSTS:
                raise ValueError("wildcard bind_host requires an explicit advertise_host")
            advertise_host = bind_host
        advertise_host = _validate_host(advertise_host)
        if advertise_host in _WILDCARD_HOSTS:
            raise ValueError("advertise_host must not be a wildcard address")

        health_host = self.health_host
        if health_host is None:
            health_host = "127.0.0.1" if bind_host == "0.0.0.0" else "::1" if bind_host == "::" else bind_host
        health_host = _validate_host(health_host)
        if health_host in _WILDCARD_HOSTS:
            raise ValueError("health_host must be locally reachable, not a wildcard address")

        for name in (
            "startup_timeout_seconds",
            "health_timeout_seconds",
            "poll_interval_seconds",
            "stop_timeout_seconds",
            "kill_timeout_seconds",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a finite number greater than zero")
            normalized = float(value)
            if not math.isfinite(normalized) or normalized <= 0:
                raise ValueError(f"{name} must be a finite number greater than zero")
            object.__setattr__(self, name, normalized)

        executable = self.python_executable
        if not isinstance(executable, str) or not executable.strip():
            raise ValueError("python_executable must be a non-empty path-like string")
        executable = executable.strip()
        if any(character in executable for character in ("\x00", "\r", "\n")):
            raise ValueError("python_executable must not contain null, CR, or LF characters")

        object.__setattr__(self, "bind_host", bind_host)
        object.__setattr__(self, "advertise_host", advertise_host)
        object.__setattr__(self, "health_host", health_host)
        object.__setattr__(self, "python_executable", executable)
        object.__setattr__(self, "cache_dir", None if self.cache_dir is None else Path(self.cache_dir))
        object.__setattr__(self, "runtime_dir", None if self.runtime_dir is None else Path(self.runtime_dir))
