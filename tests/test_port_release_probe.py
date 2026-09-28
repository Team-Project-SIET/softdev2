"""Controlled Linux socket cases for the T17 terminal endpoint assertion."""

import errno
import os
import select
import socket
import subprocess
import sys
import threading

import port_release_probe
import pytest
from port_release_probe import PortReleaseError, verify_port_release


def _free_ports() -> tuple[int, int]:
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as game,
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as admin,
    ):
        game.bind(("127.0.0.1", 0))
        admin.bind(("127.0.0.1", 0))
        return game.getsockname()[1], admin.getsockname()[1]


def test_free_game_and_admin_ports_release_without_probe_socket_leak() -> None:
    game, admin = _free_ports()
    evidence = verify_port_release(game, admin, owned_pgid=os.getpgrp(), process_checks_passed=True)
    assert [(item.role, item.protocol, item.state) for item in evidence] == [
        ("game", "tcp", "released"),
        ("game", "udp", "released"),
        ("admin", "tcp", "released"),
    ]
    for port, kind in (
        (game, socket.SOCK_STREAM),
        (game, socket.SOCK_DGRAM),
        (admin, socket.SOCK_STREAM),
    ):
        with socket.socket(socket.AF_INET, kind) as check:
            check.bind(("127.0.0.1", port))


@pytest.mark.parametrize("role", ["game", "admin"])
def test_owned_tcp_listener_reports_exact_role_port_and_family(role: str) -> None:
    game, admin = _free_ports()
    port = game if role == "game" else admin
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", port))
        listener.listen()
        with pytest.raises(PortReleaseError) as failure:
            verify_port_release(
                game,
                admin,
                owned_pgid=os.getpgrp(),
                timeout_seconds=0.03,
                process_checks_passed=True,
            )
    item = failure.value.evidence[-1]
    assert (item.role, item.protocol, item.port) == (role, "tcp", port)
    assert item.bind_address == "127.0.0.1" and item.address_family == "AF_INET"
    assert item.bind_errno == errno.EADDRINUSE
    assert item.state == "owned_listener" and os.getpid() in item.owner_pids
    assert item.socket_inodes
    assert item.process_checks_passed


def test_failed_probe_closes_its_socket_and_requires_process_checks() -> None:
    game, admin = _free_ports()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", admin))
        listener.listen()
        before = len(list(os.scandir("/proc/self/fd")))
        for _ in range(3):
            with pytest.raises(PortReleaseError):
                verify_port_release(
                    game,
                    admin,
                    owned_pgid=os.getpgrp(),
                    timeout_seconds=0.01,
                    process_checks_passed=True,
                )
        assert len(list(os.scandir("/proc/self/fd"))) == before
    with pytest.raises(ValueError, match="process ownership checks"):
        verify_port_release(game, admin, owned_pgid=os.getpgrp(), process_checks_passed=False)


def test_game_udp_listener_is_checked_independently() -> None:
    game, admin = _free_ports()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as listener:
        listener.bind(("127.0.0.1", game))
        with pytest.raises(PortReleaseError) as failure:
            verify_port_release(
                game,
                admin,
                owned_pgid=os.getpgrp(),
                timeout_seconds=0.03,
                process_checks_passed=True,
            )
    assert (failure.value.evidence[-1].role, failure.value.evidence[-1].protocol) == ("game", "udp")


def test_listener_close_is_observed_with_one_bounded_deadline() -> None:
    game, admin = _free_ports()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", admin))
    listener.listen()
    inspected = threading.Event()
    original = __import__("port_release_probe")._inspect

    def inspect(*args):
        result = original(*args)
        if result.role == "admin" and result.state == "owned_listener":
            inspected.set()
        return result

    from unittest.mock import patch

    def close_after_detection() -> None:
        assert inspected.wait(1)
        listener.close()

    closer = threading.Thread(target=close_after_detection)
    closer.start()
    try:
        with patch("port_release_probe._inspect", side_effect=inspect):
            evidence = verify_port_release(
                game,
                admin,
                owned_pgid=os.getpgrp(),
                timeout_seconds=1,
                process_checks_passed=True,
            )
    finally:
        listener.close()
        closer.join(1)
    assert inspected.is_set()
    assert evidence[-1].role == "admin" and evidence[-1].state == "released"


def test_closed_tcp_listener_with_time_wait_is_not_an_owned_listener() -> None:
    game, admin = _free_ports()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", admin))
        listener.listen()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.connect(("127.0.0.1", admin))
            accepted, _ = listener.accept()
            accepted.shutdown(socket.SHUT_WR)
            client.recv(1)
            accepted.close()
    evidence = verify_port_release(game, admin, owned_pgid=os.getpgrp(), process_checks_passed=True)
    assert evidence[-1].state == "bind_blocked_without_listener"
    assert evidence[-1].bind_errno == errno.EADDRINUSE
    assert "TIME_WAIT" in evidence[-1].tcp_states
    assert evidence[-1].owner_pids == ()


def test_unrelated_process_rebind_is_reported_without_claiming_owned_leak() -> None:
    game, admin = _free_ports()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as previous_owner:
        previous_owner.bind(("127.0.0.1", admin))
        previous_owner.listen()
    script = (
        "import os,socket,sys; os.setsid(); s=socket.socket(); "
        "s.bind(('127.0.0.1',int(sys.argv[1]))); s.listen(); "
        "print('ready',flush=True); sys.stdin.readline()"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(admin)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        readable, _, _ = select.select([child.stdout], [], [], 2)
        assert readable and child.stdout.readline().strip() == "ready"
        evidence = verify_port_release(
            game, admin, owned_pgid=os.getpgrp(), process_checks_passed=True
        )
        assert evidence[-1].state == "unrelated_reuse"
        assert evidence[-1].socket_inodes
        assert child.pid in evidence[-1].owner_pids
        assert os.getpgrp() not in evidence[-1].owner_groups
    finally:
        assert child.stdin is not None
        child.stdin.close()
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            child.terminate()
            child.wait(timeout=2)


def test_rebind_between_socket_snapshot_and_bind_is_resampled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshots = iter((set(), {"123"}))
    monkeypatch.setattr(port_release_probe, "_bound_inodes", lambda _endpoint: next(snapshots))
    monkeypatch.setattr(port_release_probe, "_bind_errno", lambda _endpoint: errno.EADDRINUSE)
    monkeypatch.setattr(port_release_probe, "_owners", lambda _inodes: ((54321,), (54321,)))
    monkeypatch.setattr(port_release_probe, "_tcp_states", lambda _endpoint: ("LISTEN",))
    item = port_release_probe._inspect(
        port_release_probe.Endpoint("admin", "tcp", 39999), os.getpgrp(), 0.0, True
    )
    assert item.state == "unrelated_reuse"
    assert item.owner_pids == (54321,)


def test_dual_stack_wildcard_listener_is_not_mistaken_for_time_wait() -> None:
    game, admin = _free_ports()
    listener: socket.socket | None = None
    try:
        listener = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        listener.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        listener.bind(("::", admin))
    except OSError:
        if listener is not None:
            listener.close()
        pytest.skip("dual-stack wildcard binding is unavailable")
    assert listener is not None
    with listener:
        listener.listen()
        with pytest.raises(PortReleaseError) as failure:
            verify_port_release(
                game,
                admin,
                owned_pgid=os.getpgrp(),
                timeout_seconds=0.03,
                process_checks_passed=True,
            )
    assert failure.value.evidence[-1].state == "owned_listener"
    assert "LISTEN" in failure.value.evidence[-1].tcp_states
