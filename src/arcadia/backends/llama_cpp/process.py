"""Owned subprocess launch and complete process-tree termination."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import IO, Any, Protocol


class OwnedProcess(Protocol):
    @property
    def pid(self) -> int: ...

    def poll(self) -> int | None: ...

    def terminate_tree(self, *, stop_timeout_seconds: float, kill_timeout_seconds: float) -> None: ...

    def close(self) -> None: ...


class ProcessLauncher(Protocol):
    def launch(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        log_path: Path,
        environment_updates: Mapping[str, str],
    ) -> OwnedProcess: ...


class ManagedSubprocess:
    """A child whose POSIX process group or Windows process tree is backend-owned."""

    def __init__(self, process: subprocess.Popen[bytes], *, platform: str) -> None:
        self._process = process
        self._platform = platform
        self._lock = threading.Lock()
        self._closed = False

    @property
    def pid(self) -> int:
        return self._process.pid

    def poll(self) -> int | None:
        return self._process.poll()

    def terminate_tree(self, *, stop_timeout_seconds: float, kill_timeout_seconds: float) -> None:
        with self._lock:
            if self._process.poll() is not None:
                self._process.wait()
                return
            if self._platform == "win32":
                self._terminate_windows(stop_timeout_seconds, kill_timeout_seconds)
            else:
                self._terminate_posix(stop_timeout_seconds, kill_timeout_seconds)

    def _terminate_posix(self, stop_timeout_seconds: float, kill_timeout_seconds: float) -> None:
        process_group = os.getpgid(self.pid)
        try:
            os.killpg(process_group, signal.SIGTERM)
        except ProcessLookupError:
            self._process.wait()
            return
        try:
            self._process.wait(timeout=stop_timeout_seconds)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process_group, signal.SIGKILL)
        except ProcessLookupError:
            pass
        self._process.wait(timeout=kill_timeout_seconds)

    def _terminate_windows(self, stop_timeout_seconds: float, kill_timeout_seconds: float) -> None:
        try:
            self._process.send_signal(getattr(signal, "CTRL_BREAK_EVENT", signal.SIGTERM))
            self._process.wait(timeout=stop_timeout_seconds)
            return
        except (OSError, subprocess.TimeoutExpired):
            pass
        # Narrow fallback: this PID is exactly the child returned by this launcher;
        # /T is required so descendants are terminated too. No shell is involved.
        completed = subprocess.run(
            ["taskkill", "/PID", str(self.pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            shell=False,
            timeout=kill_timeout_seconds,
        )
        try:
            self._process.wait(timeout=kill_timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"owned Windows process tree did not exit (taskkill={completed.returncode})") from exc

    def close(self) -> None:
        with self._lock:
            self._closed = True


class SubprocessLauncher:
    """Launch ``llama_cpp.server`` without a shell and with platform containment."""

    def __init__(self, *, platform: str | None = None, popen_factory: Any = subprocess.Popen) -> None:
        self._platform = sys.platform if platform is None else platform
        self._popen_factory = popen_factory

    def launch(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        log_path: Path,
        environment_updates: Mapping[str, str],
    ) -> ManagedSubprocess:
        environment = os.environ.copy()
        environment.update(environment_updates)
        log_file: IO[bytes] | None = None
        try:
            log_file = log_path.open("ab", buffering=0)
            keyword_arguments: dict[str, Any] = {
                "cwd": cwd,
                "env": environment,
                "stdin": subprocess.DEVNULL,
                "stdout": log_file,
                "stderr": subprocess.STDOUT,
                "shell": False,
            }
            if self._platform == "win32":
                keyword_arguments["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            else:
                keyword_arguments["start_new_session"] = True
            process = self._popen_factory(list(command), **keyword_arguments)
        finally:
            if log_file is not None:
                log_file.close()
        return ManagedSubprocess(process, platform=self._platform)
