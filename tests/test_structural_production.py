"""Production structural seams with synthetic encrypted Admin peers only."""

import asyncio

import pytest
from test_secure_admin import KEY, Writer, server_handshake

from app.simulation.openttd.proof.structural_contract import StructuralFrameBudget
from app.simulation.openttd.secure_admin import SecureAdminSession


def test_actual_encrypted_establishment_and_quit_accounted_once():
    async def run():
        reader, writer = asyncio.StreamReader(), Writer()
        accounting = StructuralFrameBudget()
        session = SecureAdminSession(reader, writer, key=KEY, frame_observer=accounting.observe)
        wire, _ = server_handshake()
        reader.feed_data(wire)
        await session.authenticate("proof", "1")
        assert accounting.total_frames == 2
        assert accounting.query_operations == 0
        await session.close(quit=True)
        assert accounting.total_frames == 3
        assert [r["packet_type"] for r in accounting.snapshot()["frames"]] == [103, 104, 1]
        assert writer.closed

    asyncio.run(run())


def make_prepared(tmp_path):
    import hashlib

    from test_real_ack_graphics import graphics_archive

    from app.simulation.openttd.proof.harness import prepare_proof

    binary = tmp_path / "controlled-openttd"
    binary.write_bytes(b"controlled, never executed")
    binary.chmod(0o700)
    graphics = tmp_path / "graphics.zip"
    digest = graphics_archive(graphics)
    return prepare_proof(
        tmp_path / "prelaunch",
        mode="structural-world",
        binary=binary,
        binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        graphics=graphics,
        graphics_sha256=digest,
    )


def test_structural_preparation_freezes_kind_destination_accounting_and_request(tmp_path):
    import json

    from app.simulation.openttd.proof.structural_contract import structural_contract

    prepared = make_prepared(tmp_path)
    try:
        meta = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
        assert meta["proof_kind"] == "structural-world"
        assert meta["attempt_id"] == "structural-world-v1-native-attempt1"
        assert meta["predecessor_attempt_ids"] == []
        assert meta["attempt_directory"] == str(
            tmp_path / "openttd-15.3-structural-world-real-attempt1"
        )
        assert prepared.request.request_id == "openttd15-structural-world-001-inv-p001"
        assert prepared.request.after_id is None and prepared.request.limit == 2
        assert (
            json.loads((prepared.directory / "structural-contract.json").read_text())
            == structural_contract()
        )
        assert prepared.key_path.stat().st_mode & 0o777 == 0o600
        key = prepared.key_path.read_bytes()
        assert all(
            key not in p.read_bytes() and key.hex().encode() not in p.read_bytes()
            for p in prepared.directory.iterdir()
            if p.is_file()
        )
    finally:
        prepared.dispose()


class ControlledEncryptedBackend:
    """Production owner + secure stream; fixture never opens a socket or subprocess."""

    def __new__(cls, *args, **kwargs):
        import json
        import struct

        from test_secure_admin import NONCE, SERVER, STREAM_NONCE
        from test_structural_world import StructuralWire

        from app.simulation.openttd.admin_crypto import AuthorizedKey, PacketCipher, derive_keys
        from app.simulation.openttd.admin_protocol import AdminFrameDecoder, encode_admin_frame
        from app.simulation.openttd.proof.native import NativeBackend
        from app.simulation.openttd.proof.structural_native import StructuralNativeBackend

        class Backend(StructuralNativeBackend):
            kind = "MOCK"

            def __init__(self, industries=(2, 17), cargoes=(1, 9, 63), failure=None):
                super().__init__(authorized_one_launch=True)
                self.peer = StructuralWire(industries=industries, cargoes=cargoes)
                self.failure = failure

            def preflight(self, prepared):
                self._key = AuthorizedKey.from_bytes(prepared.key_path.read_bytes())

            def validate_launch(self, prepared):
                assert (
                    prepared.spec.identity.executable.read_bytes() == b"controlled, never executed"
                )

            async def launch(self, prepared):
                self._prepared = prepared
                import subprocess
                from unittest.mock import Mock

                self.process = Mock(spec=subprocess.Popen)  # controlled identity, never invoked
                prepared.spec.stderr_path.write_text(
                    "dbg: [script:4] [18] [I] BRIDGE_STARTED protocol=1 api=15\n"
                    "Using the OpenGFX base graphics set\n"
                )
                prepared.spec.stdout_path.write_text("")

            def health(self):
                pass

            async def authenticate(self, prepared, gates):
                key = self._key
                assert key is not None
                reader = asyncio.StreamReader()
                outgoing = PacketCipher(
                    derive_keys(key, SERVER.public_key).server_to_client, STREAM_NONCE
                )
                incoming = PacketCipher(
                    derive_keys(key, SERVER.public_key).client_to_server, STREAM_NONCE
                )
                peer = self.peer
                decoder = AdminFrameDecoder()

                class EncryptedWriter(Writer):
                    def __init__(self):
                        super().__init__()
                        self.auth_frames = 0
                        self.pending = False

                    def write(writer, frame):
                        super().write(frame)
                        if writer.auth_frames < 2:
                            writer.auth_frames += 1
                            return
                        clear = incoming.decrypt(frame)
                        peer.writer.write.side_effect(clear)
                        writer.pending |= clear[2] in (6, 7)

                    async def drain(writer):
                        if writer.pending:
                            writer.pending = False
                            raw = await peer.reader.read(65536)
                            for frame in decoder.feed_wire_frames(raw):
                                reader.feed_data(outgoing.encrypt(frame))

                protocol = encode_admin_frame(103, b"\x03\x01" + struct.pack("<HH", 9, 64) + b"\0")
                welcome = encode_admin_frame(
                    104, b"proof\x0015.3\0\x01\0" + struct.pack("<IBIHH", 42, 0, 712223, 64, 64)
                )
                reader.feed_data(
                    encode_admin_frame(128, b"\x02" + SERVER.public_key + NONCE)
                    + encode_admin_frame(129, STREAM_NONCE)
                    + outgoing.encrypt(protocol)
                    + outgoing.encrypt(welcome)
                )
                self.session = SecureAdminSession(
                    reader, EncryptedWriter(), key=key, frame_observer=self.accounting.observe
                )
                self.secure_connection = self.session
                return await NativeBackend.authenticate(self, prepared, gates)

            async def evidence(self, prepared, request, exchange):
                if self.failure == "replacement":
                    self.session = SecureAdminSession(asyncio.StreamReader(), Writer(), key=KEY)
                if (
                    self.failure == "inventory_timeout"
                    and json.loads(request.to_bytes())["type"] == "industry_page"
                ):
                    raise TimeoutError("controlled inventory timeout")
                if (
                    self.failure == "capability_timeout"
                    and json.loads(request.to_bytes())["type"] == "industry_cargo"
                ):
                    raise TimeoutError("controlled capability timeout")
                if (
                    self.failure == "catalog_timeout"
                    and json.loads(request.to_bytes())["type"] == "cargo_page"
                ):
                    raise TimeoutError("controlled catalog timeout")
                if json.loads(request.to_bytes())["type"] == "industry_page":
                    ev = await self.peer.evidence(request, exchange)
                elif json.loads(request.to_bytes())["type"] == "industry_cargo":
                    ev = await self.peer.cargo_evidence(request, exchange)
                else:
                    ev = await self.peer.catalog_evidence(request, exchange)
                with prepared.spec.stderr_path.open("ab") as log:
                    log.write(ev.raw_log)
                return await super().evidence(prepared, request, exchange)

            async def cleanup(self, prepared):
                assert self.secure_connection is not None
                await self.secure_connection.close(quit=True)
                return dict(
                    reaped=True,
                    remaining_processes=[],
                    graceful_attempted=True,
                    returncode=0,
                    cleanup_error=None,
                    admin_frame_accounting=self.accounting.snapshot(),
                )

        return Backend(*args, **kwargs)


def test_owned_structural_runner_collects_all_phases_on_one_encrypted_stream(tmp_path):
    import json

    from app.simulation.openttd.proof.structural_attempt import execute_structural_attempt

    prepared = make_prepared(tmp_path)

    async def run():
        backend = ControlledEncryptedBackend()
        return await execute_structural_attempt(prepared, backend), backend

    result, backend = asyncio.run(run())
    assert result["status"] == "MOCK_SUCCESS", result["error"]
    assert result["requests_sent"] == 5
    assert result["accounting"]["query_operations"] == 20
    assert result["accounting"]["total_post_auth_frames"] == 26
    assert result["retries"] == result["reconnects"] == 0
    assert result["states"][-1] == "COMPLETED"
    assert [q["type"] for q in backend.peer.all_requests] == [
        "industry_page",
        "industry_cargo",
        "industry_cargo",
        "cargo_page",
        "cargo_page",
    ]
    dest = prepared.directory.with_name("openttd-15.3-structural-world-real-attempt1")
    assert json.loads((dest / "structural-observation.json").read_text())["complete"]
    assert not prepared.key_path.exists()


@pytest.mark.parametrize(
    "industries,cargoes", [((), (1, 9)), ((0,), (1, 9)), ((3, 29), (1, 9, 63))]
)
def test_native_owner_supports_empty_and_sparse_worlds(tmp_path, industries, cargoes):
    from app.simulation.openttd.proof.structural_attempt import execute_structural_attempt

    prepared = make_prepared(tmp_path)

    async def run():
        b = ControlledEncryptedBackend(industries, cargoes)
        return await execute_structural_attempt(prepared, b), b

    result, b = asyncio.run(run())
    assert result["status"] == "MOCK_SUCCESS", result["error"]
    assert sum(q["type"] == "industry_cargo" for q in b.peer.all_requests) == len(industries)
    assert any(q["type"] == "cargo_page" for q in b.peer.all_requests)
    assert (
        result["accounting"]["total_post_auth_frames"] - result["accounting"]["query_operations"]
        == 6
    )


@pytest.mark.parametrize(
    "failure", ["inventory_timeout", "capability_timeout", "catalog_timeout", "replacement"]
)
def test_runtime_failures_retain_partial_evidence_and_no_resume(tmp_path, failure):
    import json

    from app.simulation.openttd.proof.structural_attempt import execute_structural_attempt

    prepared = make_prepared(tmp_path)

    async def run():
        b = ControlledEncryptedBackend(failure=failure)
        return await execute_structural_attempt(prepared, b), b

    result, b = asyncio.run(run())
    assert result["status"] == "MOCK_FAILED"
    assert result["states"][-1] == "FAILED"
    assert result["retries"] == result["reconnects"] == 0
    dest = prepared.directory.with_name("openttd-15.3-structural-world-real-attempt1")
    assert not json.loads((dest / "structural-observation.json").read_text())["complete"]
    assert not (dest / "structural-digest.json").exists()
    assert not prepared.key_path.exists()
    assert len(b.peer.all_requests) == len({r["request_id"] for r in b.peer.all_requests})
    if failure == "capability_timeout":
        assert json.loads((dest / "inventory-observation.json").read_text())["complete"]
        assert not any(q["type"] == "cargo_page" for q in b.peer.all_requests)
    if failure == "catalog_timeout":
        assert json.loads((dest / "capability-observation.json").read_text())["complete"]


def test_missing_cargo_fails_world_assembly_without_fabrication(tmp_path):
    from app.simulation.openttd.proof.structural_attempt import execute_structural_attempt

    prepared = make_prepared(tmp_path)

    async def run():
        b = ControlledEncryptedBackend(cargoes=(1, 63))
        return await execute_structural_attempt(prepared, b)

    result = asyncio.run(run())
    assert result["status"] == "MOCK_FAILED" and "cargo" in result["error"].lower()


@pytest.mark.parametrize(
    "direction,kind",
    [("inbound", 124), ("inbound", 126), ("inbound", 111), ("outbound", 6), ("outbound", 7)],
)
def test_every_query_frame_category_consumes_the_same_budget(direction, kind):
    from app.simulation.openttd.admin_protocol import encode_admin_frame

    budget = StructuralFrameBudget()
    budget.enter("setup")
    budget.enter("inventory")
    budget.observe(direction, encode_admin_frame(kind, b""))
    assert budget.query_operations == budget.total_frames == 1


def test_query_overrun_cannot_borrow_lifecycle_allowance():
    from app.simulation.openttd.admin_protocol import encode_admin_frame

    budget = StructuralFrameBudget()
    for phase, count in (("inventory", 256), ("capability", 256), ("catalog", 512)):
        budget.consume(phase, count)
    budget.enter("setup")
    budget.enter("inventory")
    with pytest.raises(ValueError, match="budget"):
        budget.observe("inbound", encode_admin_frame(124, b""))
    assert budget.total_frames == 1024 < 1030
    assert budget.failed and not budget.snapshot()["frames"][-1]["admitted"]
    with pytest.raises(ValueError, match="reset/resume"):
        budget.enter("capability")


def test_excess_overhead_fails_without_using_query_budget():
    from app.simulation.openttd.admin_protocol import encode_admin_frame

    budget = StructuralFrameBudget()
    budget.consume("establishment", 2)
    with pytest.raises(ValueError, match="budget"):
        budget.observe("inbound", encode_admin_frame(104, b""))
    assert budget.query_operations == 0 and budget.failed


def test_phase_transitions_never_reset_frame_counts():
    budget = StructuralFrameBudget()
    budget.consume("establishment", 2)
    for phase, count in (
        ("setup", 3),
        ("inventory", 256),
        ("capability", 256),
        ("catalog", 512),
        ("cleanup", 1),
    ):
        before = budget.total_frames
        budget.enter(phase)
        assert budget.total_frames == before
        budget.consume(phase, count)
    assert budget.query_operations == 1024 and budget.total_frames == 1030


def test_lifecycle_rejects_early_transitions_and_failed_is_terminal():
    from app.simulation.openttd.proof.structural_attempt import (
        StructuralLifecycle,
        StructuralProofState,
    )

    lifecycle = StructuralLifecycle()
    with pytest.raises(ValueError):
        lifecycle.advance(StructuralProofState.INDUSTRY_CAPABILITY_STARTED)
    lifecycle.fail()
    with pytest.raises(ValueError):
        lifecycle.advance(StructuralProofState.LAUNCHED)


def test_full_lifecycle_sequence():
    from app.simulation.openttd.proof.structural_attempt import (
        StructuralLifecycle,
        StructuralProofState,
    )

    lifecycle = StructuralLifecycle()
    for state in list(StructuralProofState)[1:-1]:
        lifecycle.advance(state)
    assert lifecycle.states[-1] is StructuralProofState.COMPLETED


def test_public_guarded_cli_uses_runner_launch_boundary(tmp_path, monkeypatch, capsys):
    import json
    import socket
    import subprocess
    import sys

    from app.simulation.openttd.proof import __main__ as cli
    from app.simulation.openttd.proof import native
    from app.simulation.openttd.proof.structural_native import StructuralNativeBackend

    prepared = make_prepared(tmp_path)
    hooks = []

    class Backend(StructuralNativeBackend):
        def preflight(self, prepared):
            assert prepared.request.request_id == "openttd15-structural-world-001-inv-p001"

        def validate_launch(self, prepared):
            assert prepared.spec.argv[0] == str(prepared.spec.identity.executable)

    monkeypatch.setattr(cli, "StructuralNativeBackend", Backend)
    monkeypatch.setattr(native, "BINARY", prepared.spec.identity.executable)
    monkeypatch.setattr(native, "BINARY_SHA256", prepared.spec.identity.sha256)
    monkeypatch.setattr(sys, "addaudithook", hooks.append)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "proof",
            "preflight",
            "--mode",
            "structural-world",
            "--directory",
            str(prepared.directory),
        ],
    )

    def forbidden(*args, **kwargs):
        pytest.fail("Dry run attempted native process/connection")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    cli.main()
    result = json.loads(capsys.readouterr().out)
    assert result["state"] == "READY_TO_LAUNCH"
    assert result["production_runner_loaded"] and result["accounting_wired"]
    assert result["launch_boundary_reached"] and result["process_creation_blocked"]
    assert result["max_query_operations"] == 1024
    assert result["max_total_post_auth_frames"] == 1030
    assert result["launches"] == result["connections"] == result["requests"] == 0
    for event in ("socket.connect", "subprocess.Popen"):
        with pytest.raises(PermissionError):
            hooks[0](event, ())
    assert not prepared.directory.with_name("openttd-15.3-structural-world-real-attempt1").exists()
    prepared.dispose()


@pytest.mark.parametrize(
    "field,value",
    [
        ("attempt_directory", "alternate"),
        ("proof_kind", "cargo-catalog"),
        ("proof_config_sha256", "0" * 64),
        ("frame_accounting_identity", "0" * 64),
        ("checkpoint_head", "0" * 40),
    ],
)
def test_preflight_rejects_tampered_metadata(tmp_path, field, value):
    import json

    from app.simulation.openttd.proof.harness import manifest
    from app.simulation.openttd.proof.preflight import validate_native_inputs

    p = make_prepared(tmp_path)
    meta_path = p.directory / "PRELAUNCH.json"
    meta = json.loads(meta_path.read_text())
    meta[field] = value
    meta_path.write_text(json.dumps(meta))
    (p.directory / "artifact-manifest.sha256").write_text(manifest(p.directory))
    with pytest.raises(ValueError):
        validate_native_inputs(p)
    p.dispose()


def test_lineage_ignores_other_proof_kinds_but_rejects_unknown_structural_failure(tmp_path):
    from app.simulation.openttd.proof.structural_lineage import capture_lineage, validate_lineage

    target = tmp_path / "prelaunch"
    unrelated = tmp_path / "openttd-15.3-cargo-catalog-failure"
    unrelated.mkdir()
    lineage = capture_lineage(target, 1, tmp_path / "destination")
    assert lineage["proof_kind"] == "structural-world"
    assert lineage["supersedes_prelaunch_attempts"] == []
    unknown = tmp_path / "openttd-15.3-structural-world-unknown-failure"
    unknown.mkdir()
    with pytest.raises(ValueError, match="Unknown"):
        validate_lineage(target, lineage, 1, tmp_path / "destination")


def test_controlled_freeze_and_protected_manifests_are_deterministic(tmp_path):
    import json

    from app.simulation.openttd.proof.harness import sha256
    from app.simulation.openttd.proof.historical_protection import protection_digest

    p = make_prepared(tmp_path)
    freeze = json.loads((p.directory / "source-freeze.json").read_text())
    assert list(freeze) == sorted(set(freeze))
    assert all(
        sha256(__import__("pathlib").Path(path)) == digest for path, digest in freeze.items()
    )
    history = json.loads((p.directory / "historical-integrity.json").read_text())
    assert protection_digest(history) == history["sha256"]
    assert history["paths"] == sorted(set(history["paths"]))
    assert history["unique_count"] == len(history["paths"])
    assert str(p.key_path) not in freeze
    p.dispose()


def test_runner_rejects_parallel_accounting_authority(tmp_path):
    from unittest.mock import Mock

    from app.simulation.openttd.proof.structural_attempt import StructuralProductionRunner

    p = make_prepared(tmp_path)
    backend = Mock(accounting=object())
    with pytest.raises(ValueError, match="Shared secure"):
        StructuralProductionRunner(p, backend)
    p.dispose()


def test_phase_digest_barriers_reject_early_start(tmp_path):
    from unittest.mock import Mock

    from test_structural_world import context

    from app.simulation.openttd.proof.structural_attempt import StructuralProductionRunner
    from app.simulation.openttd.structural_world_session import StructuralWorldSession

    p = make_prepared(tmp_path)
    ctx = context()
    backend = Mock(
        accounting=StructuralFrameBudget(),
        session=ctx.connection_identity,
        secure_connection=ctx.connection_identity,
        process=ctx.process_identity,
    )
    backend.structural_session.transactions = []
    runner = StructuralProductionRunner(p, backend)
    runner.coordinator = StructuralWorldSession(ctx)
    for phase in ("CAPABILITY", "CATALOG", "ASSEMBLY"):
        with pytest.raises(ValueError, match="Early"):
            runner.phase_started(phase)
    p.dispose()


def test_native_frame_observer_is_exact_runner_authority(tmp_path):
    from app.simulation.openttd.proof.structural_attempt import execute_structural_attempt

    p = make_prepared(tmp_path)

    async def run():
        b = ControlledEncryptedBackend()
        result = await execute_structural_attempt(p, b)
        return result, b

    result, b = asyncio.run(run())
    assert result["status"] == "MOCK_SUCCESS"
    assert b.secure_connection._frame_observer.__self__ is b.accounting
    assert not hasattr(b.structural_session, "operations")
    assert len(result["accounting"]["frames"]) == 26


def test_native_budget_rejection_is_an_unsent_attempt():
    from app.simulation.openttd.gamescript_transport import encode_gamescript
    from app.simulation.openttd.proof.structural_contract import structural_first_request
    from app.simulation.openttd.proof.structural_native import StructuralRecordedSession

    async def run():
        reader, writer = asyncio.StreamReader(), Writer()
        budget = StructuralFrameBudget()
        secure = SecureAdminSession(reader, writer, key=KEY, frame_observer=budget.observe)
        wire, _ = server_handshake()
        reader.feed_data(wire)
        await secure.authenticate("proof", "1")
        budget.enter("setup")
        budget.enter("inventory")
        budget.consume("inventory", 256)
        ledger = StructuralRecordedSession(secure)
        q = structural_first_request()
        ledger.expect(q)
        with pytest.raises(ValueError, match="budget"):
            await ledger.send(encode_gamescript(q.to_bytes()))
        row = ledger.transactions[0]
        assert row["delivery"] == "NOT_SENT"
        assert "INDUSTRY_PAGE_REQUEST_SENT" not in row["events"]
        assert len(writer.frames) == 2  # auth only, no encrypted application write

    asyncio.run(run())


def test_surplus_encrypted_frames_are_accounted_and_cannot_be_discarded():
    from app.simulation.openttd.admin_protocol import encode_admin_frame

    async def run():
        reader, writer = asyncio.StreamReader(), Writer()
        budget = StructuralFrameBudget()
        secure = SecureAdminSession(reader, writer, key=KEY, frame_observer=budget.observe)
        wire, cipher = server_handshake()
        reader.feed_data(wire)
        await secure.authenticate("proof", "1")
        budget.enter("setup")
        budget.enter("inventory")
        reader.feed_data(
            cipher.encrypt(encode_admin_frame(126, b"\x54\x01\0\0"))
            + cipher.encrypt(encode_admin_frame(124, b"{}\0"))
        )
        await secure.receive()
        assert budget.query_operations == 2  # including still-buffered duplicate
        with pytest.raises(ValueError, match="buffered"):
            await secure.require_quiescent()
        await secure.close()

    asyncio.run(run())


def test_late_evidence_failure_cannot_publish_complete_world(tmp_path, monkeypatch):
    import json

    from app.simulation.openttd.proof import structural_attempt as owner

    p = make_prepared(tmp_path)
    original = owner.write_json

    def fail_late(path, value):
        if path.name == "admin-frame-accounting.json":
            raise OSError("controlled late retention failure")
        return original(path, value)

    monkeypatch.setattr(owner, "write_json", fail_late)

    async def run():
        return await owner.execute_structural_attempt(p, ControlledEncryptedBackend())

    result = asyncio.run(run())
    assert result["status"] == "MOCK_FAILED"
    dest = p.directory.with_name("openttd-15.3-structural-world-real-attempt1")
    assert not json.loads((dest / "structural-observation.json").read_text())["complete"]
    assert not (dest / "structural-digest.json").exists()


def test_retainer_failure_normalizes_every_completion_artifact(tmp_path, monkeypatch):
    import json

    from app.simulation.openttd.proof import structural_attempt as owner

    p = make_prepared(tmp_path)
    original = owner.write_json

    def fail_world(path, value):
        if path.name == "structural-observation.json":
            raise OSError("controlled final observation write failure")
        return original(path, value)

    monkeypatch.setattr(owner, "write_json", fail_world)

    async def run():
        return await owner.execute_structural_attempt(p, ControlledEncryptedBackend())

    result = asyncio.run(run())
    assert result["status"] == "MOCK_FAILED"
    dest = p.directory.with_name("openttd-15.3-structural-world-real-attempt1")
    assert not json.loads((dest / "structural-session.json").read_text())["complete"]
    assert not json.loads((dest / "structural-observation.json").read_text())["complete"]
    assert not (dest / "structural-digest.json").exists()
