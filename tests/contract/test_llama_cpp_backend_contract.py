"""Reusable Session 06 contract exercised by the real llama.cpp backend."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pytest

from arcadia.backends.llama_cpp import LlamaCppBackend, LlamaCppBackendConfig
from arcadia.hardware import CpuInfo, HardwareCapabilities, MemoryInfo, OperatingSystem, PlatformInfo
from arcadia.models import HuggingFaceFileSpec, LlamaServiceSpec, RequestedRuntimeSettings, ServiceType
from tests.helpers.llama_cpp import FakeHealth, FakeLauncher, FakeResolver

from .test_service_backend_contract import assert_service_backend_contract


def _hardware() -> HardwareCapabilities:
    return HardwareCapabilities(
        detected_at=datetime.now(UTC),
        platform=PlatformInfo(
            operating_system=OperatingSystem.LINUX,
            release="",
            version="",
            machine="x86_64",
            python_version="3.11",
        ),
        cpu=CpuInfo(logical_cores=8, architecture="x86_64"),
        memory=MemoryInfo(),
    )


@pytest.mark.parametrize("service_type", [ServiceType.LLM, ServiceType.VISUAL_LLM])
def test_llama_cpp_backend_satisfies_reusable_contract(
    tmp_path: Path,
    service_type: Literal[ServiceType.LLM, ServiceType.VISUAL_LLM],
) -> None:
    model = tmp_path / "model.gguf"
    projector = tmp_path / "projector.gguf"
    model.write_bytes(b"model")
    projector.write_bytes(b"projector")
    spec = LlamaServiceSpec(
        service_type=service_type,
        port=19002,
        model=HuggingFaceFileSpec(repo_id="owner/model", filename="model.gguf"),
        projector=(
            HuggingFaceFileSpec(repo_id="owner/projector", filename="projector.gguf")
            if service_type == ServiceType.VISUAL_LLM
            else None
        ),
        requested_settings=RequestedRuntimeSettings(values={"device": "cpu", "threads": 4}),
    )
    sequence = iter(range(100))

    def factory() -> LlamaCppBackend:
        number = next(sequence)
        return LlamaCppBackend(
            config=LlamaCppBackendConfig(runtime_dir=tmp_path / f"runtime-{number}"),
            file_resolver=FakeResolver(model, projector),
            process_launcher=FakeLauncher(),
            health_probe=FakeHealth(),
        )

    assert_service_backend_contract(factory, hardware=_hardware(), spec=spec)
