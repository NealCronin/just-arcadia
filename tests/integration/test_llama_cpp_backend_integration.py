"""Session 01/05/06/07 integration without a llama.cpp installation or model download."""

from __future__ import annotations

import json
import socket
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from arcadia.backends.llama_cpp import LlamaCppBackend, LlamaCppBackendConfig
from arcadia.backends.llama_cpp.process import SubprocessLauncher
from arcadia.hardware import CpuInfo, HardwareCapabilities, MemoryInfo, OperatingSystem, PlatformInfo
from arcadia.models import HuggingFaceFileSpec, LlamaServiceSpec, RequestedRuntimeSettings, ServiceState, ServiceType
from arcadia.models.errors import ServiceStartupError
from arcadia.services import ServiceManager

_SERVER_CODE = """
import http.server
import json
import sys

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/v1/models':
            body = json.dumps({'data': [{'id': 'local-test'}]}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()
    def log_message(self, format, *args):
        print(format % args, flush=True)

http.server.ThreadingHTTPServer(('127.0.0.1', int(sys.argv[1])), Handler).serve_forever()
"""


class FreeInspector:
    def is_in_use(self, port: int) -> bool:
        return False


class MappingResolver:
    def __init__(self, files: Mapping[str, Path]) -> None:
        self.files = dict(files)
        self.calls: list[str] = []

    def resolve(self, file_spec: HuggingFaceFileSpec, *, role: str, progress: Any) -> Path:
        self.calls.append(f"{role}:{file_spec.filename}")
        progress.report(state=ServiceState.RESOLVING, message=f"Resolving {role} file")
        return self.files[file_spec.filename]


class LocalServerLauncher:
    def __init__(self) -> None:
        self.real = SubprocessLauncher()
        self.configs: list[dict[str, Any]] = []
        self.commands: list[list[str]] = []

    def launch(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        log_path: Path,
        environment_updates: Mapping[str, str],
    ):
        config = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
        self.configs.append(config)
        self.commands.append(list(command))
        return self.real.launch(
            [sys.executable, "-u", "-c", _SERVER_CODE, str(config["port"])],
            cwd=cwd,
            log_path=log_path,
            environment_updates=environment_updates,
        )


class ExitingLauncher:
    def __init__(self) -> None:
        self.real = SubprocessLauncher()

    def launch(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        log_path: Path,
        environment_updates: Mapping[str, str],
    ):
        return self.real.launch(
            [sys.executable, "-c", "print('startup failed', flush=True); raise SystemExit(4)"],
            cwd=cwd,
            log_path=log_path,
            environment_updates=environment_updates,
        )


def _port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _hardware() -> HardwareCapabilities:
    return HardwareCapabilities(
        detected_at=datetime.now(UTC),
        platform=PlatformInfo(
            operating_system=OperatingSystem.LINUX,
            release="test",
            version="test",
            machine="test",
            python_version=sys.version.split()[0],
        ),
        cpu=CpuInfo(logical_cores=4, architecture="test"),
        memory=MemoryInfo(total_bytes=8 * 1024**3),
    )


def _spec(port: int, filename: str, *, visual: bool = False) -> LlamaServiceSpec:
    return LlamaServiceSpec(
        service_type=ServiceType.VISUAL_LLM if visual else ServiceType.LLM,
        port=port,
        model=HuggingFaceFileSpec(repo_id="owner/model", filename=filename, revision="commit"),
        projector=(
            HuggingFaceFileSpec(repo_id="owner/projector", filename="projector.gguf", revision="commit")
            if visual
            else None
        ),
        requested_settings=RequestedRuntimeSettings(values={"device": "cpu", "threads": 2}),
    )


def test_real_manager_process_readiness_logs_reuse_and_replacement(tmp_path: Path) -> None:
    port = _port()
    files = {
        "one.gguf": tmp_path / "one.gguf",
        "two.gguf": tmp_path / "two.gguf",
        "projector.gguf": tmp_path / "projector.gguf",
    }
    for path in files.values():
        path.write_bytes(b"fake")
    resolver = MappingResolver(files)
    launcher = LocalServerLauncher()
    backend = LlamaCppBackend(
        config=LlamaCppBackendConfig(
            runtime_dir=tmp_path / "runtime",
            startup_timeout_seconds=5,
            health_timeout_seconds=1,
            poll_interval_seconds=0.02,
            stop_timeout_seconds=2,
            kill_timeout_seconds=2,
        ),
        file_resolver=resolver,
        process_launcher=launcher,
    )
    manager = ServiceManager(
        hardware=_hardware(),
        backends={ServiceType.LLM: backend, ServiceType.VISUAL_LLM: backend},
        port_inspector=FreeInspector(),
        register_atexit=False,
    )

    first = manager.ensure_service(_spec(port, "one.gguf"))
    assert first.state == ServiceState.READY
    assert manager.ensure_service(_spec(port, "one.gguf")).state == ServiceState.READY
    assert len(launcher.commands) == 1
    diagnostics = manager.get_diagnostics(port)
    logs = manager.get_logs(port, tail_lines=20)
    assert diagnostics.details["alive"] is True
    assert "/v1/models" in logs.text
    assert "handle" not in first.model_dump_json()
    json.loads(first.model_dump_json())
    json.loads(diagnostics.model_dump_json())
    json.loads(logs.model_dump_json())

    replacement = manager.ensure_service(_spec(port, "two.gguf", visual=True))
    assert replacement.state == ServiceState.READY
    assert len(launcher.commands) == 2
    assert launcher.configs[-1]["models"][0]["clip_model_path"] == str(files["projector.gguf"])
    assert resolver.calls[-2:] == ["model:two.gguf", "projector:projector.gguf"]
    assert manager.stop_service(port).state == ServiceState.STOPPED
    manager.shutdown()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX runtime-directory cleanup smoke")
def test_failed_real_child_start_leaves_no_process_or_attempt_directory(tmp_path: Path) -> None:
    model = tmp_path / "model.gguf"
    model.write_bytes(b"fake")
    runtime = tmp_path / "runtime"
    backend = LlamaCppBackend(
        config=LlamaCppBackendConfig(
            runtime_dir=runtime,
            startup_timeout_seconds=2,
            poll_interval_seconds=0.01,
            stop_timeout_seconds=1,
            kill_timeout_seconds=1,
        ),
        file_resolver=MappingResolver({"one.gguf": model}),
        process_launcher=ExitingLauncher(),
    )
    manager = ServiceManager(
        hardware=_hardware(),
        backends={ServiceType.LLM: backend},
        port_inspector=FreeInspector(),
        register_atexit=False,
    )
    with pytest.raises(ServiceStartupError) as captured:
        manager.ensure_service(_spec(_port(), "one.gguf"))
    assert captured.value.code == "llama_cpp_server_exited"
    assert runtime.exists() and list(runtime.iterdir()) == []
    manager.shutdown()
