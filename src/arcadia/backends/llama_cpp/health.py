"""Bounded OpenAI models-endpoint health probing."""

from __future__ import annotations

import json
import urllib.request
from typing import Protocol

_MAX_HEALTH_BYTES = 1_048_576


class HealthProbe(Protocol):
    def probe(self, host: str, port: int, *, timeout_seconds: float) -> None: ...


class HttpModelsHealthProbe:
    """Validate one bounded ``GET /v1/models`` response."""

    def probe(self, host: str, port: int, *, timeout_seconds: float) -> None:
        formatted_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
        request = urllib.request.Request(
            f"http://{formatted_host}:{port}/v1/models",
            headers={"Accept": "application/json"},
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            if response.status != 200:
                raise RuntimeError(f"models endpoint returned HTTP {response.status}")
            payload = response.read(_MAX_HEALTH_BYTES + 1)
        if len(payload) > _MAX_HEALTH_BYTES:
            raise ValueError("models endpoint response exceeds the health-check limit")
        decoded = json.loads(payload)
        if not isinstance(decoded, dict) or not isinstance(decoded.get("data"), list):
            raise ValueError("models endpoint response must contain a data list")
