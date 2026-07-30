from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

from arcadia.backends.llama_cpp.files import HuggingFaceFileResolver
from arcadia.backends.llama_cpp.process import ManagedSubprocess, SubprocessLauncher
from arcadia.models import HuggingFaceFileSpec, ServiceState
from tests.helpers.llama_cpp import RecordingProgress


def test_hugging_face_cache_hit_uses_exact_arguments(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "model.gguf"
    target.write_bytes(b"gguf")
    calls: list[dict[str, Any]] = []

    def download(**kwargs: Any) -> str:
        calls.append(kwargs)
        return str(target)

    module = types.ModuleType("huggingface_hub")
    module.hf_hub_download = download  # type: ignore[attr-defined]
    errors = types.ModuleType("huggingface_hub.errors")
    errors.LocalEntryNotFoundError = type("LocalEntryNotFoundError", (Exception,), {})  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "huggingface_hub", module)
    monkeypatch.setitem(sys.modules, "huggingface_hub.errors", errors)

    progress = RecordingProgress()
    spec = HuggingFaceFileSpec(repo_id="owner/model", filename="exact.gguf", revision="commit")
    resolved = HuggingFaceFileResolver(cache_dir=tmp_path / "cache").resolve(spec, role="model", progress=progress)
    assert resolved == target
    assert calls == [
        {
            "repo_id": "owner/model",
            "filename": "exact.gguf",
            "revision": "commit",
            "cache_dir": tmp_path / "cache",
            "local_files_only": True,
        }
    ]
    assert [state for state, _, _ in progress.reports] == [ServiceState.RESOLVING]


def test_hugging_face_cache_miss_reports_download(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "projector.gguf"
    target.write_bytes(b"gguf")
    local_miss = type("LocalEntryNotFoundError", (Exception,), {})
    calls: list[dict[str, Any]] = []

    def download(**kwargs: Any) -> str:
        calls.append(kwargs)
        if kwargs.get("local_files_only"):
            raise local_miss()
        return str(target)

    module = types.ModuleType("huggingface_hub")
    module.hf_hub_download = download  # type: ignore[attr-defined]
    errors = types.ModuleType("huggingface_hub.errors")
    errors.LocalEntryNotFoundError = local_miss  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "huggingface_hub", module)
    monkeypatch.setitem(sys.modules, "huggingface_hub.errors", errors)

    progress = RecordingProgress()
    spec = HuggingFaceFileSpec(repo_id="owner/model", filename="exact.gguf", revision="commit")
    HuggingFaceFileResolver().resolve(spec, role="projector", progress=progress)
    assert len(calls) == 2
    assert calls[0]["local_files_only"] is True
    assert "local_files_only" not in calls[1]
    assert [state for state, _, _ in progress.reports] == [ServiceState.RESOLVING, ServiceState.DOWNLOADING]
    assert progress.reports[-1][1] is None


class FakePopen:
    def __init__(self, *, waits: list[object] | None = None) -> None:
        self.pid = 2468
        self.return_code: int | None = None
        self.waits = [] if waits is None else list(waits)
        self.signals: list[int] = []

    def poll(self) -> int | None:
        return self.return_code

    def wait(self, timeout: float | None = None) -> int:
        if self.waits:
            outcome = self.waits.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
        self.return_code = 0
        return 0

    def send_signal(self, value: int) -> None:
        self.signals.append(value)


def test_subprocess_launcher_uses_argument_list_shell_false_and_new_session(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}
    process = FakePopen()

    def popen(command: list[str], **kwargs: Any) -> FakePopen:
        captured["command"] = command
        captured.update(kwargs)
        return process

    log_path = tmp_path / "server.log"
    launcher = SubprocessLauncher(platform="linux", popen_factory=popen)
    managed = launcher.launch(
        ["python", "-m", "llama_cpp.server", "--config_file", "config.json"],
        cwd=tmp_path,
        log_path=log_path,
        environment_updates={"CUDA_VISIBLE_DEVICES": "1"},
    )
    assert managed.pid == 2468
    assert captured["command"] == ["python", "-m", "llama_cpp.server", "--config_file", "config.json"]
    assert captured["shell"] is False
    assert captured["start_new_session"] is True
    assert captured["env"]["CUDA_VISIBLE_DEVICES"] == "1"
    assert captured["stdout"].closed


def test_posix_containment_graceful_then_forced(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    process = FakePopen(waits=[subprocess.TimeoutExpired("server", 1), 0])
    signals: list[int] = []
    monkeypatch.setattr("os.getpgid", lambda pid: pid)
    monkeypatch.setattr("os.killpg", lambda pid, signal_number: signals.append(signal_number))
    managed = ManagedSubprocess(process, platform="linux")  # type: ignore[arg-type]
    managed.terminate_tree(stop_timeout_seconds=1, kill_timeout_seconds=1)
    assert signals == [15, 9]


def test_windows_launcher_marks_owned_process_group(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    def popen(command: list[str], **kwargs: Any) -> FakePopen:
        captured.update(kwargs)
        return FakePopen()

    SubprocessLauncher(platform="win32", popen_factory=popen).launch(
        ["python", "-m", "llama_cpp.server", "--config_file", "config.json"],
        cwd=tmp_path,
        log_path=tmp_path / "server.log",
        environment_updates={},
    )
    assert captured["creationflags"] != 0
    assert captured["shell"] is False
    assert "start_new_session" not in captured


def test_windows_containment_falls_back_to_owned_tree_taskkill(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess
    from types import SimpleNamespace

    process = FakePopen(waits=[subprocess.TimeoutExpired("server", 1), 0])
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def run(command: list[str], **kwargs: Any) -> SimpleNamespace:
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", run)
    managed = ManagedSubprocess(process, platform="win32")  # type: ignore[arg-type]
    managed.terminate_tree(stop_timeout_seconds=1, kill_timeout_seconds=1)
    assert calls[0][0] == ["taskkill", "/PID", "2468", "/T", "/F"]
    assert calls[0][1]["shell"] is False
