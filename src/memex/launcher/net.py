"""Binding the listening socket (SPEC §13.3, rules R1-R3).

The launcher binds the socket itself and hands it to uvicorn, so the port the
browser is sent to is always one this process owns.
"""

import socket
import sys

HOST = "127.0.0.1"  # never 0.0.0.0 or :: (R1)
PORT_ATTEMPTS = 10  # the preferred port, then the next 9 in order; never a random one


class AllPortsBusy(Exception):
    def __init__(self, first: int) -> None:
        last = first + PORT_ATTEMPTS - 1
        super().__init__(f"Ports {first}-{last} are all in use: free one or pass --port")
        self.first = first


def bind_loopback(port: int) -> socket.socket:
    """A listening socket on 127.0.0.1:`port`. Raises OSError if it's taken."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if sys.platform == "win32":
            # Stops another program binding the same port over us (R2).
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)  # type: ignore[attr-defined]
        else:
            # POSIX: only lets a relaunch reuse a port in TIME_WAIT, never steal a listener.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((HOST, port))
        sock.listen(128)
    except BaseException:
        sock.close()
        raise
    return sock


def bind_first_free(port: int) -> tuple[socket.socket, int]:
    """Bind `port`, else the next free one of the following 9 (R3)."""
    for candidate in range(port, min(port + PORT_ATTEMPTS, 65536)):
        try:
            return bind_loopback(candidate), candidate
        except OSError:
            continue
    raise AllPortsBusy(port)
