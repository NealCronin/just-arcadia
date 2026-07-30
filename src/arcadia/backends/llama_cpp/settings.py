"""Translation from resolved ARCADIA values to llama.cpp server settings."""

from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arcadia.models import ResolvedRuntimeSettings, ServiceStartupError

_OPTION_NAME = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
_RESERVED_SERVER = {"host", "port", "config_file", "models"}
_RESERVED_MODEL = {"model", "clip_model_path", "hf_model_repo_id", "hf_model_repo_revision"}
_OWNED_TOP_LEVEL = {"device", "device_index", "threads", "server_options", "model_options"}
_CREDENTIAL_MARKERS = ("token", "password", "secret", "private_key", "api_key", "credential")
_CREDENTIAL_NAMES = {"ssl_keyfile", "cuda_visible_devices", "authorization"}


@dataclass(frozen=True, slots=True)
class TranslatedSettings:
    """Detached server configuration and backend-owned child environment changes."""

    server_config: dict[str, Any]
    environment_updates: dict[str, str]


def _invalid(message: str, *, details: dict[str, Any] | None = None) -> ServiceStartupError:
    return ServiceStartupError(message, code="llama_cpp_settings_invalid", details=details)


def _copy_json(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _invalid("llama.cpp settings contain a non-finite float")
        return value
    if isinstance(value, list):
        return [_copy_json(item) for item in value]
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise _invalid("llama.cpp setting objects require string keys")
        return {key: _copy_json(item) for key, item in value.items()}
    raise _invalid("llama.cpp settings must be JSON-compatible")


def _options(values: dict[str, Any], name: str) -> dict[str, Any]:
    raw = values.get(name, {})
    if not isinstance(raw, dict):
        raise _invalid(f"{name} must be a JSON object")
    copied = _copy_json(raw)
    assert isinstance(copied, dict)
    for key in copied:
        if not _OPTION_NAME.fullmatch(key):
            raise _invalid(f"{name} keys must use lowercase snake case", details={"setting": key[:120]})
        if _is_credential(key):
            raise _invalid(
                "credentials and private keys are not accepted in runtime settings", details={"setting": key}
            )
    return copied


def _is_credential(key: str) -> bool:
    return key in _CREDENTIAL_NAMES or any(marker in key for marker in _CREDENTIAL_MARKERS)


def translate_settings(
    resolved_settings: ResolvedRuntimeSettings,
    *,
    bind_host: str,
    port: int,
    model_path: Path,
    projector_path: Path | None,
) -> TranslatedSettings:
    """Produce a deterministic, detached single-model server configuration."""

    values = copy.deepcopy(resolved_settings.values)
    server_options = _options(values, "server_options")
    model_options = _options(values, "model_options")

    for key in server_options:
        if key in _RESERVED_SERVER:
            raise _invalid("server option is owned by the backend", details={"setting": key})
    for key in model_options:
        if key in _RESERVED_MODEL:
            raise _invalid("model option is owned by the backend", details={"setting": key})

    flat_options: dict[str, Any] = {}
    for key, value in values.items():
        if key in _OWNED_TOP_LEVEL:
            continue
        if not _OPTION_NAME.fullmatch(key):
            raise _invalid("advanced setting names must use lowercase snake case", details={"setting": key[:120]})
        if _is_credential(key):
            raise _invalid(
                "credentials and private keys are not accepted in runtime settings", details={"setting": key}
            )
        if key in _RESERVED_MODEL:
            raise _invalid("model option is owned by the backend", details={"setting": key})
        if key in model_options:
            raise _invalid("duplicate flat and model option", details={"setting": key})
        flat_options[key] = _copy_json(value)
    model_options.update(flat_options)

    if "threads" in values:
        threads = values["threads"]
        if type(threads) is not int or threads < 1:
            raise _invalid("threads must be a positive integer")
        if "n_threads" in model_options:
            raise _invalid("threads and n_threads are ambiguous duplicates", details={"setting": "n_threads"})
        model_options["n_threads"] = threads

    device = values.get("device")
    environment_updates: dict[str, str] = {}
    explicit_layers = model_options.get("n_gpu_layers")
    if explicit_layers is not None and type(explicit_layers) is not int:
        raise _invalid("n_gpu_layers must be an integer")

    if device == "cpu":
        if explicit_layers not in (None, 0):
            raise _invalid("CPU execution contradicts nonzero n_gpu_layers")
        model_options.setdefault("n_gpu_layers", 0)
    elif device == "cuda":
        index = values.get("device_index")
        if type(index) is not int or index < 0:
            raise _invalid("CUDA execution requires a non-negative device_index")
        model_options.setdefault("n_gpu_layers", -1)
        environment_updates["CUDA_VISIBLE_DEVICES"] = str(index)
    elif device == "metal":
        if "device_index" in values:
            raise _invalid("device_index is valid only for CUDA")
        model_options.setdefault("n_gpu_layers", -1)
    else:
        raise _invalid("device must resolve to cpu, cuda, or metal")

    model = {"model": str(model_path), **model_options}
    if projector_path is not None:
        model["clip_model_path"] = str(projector_path)
    server_config = {"host": bind_host, "port": port, **server_options, "models": [model]}
    return TranslatedSettings(server_config=_copy_json(server_config), environment_updates=environment_updates)
