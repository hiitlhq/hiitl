"""The Python unit suites run with the network refused (HTL-22 row 180).

Trevor's ruling on HTL-20: "the unit suites run with the network refused, by the mode table's CI/CD row", the table that
names Pure Local the mode for "Dev, CI/CD, air-gapped". Every suite under python/ runs as an offline machine would: a
name lookup of, or a connect to, any host but the loopback fails at once, naming the host. Loopback and local (AF_UNIX)
sockets stay open, so a server a test starts in-process still answers.

Each test runs in a directory of its own (HTL-23). A client given no store path opens `hiitl_audit.db` in the working
directory, and a hosted client pushes what that store holds before its call (row 192); a store shared across tests and
runs would hand one test what another left.
"""

from __future__ import annotations

import ipaddress
import socket

import pytest

REFUSED = "the unit suites run with the network refused (HTL-22 row 180)"
_LOOKUP, _CONNECT, _CONNECT_EX = socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex


def _loopback(host) -> bool:
    """Whether `host` stays on this machine: the loopback addresses, and `localhost`, which RFC 6761 reserves for them.
    No host (a passive lookup for a bind) names no remote."""
    if host is None:
        return True
    host = host.decode() if isinstance(host, bytes) else str(host)
    if host.lower() in ("", "localhost"):
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


def _lookup(host, *args, **kwargs):
    if not _loopback(host):
        raise socket.gaierror(socket.EAI_NONAME, f"lookup of {host} refused: {REFUSED}")
    return _LOOKUP(host, *args, **kwargs)


def _remote(sock: socket.socket, address) -> bool:
    return sock.family in (socket.AF_INET, socket.AF_INET6) and not _loopback(address[0])


def _connect(self, address):
    if _remote(self, address):
        raise ConnectionRefusedError(f"connect to {address[0]} refused: {REFUSED}")
    return _CONNECT(self, address)


def _connect_ex(self, address):
    if _remote(self, address):
        raise ConnectionRefusedError(f"connect to {address[0]} refused: {REFUSED}")
    return _CONNECT_EX(self, address)


@pytest.fixture(autouse=True)
def _own_directory(tmp_path_factory, monkeypatch):
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))


def pytest_configure(config):
    socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex = _lookup, _connect, _connect_ex


def pytest_unconfigure(config):
    socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex = _LOOKUP, _CONNECT, _CONNECT_EX
