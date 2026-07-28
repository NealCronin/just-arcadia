"""Unit tests for arcadia.models.common.

Focused on public behavior: address validation, HF file specs, settings
defensive copying, and JSON compatibility.
"""

import pytest
from pydantic import ValidationError

from arcadia.models.common import (
    ArtifactVisibility,
    HuggingFaceFileSpec,
    NodeAddress,
    RequestedRuntimeSettings,
    ResolvedRuntimeSettings,
)


class TestNodeAddress:
    @pytest.mark.parametrize(
        "host,expected",
        [
            ("192.168.1.1", "http://192.168.1.1:8000"),
            ("localhost", "http://localhost:8000"),
            ("compute-node.local", "http://compute-node.local:8000"),
        ],
    )
    def test_valid_addresses(self, host: str, expected: str) -> None:
        addr = NodeAddress(host=host, instruction_port=8000)
        assert addr.base_url == expected
        assert addr.scheme == "http"

    def test_ipv6_brackets_ipv6(self) -> None:
        addr = NodeAddress(host="::1", instruction_port=8000)
        assert addr.base_url == "http://[::1]:8000"

    @pytest.mark.parametrize("port", [0, 65536, -1, True, "8000"])
    def test_invalid_ports(self, port: object) -> None:
        with pytest.raises(ValidationError):
            NodeAddress(host="localhost", instruction_port=port)  # type: ignore[arg-type]

    def test_unknown_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            NodeAddress(host="localhost", instruction_port=8000, extra="nope")


class TestHuggingFaceFileSpec:
    def test_valid_spec(self) -> None:
        spec = HuggingFaceFileSpec(repo_id="owner/repo", filename="model.gguf")
        assert spec.repo_id == "owner/repo"
        assert spec.filename == "model.gguf"
        assert spec.revision == "main"

    @pytest.mark.parametrize(
        "repo_id",
        ["ownerrepo", "owner/repo/extra", "owner/..repo", "/owner/repo"],
    )
    def test_invalid_repo_id(self, repo_id: str) -> None:
        with pytest.raises(ValidationError):
            HuggingFaceFileSpec(repo_id=repo_id, filename="model.gguf")

    @pytest.mark.parametrize(
        "filename",
        ["model.bin", "../model.gguf", "/abs/model.gguf", "dir\\model.gguf", "", "model\x00.gguf"],
    )
    def test_invalid_filename(self, filename: str) -> None:
        with pytest.raises(ValidationError):
            HuggingFaceFileSpec(repo_id="owner/repo", filename=filename)

    def test_nested_path_allowed(self) -> None:
        spec = HuggingFaceFileSpec(repo_id="owner/repo", filename="subdir/model.gguf")
        assert spec.filename == "subdir/model.gguf"

    @pytest.mark.parametrize("revision", ["", ".", ".."])
    def test_invalid_revision(self, revision: str) -> None:
        with pytest.raises(ValidationError):
            HuggingFaceFileSpec(repo_id="owner/repo", filename="model.gguf", revision=revision)

    def test_unknown_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            HuggingFaceFileSpec(repo_id="owner/repo", filename="model.gguf", extra="nope")


class TestRuntimeSettings:
    def test_default_values(self) -> None:
        assert RequestedRuntimeSettings().values == {}

    def test_custom_values(self) -> None:
        settings = RequestedRuntimeSettings(values={"threads": 4, "batch": True})
        assert settings.values == {"threads": 4, "batch": True}

    @pytest.mark.parametrize(
        "value",
        [float("nan"), float("inf"), b"bytes", {1, 2, 3}, object()],
    )
    def test_non_json_values_rejected(self, value: object) -> None:
        with pytest.raises(ValidationError):
            RequestedRuntimeSettings(values={"k": value})

    def test_non_string_key_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RequestedRuntimeSettings(values={1: "value"})

    def test_defensive_copy(self) -> None:
        """Mutating a restored settings dict must not affect the original input."""
        original = {"nested": [1, 2, 3]}
        settings = RequestedRuntimeSettings(values=original)
        settings.values["nested"].append(4)
        assert original == {"nested": [1, 2, 3]}

    def test_resolved_settings_requires_backend(self) -> None:
        with pytest.raises(ValidationError):
            ResolvedRuntimeSettings(backend="", values={}, notes=())

    def test_resolved_settings_valid(self) -> None:
        settings = ResolvedRuntimeSettings(backend="llama.cpp", values={"threads": 4}, notes=("auto",))
        assert settings.backend == "llama.cpp"
        assert settings.notes == ("auto",)


class TestArtifactVisibility:
    def test_values(self) -> None:
        assert ArtifactVisibility.final.value == "final"
        assert ArtifactVisibility.internal.value == "internal"
