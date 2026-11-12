import socket
import sys
from collections.abc import Iterator

import pytest

from memex.launcher.net import PORT_ATTEMPTS, AllPortsBusy, bind_first_free, bind_loopback


@pytest.fixture
def free_run() -> Iterator[int]:
    """A starting port with the next PORT_ATTEMPTS ports free (best effort)."""
    for _ in range(50):
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        start = probe.getsockname()[1]
        probe.close()
        if start + PORT_ATTEMPTS > 65535:
            continue
        try:
            held = [bind_loopback(p) for p in range(start, start + PORT_ATTEMPTS)]
        except OSError:
            continue
        for s in held:
            s.close()
        yield start
        return
    pytest.skip("no run of free ports")


def test_R01_binds_loopback_only(free_run: int):
    sock, port = bind_first_free(free_run)
    with sock:
        assert sock.getsockname() == ("127.0.0.1", port)


def test_R01_not_reachable_on_another_local_address(free_run: int):
    lan = _lan_address()
    if lan is None:
        pytest.skip("no non-loopback address on this machine")
    sock, port = bind_first_free(free_run)
    with sock, socket.socket() as client:
        client.settimeout(2)
        with pytest.raises(OSError):
            client.connect((lan, port))


def test_R03_busy_port_falls_back_to_the_next(free_run: int):
    with bind_loopback(free_run):
        sock, port = bind_first_free(free_run)
        with sock:
            assert port == free_run + 1
            assert sock.getsockname()[1] == port


def test_R03_all_ports_busy_is_an_error_not_a_random_port(free_run: int):
    held = [bind_loopback(p) for p in range(free_run, free_run + PORT_ATTEMPTS)]
    try:
        with pytest.raises(AllPortsBusy):
            bind_first_free(free_run)
    finally:
        for s in held:
            s.close()


def test_R02_a_second_bind_on_a_listening_port_fails(free_run: int):
    with bind_loopback(free_run), pytest.raises(OSError):
        bind_loopback(free_run)


@pytest.mark.windows
def test_R02_windows_socket_is_exclusive_and_not_reuseaddr(free_run: int):
    with bind_loopback(free_run) as sock:
        assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE)  # type: ignore[attr-defined]
        assert not sock.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR)


def _lan_address() -> str | None:
    """A non-loopback IPv4 address of this machine, found without sending a packet."""
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        infos = []
    for info in infos:
        addr = str(info[4][0])
        if not addr.startswith("127."):
            return addr
    if sys.platform != "win32":
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            try:
                s.connect(("10.255.255.255", 1))  # UDP connect: no packet is sent
                addr = s.getsockname()[0]
            except OSError:
                return None
            return None if addr.startswith("127.") or addr == "0.0.0.0" else addr
    return None
