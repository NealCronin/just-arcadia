"""Unit tests for backend protocols and the real TCP port inspector."""

from __future__ import annotations

import errno
import socket
from typing import Any

import pytest

from arcadia.services import TcpPortInspector


class ConnectedSocket:
    def __enter__(self) -> ConnectedSocket:
        return self

    def __exit__(self, *args: Any) -> None:
        return None


def test_tcp_port_inspector_detects_occupied_port(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[tuple[str, int], float]] = []

    def connect(address: tuple[str, int], *, timeout: float) -> ConnectedSocket:
        calls.append((address, timeout))
        return ConnectedSocket()

    monkeypatch.setattr(socket, "create_connection", connect)
    inspector = TcpPortInspector(host="127.0.0.1", timeout_seconds=0.5)

    assert inspector.is_in_use(19030)
    assert calls == [(("127.0.0.1", 19030), 0.5)]


def test_tcp_port_inspector_treats_connection_refusal_as_free(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(address: tuple[str, int], *, timeout: float) -> ConnectedSocket:
        raise ConnectionRefusedError(errno.ECONNREFUSED, "refused")

    monkeypatch.setattr(socket, "create_connection", refuse)

    assert not TcpPortInspector().is_in_use(19031)


def test_tcp_port_inspector_fails_closed_on_unexpected_socket_error(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = OSError(errno.EACCES, "denied")

    def fail(address: tuple[str, int], *, timeout: float) -> ConnectedSocket:
        raise expected

    monkeypatch.setattr(socket, "create_connection", fail)

    with pytest.raises(RuntimeError, match="probe failed") as raised:
        TcpPortInspector().is_in_use(19032)
    assert raised.value.__cause__ is expected


@pytest.mark.parametrize("timeout", [True, 0, -1, float("inf"), float("nan")])
def test_tcp_port_inspector_rejects_invalid_timeout(timeout: object) -> None:
    with pytest.raises(ValueError, match="finite positive"):
        TcpPortInspector(timeout_seconds=timeout)  # type: ignore[arg-type]


@pytest.mark.parametrize("host", ["", "bad host", "localhost:9000", 123])
def test_tcp_port_inspector_rejects_invalid_host(host: object) -> None:
    with pytest.raises(ValueError, match="host"):
        TcpPortInspector(host=host)  # type: ignore[arg-type]


def test_tcp_port_inspector_construction_performs_no_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_probe(*args: Any, **kwargs: Any) -> ConnectedSocket:
        raise AssertionError("construction probed the port")

    monkeypatch.setattr(socket, "create_connection", unexpected_probe)

    TcpPortInspector(host="localhost", timeout_seconds=0.1)
