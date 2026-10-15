"""Plain Linux sockets only: never OpenTTD or a real Admin endpoint."""

import errno
import json
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.simulation.openttd.proof.harness import EndpointReservation


def prepared(tmp_path, ports):
    (tmp_path / "PRELAUNCH.json").write_text(
        json.dumps(dict(game_port=ports[0], admin_port=ports[1]))
    )
    return SimpleNamespace(directory=tmp_path, endpoints=ports)


def cleanup():
    return dict(reaped=True, remaining_processes=[], cleanup_error=[])


def pair(host="127.0.0.1", reuse=False):
    listener = socket.socket()
    listener.settimeout(2)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, int(reuse))
    listener.bind((host, 0))
    listener.listen()
    client = socket.socket()
    client.settimeout(2)
    client.connect(("127.0.0.1", listener.getsockname()[1]))
    server, _ = listener.accept()
    server.settimeout(2)
    return listener, client, server


def close_pair(listener, client, server, server_first=True):
    active, passive = (server, client) if server_first else (client, server)
    active.shutdown(socket.SHUT_WR)
    assert passive.recv(1) == b""
    passive.close()
    assert active.recv(1) == b""
    active.close()
    listener.close()


def test_closed_listener_time_wait_not_listen(tmp_path):
    from app.simulation.openttd.proof.endpoints import verify_cleanup_endpoints

    listener, client, server = pair()
    port = listener.getsockname()[1]
    other = EndpointReservation.allocate()
    game = other.game_port
    other.close()
    close_pair(listener, client, server)
    with pytest.raises(OSError) as error:
        EndpointReservation.allocate(game, port)
    assert error.value.errno == errno.EADDRINUSE
    result = verify_cleanup_endpoints(prepared(tmp_path, (game, port)), cleanup(), other)
    assert result["sockets_closed"]
    assert any(r["state"] == "TIME_WAIT" for r in result["endpoint_verification"]["kernel_states"])


@pytest.mark.parametrize("host", ["127.0.0.1", "0.0.0.0"])
def test_listener_without_accept_closes_rebinds(tmp_path, host):
    from app.simulation.openttd.proof.endpoints import verify_cleanup_endpoints

    held = EndpointReservation.allocate()
    ports = (held.game_port, held.admin_port)
    held.close()
    with socket.socket() as listener:
        listener.bind((host, ports[1]))
        listener.listen()
    rebound = EndpointReservation.allocate(*ports)
    rebound.close()
    assert verify_cleanup_endpoints(prepared(tmp_path, ports), cleanup(), held)["sockets_closed"]


@pytest.mark.parametrize("server_first", [False, True])
@pytest.mark.parametrize("reuse", [False, True])
def test_active_passive_close_and_reuse(tmp_path, server_first, reuse):
    from app.simulation.openttd.proof.endpoints import verify_cleanup_endpoints

    listener, client, server = pair(reuse=reuse)
    port = listener.getsockname()[1]
    held = EndpointReservation.allocate()
    game = held.game_port
    held.close()
    close_pair(listener, client, server, server_first)
    with socket.socket() as rebound:
        rebound.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if server_first and not reuse:
            with pytest.raises(OSError) as e:
                rebound.bind(("127.0.0.1", port))
            assert e.value.errno == errno.EADDRINUSE
        else:
            rebound.bind(("127.0.0.1", port))
    assert verify_cleanup_endpoints(prepared(tmp_path, (game, port)), cleanup(), held)[
        "sockets_closed"
    ]


@pytest.mark.parametrize("host", ["127.0.0.1", "0.0.0.0"])
def test_surviving_listener_fails(tmp_path, host):
    from app.simulation.openttd.proof.endpoints import verify_cleanup_endpoints

    with socket.socket() as listener:
        listener.bind((host, 0))
        listener.listen()
        port = listener.getsockname()[1]
        with pytest.raises(ValueError, match="Live"):
            verify_cleanup_endpoints(prepared(tmp_path, (port, port + 1)), cleanup())


def test_listener_closed_connection_survives_rejected(tmp_path):
    from app.simulation.openttd.proof.endpoints import verify_cleanup_endpoints

    listener, client, server = pair(reuse=True)
    port = listener.getsockname()[1]
    listener.close()
    try:
        with socket.socket() as rebound:
            rebound.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            rebound.bind(("127.0.0.1", port))  # Rebind success does not prove connection closure.
        with pytest.raises(ValueError, match="Live"):
            verify_cleanup_endpoints(prepared(tmp_path, (port, port + 1)), cleanup())
    finally:
        client.close()
        server.close()


def test_connection_probe_semantics_plain_peer():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    address = listener.getsockname()
    with socket.socket() as probe:
        probe.settimeout(1)
        probe.connect(address)  # Successful connection: an actual listener exists.
        accepted, _ = listener.accept()
        accepted.close()
    listener.close()
    with socket.socket() as probe:
        probe.settimeout(1)
        assert probe.connect_ex(address) == errno.ECONNREFUSED
    # Production uses structured kernel tables, never a connect probe or timeout inference.


@pytest.mark.parametrize("v6only", [0, 1])
def test_ipv6_wildcard_ambiguity_rejected(tmp_path, v6only):
    from app.simulation.openttd.proof.endpoints import verify_cleanup_endpoints

    with socket.socket(socket.AF_INET6) as listener:
        listener.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, v6only)
        listener.bind(("::", 0))
        listener.listen()
        port = listener.getsockname()[1]
        with pytest.raises(ValueError, match="Live"):
            verify_cleanup_endpoints(prepared(tmp_path, (port, port + 1)), cleanup())


def test_ipv6_loopback_is_distinct(tmp_path):
    from app.simulation.openttd.proof.endpoints import verify_cleanup_endpoints

    with socket.socket(socket.AF_INET6) as listener:
        listener.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        listener.bind(("::1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        assert verify_cleanup_endpoints(prepared(tmp_path, (port, port + 1)), cleanup())[
            "sockets_closed"
        ]
        with pytest.raises(ValueError, match="family"):
            verify_cleanup_endpoints(
                prepared(tmp_path, (port, port + 1)), cleanup(), family=socket.AF_INET6
            )


def test_reservation_release_and_stale_detected(tmp_path):
    from app.simulation.openttd.proof.endpoints import verify_cleanup_endpoints

    held = EndpointReservation.allocate()
    ports = (held.game_port, held.admin_port)
    p = prepared(tmp_path, ports)
    try:
        with pytest.raises(ValueError, match="reservation"):
            verify_cleanup_endpoints(p, cleanup(), held)
        with pytest.raises(ValueError, match="Live"):
            verify_cleanup_endpoints(p, cleanup())  # UDP bound reservation is visible.
    finally:
        held.close()
    assert held.sockets == []
    assert verify_cleanup_endpoints(p, cleanup(), held)["sockets_closed"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("reaped", False),
        ("reaped", None),
        ("remaining_processes", [123]),
        ("remaining_processes", None),
        ("cleanup_error", ["ambiguous"]),
    ],
)
def test_process_ownership_required(tmp_path, field, value):
    from app.simulation.openttd.proof.endpoints import verify_cleanup_endpoints

    state = cleanup()
    state[field] = value
    with pytest.raises(ValueError, match="reap"):
        verify_cleanup_endpoints(prepared(tmp_path, (41001, 41002)), state)


def test_endpoint_identity_mismatch(tmp_path):
    from app.simulation.openttd.proof.endpoints import verify_cleanup_endpoints

    p = prepared(tmp_path, (41001, 41002))
    p.endpoints = (41003, 41004)
    with pytest.raises(ValueError, match="identity"):
        verify_cleanup_endpoints(p, cleanup())


@pytest.mark.parametrize(
    "error", [TimeoutError("ambiguous"), PermissionError("kernel unavailable")]
)
def test_kernel_inspection_ambiguity_fails(tmp_path, monkeypatch, error):
    from app.simulation.openttd.proof import endpoints

    def unavailable():
        raise error

    monkeypatch.setattr(endpoints, "kernel_socket_rows", unavailable)
    with pytest.raises(type(error)):
        endpoints.verify_cleanup_endpoints(prepared(tmp_path, (41001, 41002)), cleanup())


def test_kernel_listen_state_and_ipv4_mapped_rejected(tmp_path, monkeypatch):
    from app.simulation.openttd.proof import endpoints

    monkeypatch.setattr(
        endpoints,
        "kernel_socket_rows",
        lambda: [
            dict(
                table="tcp6",
                local="::ffff:127.0.0.1",
                local_port=41001,
                remote="::",
                remote_port=0,
                state=10,
                inode=3,
            )
        ],
    )
    with pytest.raises(ValueError, match="Live"):
        endpoints.verify_cleanup_endpoints(prepared(tmp_path, (41001, 41002)), cleanup())


def test_no_connect_bind_sleep_or_native_retry(monkeypatch, tmp_path):
    import time

    from app.simulation.openttd.proof import endpoints

    monkeypatch.setattr(endpoints, "kernel_socket_rows", lambda: [])
    monkeypatch.setattr(socket, "socket", lambda *a, **k: pytest.fail("verification socket"))
    monkeypatch.setattr(time, "sleep", lambda *a: pytest.fail("arbitrary sleep"))
    assert endpoints.verify_cleanup_endpoints(prepared(tmp_path, (41001, 41002)), cleanup())[
        "sockets_closed"
    ]


def test_retained_attempt3_is_failed_not_reclassified():
    from app.simulation.openttd.proof.qualification_lineage import validate_historical_attempt

    root = Path(__file__).resolve().parents[1]
    freeze = root / "artifacts/runtime/openttd-15.3-two-rollover-qualification-real-prelaunch-v4"
    m = json.loads((freeze / "PRELAUNCH.json").read_text())
    dest = Path(m["attempt_directory"])
    identity = validate_historical_attempt(freeze, dest)
    evidence = json.loads((dest / "proof-evidence.json").read_text())
    session = json.loads((dest / "qualification-session.json").read_text())
    assert identity.terminal_status == "REAL_FAILED"
    assert identity.launches == identity.connections == 1
    assert evidence["qualified_for_planning"] is False
    assert session["semantic_evidence"]["phase"] == "COMPLETED"
    assert session["semantic_evidence"]["failure"] is None
    assert "QUALIFIED_OBSERVATION_ASSEMBLED" in evidence["states"]
    assert "Address already in use" in evidence["error"]


def test_protected_history_and_context_exact():
    from app.simulation.openttd.proof.historical_protection import validate_protection

    root = Path(__file__).resolve().parents[1]
    freeze = root / "artifacts/runtime/openttd-15.3-two-rollover-qualification-real-prelaunch-v4"
    assert (
        validate_protection(root, json.loads((freeze / "historical-integrity.json").read_text()))
        == 1627
    )


def test_shared_lifecycles_use_semantic_verifier():
    import ast

    root = Path(__file__).resolve().parents[1] / "app/simulation/openttd/proof"
    for name in (
        "attempt",
        "world_attempt",
        "industry_attempt",
        "inventory_attempt",
        "cargo_attempt",
        "enrichment_attempt",
        "cargo_page_attempt",
        "catalog_attempt",
        "structural_attempt",
        "production_attempt",
        "raw_production_attempt",
    ):
        tree = ast.parse((root / (name + ".py")).read_text())
        assert any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "verify_cleanup_endpoints"
            for n in ast.walk(tree)
        ), name


def test_kernel_parser_fail_closed(monkeypatch):
    from app.simulation.openttd.proof.endpoints import kernel_socket_rows

    monkeypatch.setattr(Path, "read_text", lambda *a, **k: "untrusted malformed table")
    with pytest.raises(ValueError, match="header"):
        kernel_socket_rows()


def test_other_process_listener_rejected(tmp_path):
    import subprocess
    import sys

    from app.simulation.openttd.proof.endpoints import verify_cleanup_endpoints

    code = (
        "import socket,sys;s=socket.socket();s.bind(('127.0.0.1',0));s.listen();"
        "print(s.getsockname()[1],flush=True);sys.stdin.read();s.close()"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
    )
    try:
        assert child.stdout is not None
        port = int(child.stdout.readline())
        with pytest.raises(ValueError, match="Live"):
            verify_cleanup_endpoints(prepared(tmp_path, (port, port + 1)), cleanup())
    finally:
        child.communicate("", timeout=2)
    assert child.returncode == 0
