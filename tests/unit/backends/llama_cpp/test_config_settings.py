from __future__ import annotations

from pathlib import Path

import pytest

from arcadia.backends.llama_cpp import LlamaCppBackendConfig
from arcadia.backends.llama_cpp.settings import translate_settings
from arcadia.models import ResolvedRuntimeSettings, ServiceStartupError


def _translate(values: dict[str, object], tmp_path: Path):
    return translate_settings(
        ResolvedRuntimeSettings(backend="llama_cpp", values=values),
        bind_host="127.0.0.1",
        port=19000,
        model_path=tmp_path / "model.gguf",
        projector_path=None,
    )


def test_config_defaults_are_detached_and_side_effect_free(tmp_path: Path) -> None:
    runtime = tmp_path / "not-created"
    config = LlamaCppBackendConfig(runtime_dir=runtime, cache_dir=tmp_path / "cache")
    assert config.advertise_host == "127.0.0.1"
    assert config.health_host == "127.0.0.1"
    assert config.runtime_dir == runtime
    assert not runtime.exists()


def test_wildcard_hosts_require_advertise_and_choose_loopback() -> None:
    with pytest.raises(ValueError, match="advertise"):
        LlamaCppBackendConfig(bind_host="0.0.0.0")
    ipv4 = LlamaCppBackendConfig(bind_host="0.0.0.0", advertise_host="node.example")
    ipv6 = LlamaCppBackendConfig(bind_host="::", advertise_host="2001:db8::1")
    assert ipv4.health_host == "127.0.0.1"
    assert ipv6.health_host == "::1"


@pytest.mark.parametrize(
    "keyword,value",
    [
        ("startup_timeout_seconds", 0),
        ("health_timeout_seconds", float("inf")),
        ("poll_interval_seconds", float("nan")),
        ("stop_timeout_seconds", -1),
        ("kill_timeout_seconds", True),
    ],
)
def test_config_rejects_invalid_timeouts(keyword: str, value: object) -> None:
    with pytest.raises(ValueError):
        LlamaCppBackendConfig(**{keyword: value})  # type: ignore[arg-type]


def test_python_executable_validation() -> None:
    for value in ("", "python\n-x", "python\x00-x"):
        with pytest.raises(ValueError):
            LlamaCppBackendConfig(python_executable=value)


def test_cpu_cuda_metal_threads_and_partial_offload(tmp_path: Path) -> None:
    cpu = _translate({"device": "cpu", "threads": 8}, tmp_path)
    cuda = _translate({"device": "cuda", "device_index": 3, "model_options": {"n_gpu_layers": 20}}, tmp_path)
    metal = _translate({"device": "metal"}, tmp_path)
    assert cpu.server_config["models"][0]["n_threads"] == 8
    assert cpu.server_config["models"][0]["n_gpu_layers"] == 0
    assert cuda.server_config["models"][0]["n_gpu_layers"] == 20
    assert cuda.environment_updates == {"CUDA_VISIBLE_DEVICES": "3"}
    assert metal.server_config["models"][0]["n_gpu_layers"] == -1


def test_option_merging_and_projector_path(tmp_path: Path) -> None:
    settings = ResolvedRuntimeSettings(
        backend="llama_cpp",
        values={
            "device": "metal",
            "server_options": {"api_key_file": "not accepted"},
        },
    )
    with pytest.raises(ServiceStartupError, match="credentials"):
        translate_settings(
            settings,
            bind_host="::",
            port=19000,
            model_path=tmp_path / "model.gguf",
            projector_path=tmp_path / "projector.gguf",
        )

    translated = translate_settings(
        ResolvedRuntimeSettings(
            backend="llama_cpp",
            values={
                "device": "metal",
                "server_options": {"root_path": "/llama"},
                "model_options": {"chat_format": "chatml"},
                "n_ctx": 4096,
            },
        ),
        bind_host="::",
        port=19000,
        model_path=tmp_path / "model.gguf",
        projector_path=tmp_path / "projector.gguf",
    )
    model = translated.server_config["models"][0]
    assert translated.server_config["root_path"] == "/llama"
    assert model["chat_format"] == "chatml"
    assert model["n_ctx"] == 4096
    assert model["clip_model_path"] == str(tmp_path / "projector.gguf")


@pytest.mark.parametrize(
    "values",
    [
        {"device": "cpu", "n_ctx": 1, "model_options": {"n_ctx": 2}},
        {"device": "cpu", "threads": 2, "model_options": {"n_threads": 2}},
        {"device": "cpu", "model_options": {"model": "other.gguf"}},
        {"device": "cpu", "server_options": {"host": "0.0.0.0"}},
        {"device": "cpu", "model_options": {"api_key": "secret"}},
        {"device": "cpu", "CUDA_VISIBLE_DEVICES": "all"},
        {"device": "cpu", "model_options": {"n_gpu_layers": 1}},
        {"device": "cuda"},
        {"device": "unknown"},
    ],
)
def test_invalid_or_ambiguous_settings(values: dict[str, object], tmp_path: Path) -> None:
    with pytest.raises(ServiceStartupError) as captured:
        _translate(values, tmp_path)
    assert captured.value.code == "llama_cpp_settings_invalid"


def test_translation_defensively_copies_nested_values(tmp_path: Path) -> None:
    nested = [1, {"value": "before"}]
    values: dict[str, object] = {"device": "cpu", "model_options": {"metadata": nested}}
    translated = _translate(values, tmp_path)
    nested[1]["value"] = "after"  # type: ignore[index]
    assert translated.server_config["models"][0]["metadata"][1]["value"] == "before"
