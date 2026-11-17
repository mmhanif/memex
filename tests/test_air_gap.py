"""SPEC §16.5 (1): in tests, any socket connection beyond loopback raises."""

import contextlib
import socket

import pytest

from tests.air_gap import AirGapViolation

OUTSIDE = ("192.0.2.1", 9)  # TEST-NET-1: never routed, so nothing leaves even if the guard fails


def test_a_tcp_connect_beyond_loopback_raises():
    with socket.socket() as sock, pytest.raises(AirGapViolation):
        sock.connect(OUTSIDE)


def test_connect_ex_beyond_loopback_raises():
    with socket.socket() as sock, pytest.raises(AirGapViolation):
        sock.connect_ex(OUTSIDE)


def test_create_connection_beyond_loopback_raises():
    with pytest.raises(AirGapViolation):
        socket.create_connection(OUTSIDE, timeout=1)


def test_a_udp_connect_beyond_loopback_raises():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock, pytest.raises(AirGapViolation):
        sock.connect(OUTSIDE)


def test_a_host_name_raises_before_any_lookup():
    with socket.socket() as sock, pytest.raises(AirGapViolation):
        sock.connect(("example.com", 80))


def test_ipv6_beyond_loopback_raises():
    if not socket.has_ipv6:
        pytest.skip("no IPv6")
    with socket.socket(socket.AF_INET6) as sock, pytest.raises(AirGapViolation):
        sock.connect(("2001:db8::1", 9))


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
def test_loopback_still_connects(host: str):
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        with socket.create_connection((host, server.getsockname()[1]), timeout=5):
            pass


@pytest.mark.lan
def test_the_lan_marker_lifts_the_guard_for_one_test():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect(OUTSIDE)  # UDP connect sends no packet


def test_code_that_handles_network_failures_does_not_swallow_a_violation():
    with pytest.raises(AirGapViolation), contextlib.suppress(OSError):
        socket.create_connection(OUTSIDE, timeout=1)
