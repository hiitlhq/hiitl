"""Row 180 (HTL-22): the Python unit suites run with the network refused.

Trevor's ruling on HTL-20: "the unit suites run with the network refused, by the mode table's CI/CD row", the table that
names Pure Local the mode for "Dev, CI/CD, air-gapped". Design: the HTL-22 test design, row 180, behaviors 1 and 2. The
guard is python/conftest.py; behavior 3, the exit cell, is the suites passing with it on. The TypeScript side is
typescript/packages/sdk/tests/unit/row180.test.ts.
"""

from __future__ import annotations

import socket
import threading

from conftest import REFUSED

PAST_THE_MACHINE = "192.0.2.1"  # TEST-NET-1 (RFC 5737): documentation only, routed nowhere
NAMED = "api.example.invalid"  # RFC 6761: a name that never resolves
UNANSWERED_S = 2.0  # where nothing refuses, the connect is given up after this and reports no refusal


def _refusal(attempt) -> BaseException | None:
    """The error that ends an attempt, or None if it completes or is given up."""
    try:
        attempt()
    except (TimeoutError, socket.timeout):
        return None
    except OSError as e:
        return e
    return None


def _connect(host: str):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(UNANSWERED_S)
        sock.connect((host, 443))


def _connect_ex(host: str):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(UNANSWERED_S)
        code = sock.connect_ex((host, 443))
    if code:
        raise OSError(code, f"connect_ex to {host}: {code}")


def test_a_connect_past_the_loopback_is_refused_naming_the_host_and_the_rule():
    """Behavior 1: a connect (and connect_ex) to an address past the machine, and a lookup of a name, are refused at
    once, naming the host and the rule."""
    attempts = ((_connect, PAST_THE_MACHINE), (_connect_ex, PAST_THE_MACHINE),
                (lambda h: socket.getaddrinfo(h, 443), NAMED),
                (lambda h: socket.create_connection((h, 443), UNANSWERED_S).close(), NAMED))
    for attempt, host in attempts:
        refused = _refusal(lambda: attempt(host))

        assert isinstance(refused, (ConnectionRefusedError, socket.gaierror)), (attempt, host, refused)
        assert host in str(refused) and REFUSED in str(refused), str(refused)


def test_the_loopback_stays_open():
    """Behavior 2: a client connects to a server listening on 127.0.0.1, and `localhost` resolves."""
    with socket.create_server(("127.0.0.1", 0)) as server:
        server.settimeout(UNANSWERED_S)
        port = server.getsockname()[1]
        threading.Thread(target=lambda: _refusal(lambda: server.accept()[0].close()), daemon=True).start()
        refused = _refusal(lambda: socket.create_connection(("127.0.0.1", port), UNANSWERED_S).close())
    resolved = _refusal(lambda: socket.getaddrinfo("localhost", port))

    assert refused is None, refused
    assert resolved is None, resolved
