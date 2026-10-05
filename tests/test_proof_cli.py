"""Black-box proof CLI contracts: no private helper imports in invocation."""

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]


def test_public_preflight_command_is_supported():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.simulation.openttd.proof",
            "preflight",
            "--directory",
            "/nonexistent-proof",
        ],
        cwd=PROJECT,
        capture_output=True,
        text=True,
    )
    assert "invalid choice" not in result.stderr
    assert result.returncode != 0
    assert "PREFLIGHT_FAILED" in result.stdout


@pytest.mark.parametrize("case", ["ready", "busy", "history_changed", "freeze_changed"])
def test_public_preflight_resolves_contract_and_reserves_endpoints(
    tmp_path, monkeypatch, capsys, case
):
    import json

    from test_real_ack_harness import make_prepared

    from app.simulation.openttd.proof import __main__ as cli

    history = tmp_path / "openttd-15.3-real-ack-attempt1"
    history.mkdir()
    historical_report = history / "final-report.md"
    historical_report.write_text("FAILED historical proof")
    prepared = make_prepared(tmp_path)
    import app.simulation.openttd.proof.native as native

    monkeypatch.setattr(native, "BINARY", prepared.spec.identity.executable)
    monkeypatch.setattr(native, "BINARY_SHA256", prepared.spec.identity.sha256)

    class ControlledPreflightBackend:
        def __init__(self, *, authorized_one_launch):
            assert authorized_one_launch

        def preflight(self, received):
            assert received.spec.workspace.root == prepared.spec.workspace.root
            assert received.key_path == prepared.key_path

    monkeypatch.setattr(cli, "NativeBackend", ControlledPreflightBackend)
    # Avoid permanently installing a process-wide audit hook in pytest; the black-box
    # command test covers actual hook installation. No runner is called here.
    monkeypatch.setattr(sys, "addaudithook", lambda guard: None)
    monkeypatch.setattr(sys, "argv", ["proof", "preflight", "--directory", str(prepared.directory)])
    import socket

    held = None
    if case == "busy":
        held = socket.socket()
        held.bind(("127.0.0.1", prepared.endpoints[0]))
    elif case == "history_changed":
        historical_report.write_text("changed")
    elif case == "freeze_changed":
        prepared.spec.workspace.config.write_text("changed")
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("process forbidden"))
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **kw: pytest.fail("connect forbidden"))
    before = {str(p): p.read_bytes() for p in prepared.directory.rglob("*") if p.is_file()}
    try:
        if case == "ready":
            cli.main()
        else:
            with pytest.raises(SystemExit):
                cli.main()
        result = json.loads(capsys.readouterr().out)
        assert result["state"] == ("READY_TO_LAUNCH" if case == "ready" else "PREFLIGHT_FAILED")
        if case == "ready":
            assert result["endpoints_reserved"] == list(prepared.endpoints)
            assert result["request_id"] == "openttd15-real-ack-002"
        assert result["launches"] == result["connections"] == result["requests"] == 0
        assert {
            str(p): p.read_bytes() for p in prepared.directory.rglob("*") if p.is_file()
        } == before
    finally:
        if held:
            held.close()
        prepared.dispose()
