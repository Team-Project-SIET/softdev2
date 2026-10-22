"""Controlled local attended lifecycle; no real approvals, processes or connections."""

import asyncio
import inspect
import json
from dataclasses import replace
from io import StringIO
from pathlib import Path

import pytest

from app.simulation.openttd.proof import terrain_preparation as prep
from app.simulation.openttd.proof.terrain_attempt import (
    execute_single_page,
    validate_final_prelaunch,
)
from app.simulation.openttd.proof.terrain_authorization import (
    LOCAL_POLICY,
    FailureCode,
    LocalProofFailure,
    LocalTrust,
)
from app.simulation.openttd.proof.terrain_native import SinglePageNativeBackend
from app.simulation.openttd.proof.terrain_operator import controlled_confirmation
from app.simulation.openttd.proof.terrain_seal import consume_authorized_attempt, seal_candidate
from tests.test_terrain_single_page_preparation import FakeBackend
from tests.test_terrain_single_page_preparation import candidate as candidate  # noqa: F401


@pytest.fixture
def local_seal(candidate, tmp_path, monkeypatch):
    from app.simulation.openttd.proof import terrain_attempt as attempt

    monkeypatch.setattr(attempt, "PROJECT", prep.PROJECT)
    monkeypatch.setattr(attempt, "source_freeze", prep.source_freeze)
    return seal_candidate(
        candidate,
        tmp_path / "local-sealed",
        tmp_path / "local-attempt",
        authorization_policy=LOCAL_POLICY,
    )


class Terminal(StringIO):
    def __init__(self, answer, tty=True):
        super().__init__()
        self.answer = answer
        self.tty = tty

    def isatty(self):
        return self.tty

    def readline(self, size=-1):
        return self.answer


def expected_confirmation(p):
    row = json.loads((p.directory / "PRELAUNCH.json").read_text())
    digest = prep.sha256(p.directory / "PRELAUNCH.json")
    return f"CONFIRM {digest} {row['attempt_identity']} {row['attempt_directory']}\n"


def authorize(p):
    return controlled_confirmation(p, Terminal(expected_confirmation(p)))


def destination(p):
    return Path(json.loads((p.directory / "PRELAUNCH.json").read_text())["attempt_directory"])


class LocalFakeBackend(FakeBackend):
    def __init__(self, *, failure=None, before_popen=None):
        super().__init__()
        self.failure = failure
        self.before_popen = before_popen
        self.authorization = self.claim = None
        self.fake_popen_calls = 0

    def bind_authorization(self, authorization, claim):
        authorization.require_process(native=False)
        self.authorization, self.claim = authorization, claim

    async def launch(self, prepared):
        p = prepared
        if self.before_popen:
            self.before_popen()
        try:
            validate_final_prelaunch(
                p, destination(p), native=False, authorization=self.authorization, claim=self.claim
            )
        except ValueError as error:
            raise LocalProofFailure(FailureCode.SOURCE_INTEGRITY_FAILED, str(error)) from error
        self.fake_popen_calls += 1  # A fake process-creation seam, never subprocess.Popen.
        if self.failure == "popen":
            raise LocalProofFailure(FailureCode.LAUNCH_FAILED, "controlled fake Popen failure")
        await super().launch(p)

    async def cleanup(self, prepared):
        p = prepared
        value = await super().cleanup(p)
        value["reaped"] = p.spec.lifecycle.process is None or self.child.reaped
        return value


def test_full_local_fake_execution_and_replay(local_seal, monkeypatch):
    from app.simulation.openttd.proof import endpoints

    monkeypatch.setattr(endpoints, "kernel_socket_rows", lambda: [])
    a = authorize(local_seal)
    backend = LocalFakeBackend()
    before = (local_seal.directory / "PRELAUNCH.json").read_bytes()
    result = asyncio.run(
        execute_single_page(local_seal, backend, destination(local_seal), authorization=a)
    )
    assert result["status"] == "CONTROLLED_PASS"
    assert backend.authorization is a and backend.claim is not None
    assert backend.fake_popen_calls == 1
    assert (backend.launches, backend.connections, backend.requests) == (1, 1, 1)
    assert result["gates"]["cleanup"] and result["gates"]["post_run_integrity"]
    assert (local_seal.directory / "PRELAUNCH.json").read_bytes() == before
    assert (destination(local_seal) / "authorization-consumed.json").exists()
    with pytest.raises(ValueError):
        asyncio.run(
            execute_single_page(
                local_seal, LocalFakeBackend(), destination(local_seal), authorization=a
            )
        )


@pytest.mark.parametrize(
    "change", ["yes", "empty", "digest", "attempt", "destination", "force", "noninteractive"]
)
def test_confirmation_rejects_without_consumption(local_seal, change):
    answer = expected_confirmation(local_seal)
    if change == "digest":
        answer = answer.replace(prep.sha256(local_seal.directory / "PRELAUNCH.json"), "0" * 64)
    elif change == "attempt":
        answer = answer.replace("terrain-single-page-", "other-")
    elif change == "destination":
        answer = answer.replace(str(destination(local_seal)), "/wrong")
    elif change == "empty":
        answer = "\n"
    elif change in ("yes", "force"):
        answer = change + "\n"
    with pytest.raises(LocalProofFailure):
        controlled_confirmation(local_seal, Terminal(answer, tty=change != "noninteractive"))
    assert not destination(local_seal).exists()


def test_operator_display_scope_and_trust(local_seal):
    terminal = Terminal(expected_confirmation(local_seal))
    a = controlled_confirmation(local_seal, terminal)
    assert a.trust == LocalTrust.CONTROLLED_OPERATOR_ATTESTED
    text = terminal.getvalue()
    for word in (
        "15.3",
        "tile_facts_page",
        "Maximum launches: 1",
        "Source integrity: PASS",
        str(destination(local_seal)),
        "no independent authentication",
        "65",
    ):
        assert word in text
    assert not destination(local_seal).exists()


def test_exact_owner_can_continue_foreign_owner_cannot(local_seal):
    a = authorize(local_seal)
    claim = consume_authorized_attempt(local_seal.directory, destination(local_seal), a)
    assert validate_final_prelaunch(
        local_seal, destination(local_seal), native=False, authorization=a, claim=claim
    )
    for wrong in (
        replace(a, owner_nonce="other"),
        replace(a, owner_pid=999999),
        replace(a, owner_start="other"),
    ):
        with pytest.raises(LocalProofFailure):
            validate_final_prelaunch(
                local_seal, destination(local_seal), native=False, authorization=wrong, claim=claim
            )
    with pytest.raises(LocalProofFailure):
        validate_final_prelaunch(local_seal, destination(local_seal), native=False, authorization=a)


@pytest.mark.parametrize(
    "field,value",
    [
        ("seal_sha256", "0" * 64),
        ("attempt_identity", "other"),
        ("attempt_directory", "/wrong"),
        ("proof_operation", "wrong"),
        ("launch_allowance", 2),
        ("_grant", None),
        ("trust", LocalTrust.LOCAL_OPERATOR_ATTESTED),
    ],
)
def test_local_binding_invalid(local_seal, field, value):
    a = replace(authorize(local_seal), **{field: value})
    with pytest.raises(LocalProofFailure):
        validate_final_prelaunch(local_seal, destination(local_seal), native=False, authorization=a)
    assert not destination(local_seal).exists()


def test_controlled_grant_cannot_reach_real_backend(local_seal, monkeypatch):
    import subprocess

    from app.simulation.openttd.proof.terrain_attempt import authorized_native_run

    def forbidden(*args, **kwargs):
        raise AssertionError("Real Popen forbidden")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    a = authorize(local_seal)
    with pytest.raises(LocalProofFailure):
        asyncio.run(authorized_native_run(local_seal, destination(local_seal), authorization=a))
    backend = SinglePageNativeBackend(authorized_one_launch=True)
    with pytest.raises(LocalProofFailure):
        backend.bind_authorization(a, object())
    assert backend.launches == 0 and not destination(local_seal).exists()


def test_failed_fake_popen_retains_claim(local_seal, monkeypatch):
    from app.simulation.openttd.proof import endpoints

    monkeypatch.setattr(endpoints, "kernel_socket_rows", lambda: [])
    a = authorize(local_seal)
    b = LocalFakeBackend(failure="popen")
    result = asyncio.run(
        execute_single_page(local_seal, b, destination(local_seal), authorization=a)
    )
    assert result["status"] == "CONTROLLED_FAILED"
    assert result["failure_code"] == "LAUNCH_FAILED" and result["launches"] == 0
    assert b.fake_popen_calls == 1
    assert (destination(local_seal) / "authorization-consumed.json").exists()
    assert (destination(local_seal) / "result.json").exists()
    with pytest.raises(ValueError):
        asyncio.run(
            execute_single_page(
                local_seal, LocalFakeBackend(), destination(local_seal), authorization=a
            )
        )


def test_source_changed_immediately_before_fake_popen(local_seal, monkeypatch):
    from app.simulation.openttd.proof import endpoints

    monkeypatch.setattr(endpoints, "kernel_socket_rows", lambda: [])
    a = authorize(local_seal)
    b = LocalFakeBackend(
        before_popen=lambda: Path(next(iter(prep.source_freeze()))).write_bytes(b"mutated")
    )
    result = asyncio.run(
        execute_single_page(local_seal, b, destination(local_seal), authorization=a)
    )
    assert result["status"] == "CONTROLLED_FAILED" and b.fake_popen_calls == 0
    assert (destination(local_seal) / "result.json").exists()


def test_authorization_propagation_contract():
    assert "authorization" in inspect.signature(execute_single_page).parameters
    assert hasattr(SinglePageNativeBackend, "bind_authorization")


def test_concurrent_claim_is_durable(local_seal):
    from concurrent.futures import ThreadPoolExecutor

    a = authorize(local_seal)

    def acquire():
        try:
            return consume_authorized_attempt(local_seal.directory, destination(local_seal), a)
        except LocalProofFailure:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        winners = list(pool.map(lambda _: acquire(), range(2)))
    assert sum(w is not None for w in winners) == 1
    assert (destination(local_seal) / "authorization-consumed.json").exists()
    with pytest.raises(LocalProofFailure):
        acquire_again = consume_authorized_attempt(local_seal.directory, destination(local_seal), a)
        assert acquire_again is None


def test_arbitrary_destination_rejected(local_seal):
    a = authorize(local_seal)
    destination(local_seal).mkdir()
    (destination(local_seal) / "foreign").write_text("occupied")
    with pytest.raises(LocalProofFailure):
        consume_authorized_attempt(local_seal.directory, destination(local_seal), a)


def test_decline_does_not_consume(local_seal):
    with pytest.raises(LocalProofFailure):
        controlled_confirmation(local_seal, Terminal("yes\n"))
    assert not destination(local_seal).exists()


def test_fabricated_local_grant_rejected(local_seal):
    a = replace(authorize(local_seal), _grant=None)
    with pytest.raises(LocalProofFailure):
        consume_authorized_attempt(local_seal.directory, destination(local_seal), a)
    assert not destination(local_seal).exists()


def test_missing_local_authorization_rejected(local_seal):
    with pytest.raises(LocalProofFailure) as error:
        validate_final_prelaunch(local_seal, destination(local_seal), native=False)
    assert error.value.code == FailureCode.AUTHORIZATION_INVALID
    assert not destination(local_seal).exists()


def test_changed_source_before_claim_does_not_consume(local_seal):
    a = authorize(local_seal)
    Path(next(iter(prep.source_freeze()))).write_bytes(b"changed")
    with pytest.raises(LocalProofFailure) as error:
        validate_final_prelaunch(local_seal, destination(local_seal), native=False, authorization=a)
    assert error.value.code == FailureCode.SOURCE_INTEGRITY_FAILED
    assert not destination(local_seal).exists()


def test_real_backend_preflight_uses_terrain_assets_without_launch(local_seal, monkeypatch):
    from app.simulation.openttd.proof import native

    monkeypatch.setattr(native, "matching_processes", lambda _: [])
    assert not (local_seal.directory / "graphics-identity.json").exists()
    b = SinglePageNativeBackend(authorized_one_launch=True)
    b.preflight(local_seal)
    assert b.launches == b.connections == b.requests == 0
    assert b.authorization is None and b.claim is None
    assert not destination(local_seal).exists()


def test_candidate_explicit_model_a_policy(candidate, tmp_path):
    fresh = prep.prepare_candidate(tmp_path / "explicit-policy", authorization_policy=LOCAL_POLICY)
    assert fresh.record["authorization_policy"] == LOCAL_POLICY
    assert fresh.record["authorization_state"] == "UNAUTHORIZED"
    assert fresh.record["maximum_launches"] == 1
    assert fresh.preflight()["authorized"] is False
    with pytest.raises(PermissionError):
        seal_candidate(fresh, tmp_path / "wrong-policy-seal", tmp_path / "wrong-policy-attempt")


def test_terrain_inventory_includes_transitive_shared_dtos():
    inventory = prep.source_freeze()
    for name in ("__init__.py", "domain.py", "canonical.py"):
        path = (prep.PROJECT / "app/planning" / name).resolve()
        assert inventory[str(path)] == prep.sha256(path)


@pytest.fixture
def direct_pty(monkeypatch):
    """Map only /dev/tty to an isolated PTY; never invoke main or a backend."""
    import os
    import pty

    from app.simulation.openttd.proof import terrain_operator as operator

    master, slave = pty.openpty()
    terminal_path = Path(os.ttyname(slave))
    opened = []
    original_open = Path.open
    original_confirmation = operator._confirmation

    def open_terminal(path, *args, **kwargs):
        if path == Path("/dev/tty"):
            stream = open(
                terminal_path,
                *args,
                **kwargs,
                opener=lambda path, flags: os.open(path, flags | os.O_NOCTTY),
            )
            opened.append(stream)
            return stream
        return original_open(path, *args, **kwargs)

    def controlled_only(prepared, terminal, **kwargs):
        return original_confirmation(prepared, terminal, **{**kwargs, "controlled": True})

    monkeypatch.setattr(Path, "open", open_terminal)
    monkeypatch.setattr(operator, "_confirmation", controlled_only)
    monkeypatch.setattr(operator.sys, "stdin", Terminal(""))
    monkeypatch.setattr(operator.sys, "stdout", Terminal(""))
    try:
        yield master, terminal_path, opened
    finally:
        os.close(master)
        os.close(slave)
        assert all(stream.closed for stream in opened)


def test_legacy_update_stream_reproduces_nonseekable(direct_pty):
    import io
    import os

    _, path, _ = direct_pty
    with pytest.raises(io.UnsupportedOperation, match="not seekable"):
        open(path, "r+", buffering=1, opener=lambda path, flags: os.open(path, flags | os.O_NOCTTY))


@pytest.mark.parametrize("answer", ["exact", "wrong", "eof"])
def test_direct_tty_confirmation(local_seal, direct_pty, monkeypatch, answer):
    import os
    import select
    import sys

    from app.simulation.openttd.proof.terrain_operator import attended_confirmation

    monkeypatch.setattr(sys, "stdout", Terminal(""))
    master, _, opened = direct_pty
    text = expected_confirmation(local_seal) if answer == "exact" else "wrong\n"
    os.write(master, b"\x04" if answer == "eof" else text.encode())
    if answer == "exact":
        authorization = attended_confirmation(local_seal)
        assert authorization.trust == LocalTrust.CONTROLLED_OPERATOR_ATTESTED
        assert authorization.seal_sha256 == prep.sha256(local_seal.directory / "PRELAUNCH.json")
        assert authorization.attempt_identity in text
        assert authorization.attempt_directory == str(destination(local_seal))
    else:
        with pytest.raises(LocalProofFailure) as error:
            attended_confirmation(local_seal)
        assert error.value.code == FailureCode.OPERATOR_CONFIRMATION_DECLINED
    assert not destination(local_seal).exists()
    assert all(stream.closed for stream in opened)
    assert select.select([master], [], [], 1)[0]
    display = os.read(master, 16384).decode()
    assert f"Type exactly: {expected_confirmation(local_seal).rstrip()}" in display


@pytest.mark.parametrize("failure", ["missing", "second_open", "input", "noninteractive"])
def test_direct_tty_failure_cleanup(local_seal, direct_pty, monkeypatch, failure):
    from app.simulation.openttd.proof import terrain_operator as operator

    monkeypatch.setattr(operator.sys, "stdout", Terminal(""))
    _, _, opened = direct_pty
    previous_open = Path.open

    def failing_open(path, *args, **kwargs):
        if path == Path("/dev/tty"):
            if failure == "missing" or (failure == "second_open" and opened):
                raise OSError("Controlled unavailable terminal")
            stream = previous_open(path, *args, **kwargs)
            if failure == "input" and args[0] == "r":

                def fail_read(size=-1):
                    raise OSError("Controlled read failure")

                monkeypatch.setattr(stream, "readline", fail_read)
            return stream
        return previous_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing_open)
    if failure == "noninteractive":
        monkeypatch.setattr(operator.sys, "stdin", Terminal("", tty=False))
    with pytest.raises(LocalProofFailure):
        operator.attended_confirmation(local_seal)
    assert not destination(local_seal).exists()
    assert all(stream.closed for stream in opened)
    if failure == "noninteractive":
        assert not opened


@pytest.mark.parametrize("stream_index", [0, 1])
def test_direct_stream_must_be_tty(local_seal, direct_pty, monkeypatch, stream_index):
    from app.simulation.openttd.proof import terrain_operator as operator

    monkeypatch.setattr(operator.sys, "stdout", Terminal(""))
    _, _, opened = direct_pty
    previous_open = Path.open

    def non_tty_open(path, *args, **kwargs):
        stream = previous_open(path, *args, **kwargs)
        if path == Path("/dev/tty") and len(opened) - 1 == stream_index:
            monkeypatch.setattr(stream, "isatty", lambda: False)
        return stream

    monkeypatch.setattr(Path, "open", non_tty_open)
    with pytest.raises(LocalProofFailure) as error:
        operator.attended_confirmation(local_seal)
    assert error.value.code == FailureCode.AUTHORIZATION_INVALID
    assert all(stream.closed for stream in opened)
    assert not destination(local_seal).exists()


def test_direct_source_failure_keeps_failure_code(local_seal, direct_pty, monkeypatch):
    from app.simulation.openttd.proof import terrain_attempt as attempt
    from app.simulation.openttd.proof import terrain_operator as operator

    monkeypatch.setattr(operator.sys, "stdout", Terminal(""))

    def stale_seal(*args):
        raise ValueError("Controlled stale source")

    monkeypatch.setattr(attempt, "validate_immutable_seal", stale_seal)
    with pytest.raises(LocalProofFailure) as error:
        operator.attended_confirmation(local_seal)
    assert error.value.code == FailureCode.SOURCE_INTEGRITY_FAILED
    assert all(stream.closed for stream in direct_pty[2])
    assert not destination(local_seal).exists()
