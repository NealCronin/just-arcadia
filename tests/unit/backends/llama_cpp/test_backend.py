from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from arcadia.backends.llama_cpp import LLAMA_CPP_BACKEND_ID, LlamaCppBackend, LlamaCppBackendConfig
from arcadia.backends.llama_cpp.process import ServerDependencyUnavailable
from arcadia.models import (
    HuggingFaceFileSpec,
    LlamaServiceSpec,
    RequestedRuntimeSettings,
    ResolvedRuntimeSettings,
    SamServiceSpec,
    ServiceEndpoint,
    ServiceError,
    ServiceHealthError,
    ServiceStartupError,
    ServiceState,
    ServiceType,
)
from arcadia.services import BackendInstance, ServiceBackend
from tests.helpers.llama_cpp import FakeHealth, FakeLauncher, FakeProcess, FakeResolver, RecordingProgress


def _spec(*, visual: bool = False, filename: str = "model.gguf") -> LlamaServiceSpec:
    return LlamaServiceSpec(
        service_type=ServiceType.VISUAL_LLM if visual else ServiceType.LLM,
        port=19000,
        model=HuggingFaceFileSpec(repo_id="owner/model", filename=filename, revision="revision"),
        projector=(
            HuggingFaceFileSpec(repo_id="owner/projector", filename="projector.gguf", revision="projector-rev")
            if visual
            else None
        ),
        requested_settings=RequestedRuntimeSettings(values={"threads": 8}),
    )


def _settings(device: str = "cpu") -> ResolvedRuntimeSettings:
    values: dict[str, object] = {"device": device, "threads": 8}
    if device == "cuda":
        values["device_index"] = 2
    return ResolvedRuntimeSettings(backend="llama_cpp", values=values)


def _boundaries(tmp_path: Path, *, process: FakeProcess | None = None, health: FakeHealth | None = None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    model = tmp_path / "model.gguf"
    projector = tmp_path / "projector.gguf"
    model.write_bytes(b"model")
    projector.write_bytes(b"projector")
    resolver = FakeResolver(model, projector)
    launcher = FakeLauncher(process)
    selected_health = FakeHealth() if health is None else health
    backend = LlamaCppBackend(
        config=LlamaCppBackendConfig(runtime_dir=tmp_path / "runtime", python_executable="/python"),
        file_resolver=resolver,
        process_launcher=launcher,
        health_probe=selected_health,
        clock=lambda: datetime(2026, 1, 2, tzinfo=UTC),
        sleeper=lambda _: None,
    )
    return backend, resolver, launcher, selected_health


def test_public_api_and_protocol(tmp_path: Path) -> None:
    backend, _, _, _ = _boundaries(tmp_path)
    assert LLAMA_CPP_BACKEND_ID == "llama_cpp"
    assert backend.backend_id == "llama_cpp"
    assert isinstance(backend, ServiceBackend)


def test_start_generates_exact_command_config_and_detached_instance(tmp_path: Path) -> None:
    class InspectingLauncher(FakeLauncher):
        config: dict[str, object] | None = None

        def launch(self, command, *, cwd, log_path, environment_updates):  # type: ignore[no-untyped-def]
            self.config = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
            return super().launch(
                command,
                cwd=cwd,
                log_path=log_path,
                environment_updates=environment_updates,
            )

    model = tmp_path / "model.gguf"
    projector = tmp_path / "projector.gguf"
    model.write_bytes(b"model")
    projector.write_bytes(b"projector")
    resolver = FakeResolver(model, projector)
    launcher = InspectingLauncher()
    backend = LlamaCppBackend(
        config=LlamaCppBackendConfig(runtime_dir=tmp_path / "runtime", python_executable="/python"),
        file_resolver=resolver,
        process_launcher=launcher,
        health_probe=FakeHealth(),
    )
    spec = _spec(visual=True)
    spec_before = spec.model_dump_json()
    settings = _settings("cuda")
    settings_before = settings.model_dump_json()
    progress = RecordingProgress()
    instance = backend.start(spec, settings, progress)

    call = launcher.calls[0]
    assert call["command"][:4] == ["/python", "-m", "llama_cpp.server", "--config_file"]
    assert call["environment_updates"] == {"CUDA_VISIBLE_DEVICES": "2"}
    assert launcher.config == {
        "host": "127.0.0.1",
        "port": 19000,
        "models": [
            {
                "model": str(model),
                "clip_model_path": str(projector),
                "n_threads": 8,
                "n_gpu_layers": -1,
            }
        ],
    }
    config_path = Path(call["command"][-1])
    assert not config_path.exists()
    assert instance.endpoint.host == "127.0.0.1"
    assert instance.resolved_settings == settings
    assert spec.model_dump_json() == spec_before
    assert settings.model_dump_json() == settings_before
    assert resolver.calls[0][0] == "model" and resolver.calls[1][0] == "projector"
    assert [state for state, _, _ in progress.reports][-1] == ServiceState.STARTING


def test_bind_advertise_and_health_hosts_are_separate(tmp_path: Path) -> None:
    model = tmp_path / "model.gguf"
    model.write_bytes(b"model")
    health = FakeHealth()
    backend = LlamaCppBackend(
        config=LlamaCppBackendConfig(
            bind_host="0.0.0.0",
            advertise_host="node.example",
            runtime_dir=tmp_path / "runtime",
        ),
        file_resolver=FakeResolver(model),
        process_launcher=FakeLauncher(),
        health_probe=health,
    )
    instance = backend.start(_spec(), _settings(), RecordingProgress())
    assert instance.endpoint.host == "node.example"
    assert health.calls[0][0] == "127.0.0.1"


def test_rejects_invalid_specs_backend_globs_and_split_before_resolution(tmp_path: Path) -> None:
    backend, resolver, _, _ = _boundaries(tmp_path)
    invalid_cases = [
        (SamServiceSpec(port=19000, checkpoint_path="checkpoint.pt"), _settings(), "llama_cpp_spec_invalid"),
        (_spec(), ResolvedRuntimeSettings(backend="other", values={"device": "cpu"}), "llama_cpp_backend_mismatch"),
        (_spec(filename="*.gguf"), _settings(), "llama_cpp_spec_invalid"),
        (_spec(filename="model-00001-of-00005.gguf"), _settings(), "llama_cpp_split_gguf_unsupported"),
    ]
    for spec, settings, code in invalid_cases:
        with pytest.raises(ServiceStartupError) as captured:
            backend.start(spec, settings, RecordingProgress())
        assert captured.value.code == code
    assert resolver.calls == []


def test_missing_llama_server_is_dependency_error_before_hugging_face_resolution(tmp_path: Path) -> None:
    class MissingServerLauncher(FakeLauncher):
        def verify_server(self, python_executable: str, *, timeout_seconds: float) -> None:
            assert python_executable == "/configured/python"
            assert timeout_seconds == 30.0
            raise ServerDependencyUnavailable("llama_cpp.server is missing")

    model = tmp_path / "model.gguf"
    model.write_bytes(b"model")
    resolver = FakeResolver(model)
    launcher = MissingServerLauncher()
    backend = LlamaCppBackend(
        config=LlamaCppBackendConfig(
            runtime_dir=tmp_path / "runtime",
            python_executable="/configured/python",
        ),
        file_resolver=resolver,
        process_launcher=launcher,
        health_probe=FakeHealth(),
    )

    with pytest.raises(ServiceStartupError) as captured:
        backend.start(_spec(), _settings(), RecordingProgress())
    assert captured.value.code == "llama_cpp_dependency_missing"
    assert captured.value.details["dependency"] == "llama_cpp.server"
    assert resolver.calls == []
    assert launcher.calls == []


def test_projector_failure_prevents_launch_and_cleans_nothing_cached(tmp_path: Path) -> None:
    backend, resolver, launcher, _ = _boundaries(tmp_path)
    resolver.error_role = "projector"
    with pytest.raises(ServiceStartupError) as captured:
        backend.start(_spec(visual=True), _settings(), RecordingProgress())
    assert captured.value.code == "llama_cpp_model_resolve_failed"
    assert launcher.calls == []
    assert (tmp_path / "model.gguf").exists()


def test_launch_failure_is_typed_and_attempt_directory_is_removed(tmp_path: Path) -> None:
    backend, _, launcher, _ = _boundaries(tmp_path)
    launcher.error = OSError("launch failed")
    with pytest.raises(ServiceStartupError) as captured:
        backend.start(_spec(), _settings(), RecordingProgress())
    assert captured.value.code == "llama_cpp_process_launch_failed"
    assert list((tmp_path / "runtime").iterdir()) == []


def test_early_exit_timeout_and_base_exception_clean_processes(tmp_path: Path) -> None:
    exited = FakeProcess(return_code=7)
    backend, _, _, _ = _boundaries(tmp_path / "exit", process=exited)
    with pytest.raises(ServiceStartupError) as captured:
        backend.start(_spec(), _settings(), RecordingProgress())
    assert captured.value.code == "llama_cpp_server_exited"
    assert exited.terminate_calls == 1

    timeout_root = tmp_path / "timeout"
    timeout_root.mkdir()
    model = timeout_root / "model.gguf"
    model.write_bytes(b"model")
    timed_process = FakeProcess()
    timeout_backend = LlamaCppBackend(
        config=LlamaCppBackendConfig(
            runtime_dir=timeout_root / "runtime",
            startup_timeout_seconds=0.001,
            poll_interval_seconds=0.001,
        ),
        file_resolver=FakeResolver(model),
        process_launcher=FakeLauncher(timed_process),
        health_probe=FakeHealth([ValueError("malformed")] * 10000),
        sleeper=lambda _: None,
    )
    with pytest.raises(ServiceStartupError) as captured:
        timeout_backend.start(_spec(), _settings(), RecordingProgress())
    assert captured.value.code == "llama_cpp_startup_timeout"
    assert timed_process.terminate_calls == 1

    interrupt_root = tmp_path / "interrupt"
    interrupt_root.mkdir()
    interrupt_model = interrupt_root / "model.gguf"
    interrupt_model.write_bytes(b"model")

    class InterruptingHealth:
        def probe(self, host: str, port: int, *, timeout_seconds: float) -> None:
            raise KeyboardInterrupt

    interrupted_process = FakeProcess()
    interrupt_backend = LlamaCppBackend(
        config=LlamaCppBackendConfig(runtime_dir=interrupt_root / "runtime"),
        file_resolver=FakeResolver(interrupt_model),
        process_launcher=FakeLauncher(interrupted_process),
        health_probe=InterruptingHealth(),
    )
    with pytest.raises(KeyboardInterrupt):
        interrupt_backend.start(_spec(), _settings(), RecordingProgress())
    assert interrupted_process.terminate_calls == 1


def test_health_stop_diagnostics_and_logs_before_and_after_stop(tmp_path: Path) -> None:
    process = FakeProcess()
    backend, _, launcher, health = _boundaries(tmp_path, process=process)
    launcher.log_text = b"bad\xff\none\ntwo\nthree\n"
    instance = backend.start(_spec(), _settings(), RecordingProgress())
    backend.check_health(instance)
    diagnostics = backend.diagnostics(instance)
    assert diagnostics["alive"] is True
    assert diagnostics["model_filename"] == "model.gguf"
    assert "runtime" not in json.dumps(diagnostics)
    assert backend.read_logs(instance, tail_lines=2) == "two\nthree\n"

    progress = RecordingProgress()
    backend.stop(instance, progress)
    backend.stop(instance, progress)
    assert process.terminate_calls == 1
    assert process.close_calls == 1
    assert backend.diagnostics(instance)["stopped_at"]
    assert backend.read_logs(instance, tail_lines=5).startswith("bad�")
    assert len(health.calls) == 2


def test_health_failures_and_process_exit_are_typed(tmp_path: Path) -> None:
    process = FakeProcess()
    backend, _, _, health = _boundaries(tmp_path, process=process)
    instance = backend.start(_spec(), _settings(), RecordingProgress())
    health.failures.append(TimeoutError("slow"))
    with pytest.raises(ServiceHealthError) as captured:
        backend.check_health(instance)
    assert captured.value.code == "llama_cpp_health_failed"
    assert captured.value.cause is not None
    process.return_code = 9
    with pytest.raises(ServiceHealthError) as captured:
        backend.check_health(instance)
    assert captured.value.code == "llama_cpp_process_exited"
    assert captured.value.details == {"pid": 4321, "return_code": 9}


def test_foreign_handles_and_invalid_log_bounds_are_rejected(tmp_path: Path) -> None:
    backend, _, _, _ = _boundaries(tmp_path)
    foreign = BackendInstance(
        endpoint=ServiceEndpoint(host="127.0.0.1", port=19000, service_type=ServiceType.LLM),
        resolved_settings=_settings(),
        handle=object(),
    )
    with pytest.raises(ServiceHealthError, match="invalid"):
        backend.check_health(foreign)
    for operation in (
        lambda: backend.stop(foreign, RecordingProgress()),
        lambda: backend.diagnostics(foreign),
        lambda: backend.read_logs(foreign, tail_lines=1),
    ):
        with pytest.raises(ServiceError) as captured:
            operation()
        assert captured.value.code == "llama_cpp_handle_invalid"

    instance = backend.start(_spec(), _settings(), RecordingProgress())
    for value in (0, -1, True, 5001):
        with pytest.raises(ServiceError) as captured:
            backend.read_logs(instance, tail_lines=value)
        assert captured.value.code == "llama_cpp_logs_failed"
