"""The runtime air-gap guard (SPEC §16.5, item 1).

While installed, connecting a socket anywhere but loopback raises AirGapViolation,
before any packet or name lookup. It covers this test process only; launcher tests'
`memex` processes are covered by the static scan and the e2e request check instead.
"""

import ipaddress
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


class AirGapViolation(Exception):
    """Not an OSError: code that expects network failures must not swallow it as one."""


lifted = False  # set for one test by the `lan` marker


def is_loopback(address: Any) -> bool:
    if not isinstance(address, tuple):
        return True  # AF_UNIX paths and the like never leave the machine
    host = address[0]
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False  # any other host name: refuse rather than look it up


@contextmanager
def guard() -> Iterator[None]:
    connect, connect_ex = socket.socket.connect, socket.socket.connect_ex

    def check(address: Any) -> None:
        if not lifted and not is_loopback(address):
            raise AirGapViolation(f"Air gap: tests may only connect to loopback, not {address!r}")

    def guarded_connect(self: socket.socket, address: Any) -> None:
        check(address)
        connect(self, address)

    def guarded_connect_ex(self: socket.socket, address: Any) -> int:
        check(address)
        return connect_ex(self, address)

    socket.socket.connect = guarded_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = guarded_connect_ex  # type: ignore[method-assign]
    try:
        yield
    finally:
        socket.socket.connect, socket.socket.connect_ex = connect, connect_ex  # type: ignore[method-assign]
