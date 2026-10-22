"""Offline proof preparation and one-shot fake child; never a native process."""

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.simulation.openttd.proof import terrain_preparation as prep
from app.simulation.openttd.proof.terrain_attempt import (
    authorized_native_run,
    execute_single_page,
    verify_page,
)
from app.simulation.openttd.runtime.base import ProcessLifecycle
from app.simulation.openttd.tile_facts import (
    TileFactsExchange,
    TileFactsReceipt,
    TileFactsResponse,
)
from app.simulation.openttd.tile_facts_evidence import GS_SEQUENCE

PREFIX = "dbg: [script:4] [18] [I] "


def response():
    return TileFactsResponse(
        prep.REQUEST.request_id,
        prep.REQUEST.region,
        0,
        64,
        64,
        712000,
        712000,
        tuple(
            (i, 0, 0, 1, None, -1, 0, 0, 0, 2 if i == 65 else 8 if i == 69 else 10)
            for i in range(65, 70)
        ),
        None,
        False,
    )


def exchange(r=None, operations=4):
    payload = (r or response()).to_bytes()
    q = prep.REQUEST.to_bytes()
    return TileFactsExchange(
        q, payload, TileFactsReceipt.correlate(q, payload), protocol_operations=operations
    )


def evidence(ex):
    suffixes = (
        " type=tile_facts_page protocol=1",
        " response_json=" + ex.response.to_bytes().decode(),
        " type=tile_facts_page_result status=ok protocol=1",
        "",
    )
    return "".join(
        PREFIX + event + " request_id=" + prep.REQUEST.request_id + suffix + "\n"
        for event, suffix in zip(GS_SEQUENCE, suffixes, strict=True)
    ).encode()


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    binary = tmp_path / "openttd"
    binary.write_bytes(b"controlled executable - never executed")
    project = tmp_path / "project"
    gfx = project / "artifacts/runtime/verified-assets/OpenGFX-8.0"
    gfx.mkdir(parents=True)
    archive = gfx.with_name("opengfx-8.0-all.zip")
    archive.write_bytes(b"controlled graphics")
    nut = project / "app/simulation/openttd/terrain_bridge.nut"
    nut.parent.mkdir(parents=True)
    nut.write_bytes(b"controlled source")
    monkeypatch.setattr(prep, "BINARY", binary)
    monkeypatch.setattr(prep, "BINARY_SHA256", prep.sha256(binary))
    monkeypatch.setattr(prep, "ARCHIVE_SHA256", prep.sha256(archive))
    monkeypatch.setattr(prep, "PROJECT", project)
    monkeypatch.setattr(prep, "source_freeze", lambda: {str(nut): prep.sha256(nut)})
    monkeypatch.setattr(prep, "validate_baseset", lambda p: ())
    monkeypatch.setattr(prep, "stage_opengfx", lambda *a, **k: None)
    return prep.prepare_candidate(tmp_path / "candidate")


def test_candidate_valid_and_unassigned(candidate):
    assert candidate.preflight()["authorized"] is False
    assert candidate.record["attempt_identity"] is None
    assert candidate.record["expected_tiles"] == [65, 66, 67, 68, 69]
    assert len(list(candidate.directory.rglob(".admin-secret"))) == 1
    assert "public_key" in candidate.record


@pytest.mark.parametrize(
    "name",
    [
        "request.json",
        "source.json",
        "bridge/main.nut",
        "bridge/info.nut",
        "config-template.cfg",
        "historical-integrity.json",
    ],
)
def test_candidate_bytes_changed(candidate, name):
    (candidate.directory / name).write_bytes(b"changed")
    with pytest.raises((ValueError, KeyError, json.JSONDecodeError)):
        candidate.preflight()


@pytest.mark.parametrize("asset", ["executable", "graphics_archive"])
def test_asset_missing(candidate, asset):
    Path(candidate.record[asset]).unlink()
    with pytest.raises(FileNotFoundError):
        candidate.preflight()


@pytest.mark.parametrize("asset", ["executable", "graphics_archive"])
def test_asset_changed(candidate, asset):
    Path(candidate.record[asset]).write_bytes(b"different bytes")
    with pytest.raises(ValueError):
        candidate.preflight()


@pytest.mark.parametrize(
    "field,value",
    [
        ("attempt_identity", "attempt1"),
        ("authorized", True),
        ("version", "13.4"),
        ("bridge_digest", "0" * 64),
    ],
)
def test_candidate_record_cannot_change(candidate, field, value):
    row = {**candidate.record, field: value}
    (candidate.directory / "CANDIDATE.json").write_text(json.dumps(row))
    with pytest.raises(ValueError):
        candidate.preflight()


def test_source_mutation(candidate):
    Path(next(iter(candidate.record["source_integrity"]))).write_bytes(b"mutated")
    with pytest.raises(ValueError):
        candidate.preflight()


def test_exact_budget_and_package():
    assert prep.budget()["native_getter_calls"] == 226
    assert prep.budget()["post_auth_frames"] == 2 + 3 + 8 + 1 == 14
    source = prep.package_bytes()["main.nut"].decode()
    assert "RawObservationBridge.Handle.call(this, request)" in source
    assert "base.Handle" not in source
    assert "function TileFactsPage(" in source
    assert "class NoMutationBridge extends TerrainBridge" in source
    assert prep.package_bytes()["info.nut"].count(b'return "15"') == 1


@pytest.mark.parametrize("operations", [4, 8])
def test_frame_limits(operations):
    b = prep.SinglePageFrames()
    b.consume("establishment", 2)
    b.enter("setup")
    b.consume("setup", 3)
    b.enter("query")
    b.consume("query", operations)
    b.consume("cleanup")
    assert b.total_frames == operations + 6
    with pytest.raises(ValueError):
        b.enter("setup")
    with pytest.raises(ValueError):
        b.consume("query", 9 - operations)


@pytest.mark.parametrize(
    "change",
    ["id", "cursor", "duplicate", "missing", "order", "dimensions", "oversized508", "oversized512"],
)
def test_page_rejection(change):
    ex = exchange()
    value = json.loads(ex.response_payload)
    if change == "id":
        value["request_id"] = "other"
    elif change == "cursor":
        value["cursor"] = 5
    elif change == "duplicate":
        value["tiles"][1] = value["tiles"][0]
    elif change == "missing":
        value["tiles"].pop()
    elif change == "order":
        value["tiles"].reverse()
    elif change == "dimensions":
        value["map"] = [128, 64]
    payload = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    if change.startswith("oversized"):
        payload += b" " * ((509 if change.endswith("508") else 513) - len(payload))
    with pytest.raises(ValueError):
        receipt = TileFactsReceipt.correlate(prep.REQUEST.to_bytes(), payload)
        bad = replace(ex, response_payload=payload, receipt=receipt)
        verify_page(bad, evidence(ex), 64, 64)


@pytest.mark.parametrize("missing", ["TILE_FACTS_READ", "BRIDGE_POST_RESPONSE_ALIVE"])
def test_evidence_missing(missing):
    ex = exchange()
    raw = (
        b"\n".join(line for line in evidence(ex).splitlines() if missing.encode() not in line)
        + b"\n"
    )
    with pytest.raises(ValueError):
        verify_page(ex, raw, 64, 64)


class FakeChild:
    pid = 999999
    stdin = None
    reaped = False

    def poll(self):
        return 0

    def wait(self, timeout=None):
        self.reaped = True
        return 0


class FakeBackend:
    kind = "CONTROLLED"
    launches = connections = requests = 0

    def __init__(self, case="valid", operations=4):
        self.case = case
        self.operations = operations
        self.accounting = prep.SinglePageFrames()
        self.child = FakeChild()
        self.welcome = SimpleNamespace(width=64, height=64)

    def preflight(self, prepared):
        pass

    async def launch(self, prepared):
        self.launches += 1
        prepared.spec.lifecycle.process = self.child
        if self.case == "crash":
            raise RuntimeError("controlled crash")

    async def authenticate(self, prepared, gates):
        from app.simulation.openttd.proof.attempt import Gate

        for gate in list(Gate)[1:7]:
            gates.advance(gate)
        self.connections += 1
        self.accounting.consume("establishment", 2)
        if self.case == "lost":
            raise ConnectionError("controlled disconnect")
        return {"controlled": True}

    async def setup(self, prepared):
        self.accounting.enter("setup")
        self.accounting.consume("setup", 3)

    async def tile_facts_page(self, request):
        self.requests += 2 if self.case == "second" else 1
        self.accounting.consume("query", self.operations)
        if self.case == "handler":
            raise RuntimeError("controlled handler exception")
        return exchange(operations=self.operations)

    async def page_evidence(self, prepared, ex):
        raw = evidence(ex)
        if self.case == "liveness":
            raw = b"\n".join(raw.splitlines()[:-1]) + b"\n"
        if self.case == "mutate":
            (prepared.directory / "source.txt").write_text("changed")
        prepared.spec.stderr_path.write_bytes(raw)
        return raw

    async def cleanup(self, prepared):
        prepared.spec.lifecycle.close()
        self.accounting.consume("cleanup")
        return dict(reaped=self.child.reaped, remaining_processes=[], cleanup_error=[])


@pytest.fixture
def prepared(tmp_path):
    directory = tmp_path / "prepared"
    directory.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    destination = tmp_path / "controlled-attempt"
    (directory / "source.txt").write_text("original")
    (directory / "source-freeze.json").write_text(
        json.dumps({str(directory / "source.txt"): prep.sha256(directory / "source.txt")})
    )
    (directory / "request.json").write_bytes(prep.REQUEST.to_bytes())
    (directory / "PRELAUNCH.json").write_text(
        json.dumps(
            dict(
                state="CONTROLLED_FAKE_PRELAUNCH",
                mode="terrain-single-page",
                attempt_directory=str(destination),
                budget=prep.budget(),
                game_port=3979,
                admin_port=3977,
            )
        )
    )
    p = SimpleNamespace(
        directory=directory,
        request=prep.REQUEST,
        endpoints=(3979, 3977),
        spec=SimpleNamespace(
            workspace=SimpleNamespace(root=workspace),
            stdout_path=workspace / "stdout.log",
            stderr_path=workspace / "stderr.log",
            lifecycle=ProcessLifecycle(),
        ),
    )
    return p, destination


@pytest.mark.parametrize(
    "case", ["valid", "second", "handler", "liveness", "lost", "crash", "mutate", "endpoint"]
)
def test_one_shot_fake_child(prepared, monkeypatch, case):
    from app.simulation.openttd.proof import endpoints

    p, destination = prepared
    monkeypatch.setattr(
        endpoints,
        "kernel_socket_rows",
        lambda: (
            []
            if case != "endpoint"
            else [
                dict(
                    local_port=3977,
                    remote_port=0,
                    local="127.0.0.1",
                    remote="0.0.0.0",
                    table="tcp",
                    state=10,
                )
            ]
        ),
    )
    backend = FakeBackend(case)
    result = asyncio.run(execute_single_page(p, backend, destination))
    assert result["status"] == ("CONTROLLED_PASS" if case == "valid" else "CONTROLLED_FAILED")
    assert backend.child.reaped
    assert (destination / "result.json").is_file()
    with pytest.raises(ValueError):
        asyncio.run(execute_single_page(p, backend, destination))


def test_native_authorization_unreachable(prepared):
    p, destination = prepared
    with pytest.raises(PermissionError):
        asyncio.run(authorized_native_run(p, destination))
    with pytest.raises(PermissionError):
        asyncio.run(authorized_native_run(p, destination, authorize_one_launch=True))
    assert not destination.exists()


@pytest.mark.parametrize("operations", [4, 8, 9])
def test_one_shot_accounting_and_offline_acceptance(prepared, monkeypatch, operations):
    from app.simulation.openttd.proof import endpoints
    from app.simulation.openttd.proof.terrain_attempt import verify_retained_attempt

    monkeypatch.setattr(endpoints, "kernel_socket_rows", lambda: [])
    p, destination = prepared
    result = asyncio.run(execute_single_page(p, FakeBackend(operations=operations), destination))
    if operations == 9:
        assert result["status"] == "CONTROLLED_FAILED"
        with pytest.raises(ValueError):
            verify_retained_attempt(destination)
    else:
        assert result["status"] == "CONTROLLED_PASS"
        assert verify_retained_attempt(destination)["mode"] == "CONTROLLED"
        (destination / "response.json").write_bytes(b"mutated")
        with pytest.raises(ValueError):
            verify_retained_attempt(destination)


@pytest.mark.parametrize(
    "name",
    [
        "public_key",
        "argv",
        "endpoints",
        "source_digest",
        "request_sha256",
        "configuration_digest",
        "budget",
    ],
)
def test_coordinated_candidate_metadata_mutation_rejected(candidate, name):
    # An attacker changing both in-memory and persisted metadata must still fail.
    record = json.loads(json.dumps(candidate.record))
    record[name] = "invalid"
    (candidate.directory / "CANDIDATE.json").write_text(json.dumps(record))
    with pytest.raises((ValueError, TypeError, KeyError)):
        prep.TerrainCandidate(candidate.directory, record).preflight()


@pytest.mark.parametrize("tile_count", [0, 6, 256])
def test_single_page_region_required(candidate, tile_count):
    value = json.loads(prep.REQUEST.to_bytes())
    value["region"] = [1, 1, tile_count, 1]
    (candidate.directory / "request.json").write_text(json.dumps(value))
    with pytest.raises(ValueError):
        candidate.preflight()


def test_native_backend_requires_authorization():
    from app.simulation.openttd.proof.terrain_native import SinglePageNativeBackend

    with pytest.raises(PermissionError):
        SinglePageNativeBackend()


def test_preflight_cannot_launch(candidate, monkeypatch):
    import subprocess

    from app.simulation.openttd.secure_admin import SecureAdminSession

    def forbidden(*args, **kwargs):
        pytest.fail("Native execution boundary crossed")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(SecureAdminSession, "connect_secure", forbidden)
    assert candidate.preflight()["launches"] == 0


def test_selected_response_worst_case_tagged_serializer(tmp_path):
    import os
    import subprocess

    masks = (2, 10, 10, 10, 8)
    worst = replace(
        response(),
        date_before=2147483647,
        date_after=2147483647,
        rows=tuple((65 + i, 255, 31, 8191, 63999, 14, 1, m, m, m) for i, m in enumerate(masks)),
    )
    assert len(prep.REQUEST.to_bytes()) == 111
    assert len(worst.to_bytes()) == prep.budget()["response_bytes"] == 420
    assert verify_page(exchange(worst), evidence(exchange(worst)), 64, 64)["coverage_valid"]
    exe = os.environ.get("TILE_FACTS_SERIALIZER_PROBE")
    if not exe:
        pytest.skip("Tagged serializer probe not configured")

    def squirrel(value):
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, str):
            return json.dumps(value)
        if isinstance(value, list):
            return "[" + ",".join(squirrel(v) for v in value) + "]"
        if isinstance(value, dict):
            return "{" + ",".join(k + "=" + squirrel(v) for k, v in value.items()) + "}"
        return str(value)

    path = tmp_path / "selected-worst-case.nut"
    path.write_text("::replies <- [" + squirrel(json.loads(worst.to_bytes())) + "];")
    result = subprocess.run([exe, str(path)], capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    payload = next(line[5:] for line in result.stdout.splitlines() if line.startswith(b"JSON "))
    assert payload == worst.to_bytes()


def test_unexpected_frame_is_retained_and_rejected():
    import struct

    b = prep.SinglePageFrames()
    with pytest.raises(ValueError):
        b.observe("inbound", struct.pack("<HB", 3, 124))
    assert b.failed
    assert len(b.snapshot()["frames"]) == 1


@pytest.mark.parametrize("extra", [0, 1, 4096])
def test_native_capture_exact_bound_offline(extra):
    from io import BytesIO

    from app.simulation.openttd.proof.terrain_native import SinglePageNativeBackend

    backend = SinglePageNativeBackend(authorized_one_launch=True)
    output = BytesIO()
    limit = prep.budget()["capture_bytes"]
    asyncio.run(backend._capture(BytesIO(b"x" * (limit + extra)), output))
    assert len(output.getvalue()) == limit
    assert backend._capture_failed is (extra > 0)


def test_unsolicited_pong_cannot_hide_in_query_allowance():
    import struct

    from app.simulation.openttd.gamescript_transport import encode_gamescript

    b = prep.SinglePageFrames()
    b.consume("establishment", 2)
    b.enter("setup")
    b.consume("setup", 3)
    b.enter("query")
    b.observe("outbound", encode_gamescript(prep.REQUEST.to_bytes()))
    with pytest.raises(ValueError):
        b.observe("inbound", struct.pack("<HBI", 7, 126, 0x154))
    assert b.failed


def test_owned_typed_inputs_are_not_authorization(candidate, tmp_path):
    p = prep.load_terrain_prepared(candidate.directory, tmp_path / "unsealed")
    assert p.request == prep.REQUEST
    assert p.spec.argv == tuple(candidate.record["argv"])
    assert p.spec.lifecycle.process is None
    with pytest.raises(FileNotFoundError):
        asyncio.run(authorized_native_run(p, tmp_path / "never-created", authorize_one_launch=True))
    assert not (tmp_path / "never-created").exists()


def test_native_launch_boundary_rechecks_seal(candidate, tmp_path, monkeypatch):
    from app.simulation.openttd.proof.native import NativeBackend
    from app.simulation.openttd.proof.terrain_native import SinglePageNativeBackend

    p = prep.load_terrain_prepared(candidate.directory, tmp_path / "unsealed")
    monkeypatch.setattr(NativeBackend, "validate_launch", lambda *args: None)
    backend = SinglePageNativeBackend(authorized_one_launch=True)
    with pytest.raises(FileNotFoundError):
        backend.validate_launch(p)


@pytest.fixture
def sealed(candidate, tmp_path, monkeypatch):
    from app.simulation.openttd.proof import terrain_attempt as attempt
    from app.simulation.openttd.proof.terrain_seal import seal_candidate

    monkeypatch.setattr(attempt, "PROJECT", prep.PROJECT)
    monkeypatch.setattr(attempt, "source_freeze", prep.source_freeze)
    # Ownership/history use an isolated test project, not protected repository inputs.
    return seal_candidate(candidate, tmp_path / "sealed", tmp_path / "native-attempt")


def test_unauthorized_seal_lifecycle(sealed):
    from app.simulation.openttd.proof.terrain_attempt import validate_immutable_seal
    from app.simulation.openttd.proof.terrain_seal import validate_seal_record

    row = json.loads((sealed.directory / "PRELAUNCH.json").read_text())
    target = Path(row["attempt_directory"])
    assert validate_immutable_seal(sealed, target)
    assert validate_seal_record(sealed.directory, target)["authorized_one_launch"] is False
    assert not target.exists()
    assert sealed.directory.stat().st_mode & 0o222 == 0
    assert all(p.stat().st_mode & 0o222 == 0 for p in sealed.directory.iterdir())
    with pytest.raises(PermissionError):
        asyncio.run(authorized_native_run(sealed, target, authorize_one_launch=True))
    assert not target.exists()


def approval(sealed):
    row = json.loads((sealed.directory / "PRELAUNCH.json").read_text())
    return dict(
        seal_sha256=prep.sha256(sealed.directory / "PRELAUNCH.json"),
        attempt_identity=row["attempt_identity"],
        attempt_directory=row["attempt_directory"],
        authorized_launch_count=1,
        schema="openttd-terrain-one-launch",
        version=1,
        authorization_id="CONTROLLED_TEST_ONLY",
        issuer_id="CONTROLLED_TEST_ONLY",
        proof_operation="openttd-15.3.tile_facts_page.single_page",
        approval_evidence="CONTROLLED_TEST_ONLY",
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("seal_sha256", "0" * 64),
        ("attempt_identity", "other"),
        ("attempt_directory", "/wrong"),
        ("authorized_launch_count", 2),
        ("authorized_launch_count", True),
    ],
)
def test_authorization_wrong_binding(sealed, field, value):
    from app.simulation.openttd.proof.terrain_seal import validate_authorization

    a = approval(sealed)
    target = Path(a["attempt_directory"])
    a[field] = value
    with pytest.raises(PermissionError):
        validate_authorization(sealed.directory, target, a, authority=lambda _: True)
    assert not target.exists()


def test_fake_approval_never_production_authority(sealed):
    from app.simulation.openttd.proof.terrain_seal import validate_authorization

    a = approval(sealed)
    target = Path(a["attempt_directory"])
    with pytest.raises(PermissionError, match="issuer is not configured"):
        validate_authorization(sealed.directory, target, a)
    with pytest.raises(PermissionError, match="provenance rejected"):
        validate_authorization(sealed.directory, target, a, authority=lambda _: False)
    with pytest.raises(PermissionError):
        asyncio.run(
            authorized_native_run(sealed, target, authorize_one_launch=True, authorization=a)
        )
    assert not target.exists()


def test_controlled_authorization_and_consumption_one_shot(sealed):
    from app.simulation.openttd.proof.terrain_seal import consume_authorized_attempt

    a = approval(sealed)
    target = Path(a["attempt_directory"])
    before = (sealed.directory / "PRELAUNCH.json").read_bytes()
    consume_authorized_attempt(sealed.directory, target, a, authority=lambda x: x == a)
    assert (target / "authorization-consumed.json").exists()
    (target / "failure.json").write_text('{"controlled_failure":true}')
    with pytest.raises(PermissionError, match="replayed"):
        consume_authorized_attempt(sealed.directory, target, a, authority=lambda _: True)
    assert (target / "failure.json").exists()
    assert (sealed.directory / "PRELAUNCH.json").read_bytes() == before


def test_seal_mutation_rejected(sealed):
    from app.simulation.openttd.proof.terrain_attempt import validate_immutable_seal

    path = sealed.directory / "PRELAUNCH.json"
    target = Path(approval(sealed)["attempt_directory"])
    path.chmod(0o644)
    path.write_bytes(path.read_bytes() + b" ")
    path.chmod(0o444)
    with pytest.raises(ValueError, match="digest"):
        validate_immutable_seal(sealed, target)


def test_seal_source_mutation_rejected(sealed):
    from app.simulation.openttd.proof.terrain_attempt import validate_immutable_seal

    source = Path(next(iter(prep.source_freeze())))
    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="Frozen"):
        validate_immutable_seal(sealed, Path(approval(sealed)["attempt_directory"]))


def test_second_seal_at_same_destination_rejected(candidate, sealed):
    from app.simulation.openttd.proof.terrain_seal import seal_candidate

    with pytest.raises(ValueError, match="Fresh"):
        seal_candidate(candidate, sealed.directory, Path(approval(sealed)["attempt_directory"]))


@pytest.mark.parametrize("target_name", ["bridge/main.nut", "request.json", "config-template.cfg"])
def test_seal_candidate_input_mutation_rejected(sealed, target_name):
    from app.simulation.openttd.proof.terrain_attempt import validate_immutable_seal

    row = json.loads((sealed.directory / "PRELAUNCH.json").read_text())
    source = Path(row["candidate_path"]) / target_name
    source.write_bytes(b"mutated")
    with pytest.raises(ValueError):
        validate_immutable_seal(sealed, Path(row["attempt_directory"]))


def test_invalid_candidate_cannot_publish_seal(candidate, tmp_path):
    from app.simulation.openttd.proof.terrain_seal import seal_candidate

    (candidate.directory / "request.json").write_bytes(b"changed")
    target = tmp_path / "must-not-exist"
    with pytest.raises(ValueError):
        seal_candidate(candidate, target, tmp_path / "unused-attempt")
    assert not target.exists()


def test_unauthorized_seal_cannot_consume(sealed):
    from app.simulation.openttd.proof.terrain_seal import consume_authorized_attempt

    target = Path(approval(sealed)["attempt_directory"])
    with pytest.raises(PermissionError):
        consume_authorized_attempt(sealed.directory, target, None)
    assert not target.exists()


def test_sealed_gate_precedes_fake_backend(sealed):
    row = json.loads((sealed.directory / "PRELAUNCH.json").read_text())
    backend = FakeBackend()
    backend.kind = "REAL"  # Controlled sentinel only; not the native backend.
    with pytest.raises(PermissionError):
        asyncio.run(execute_single_page(sealed, backend, Path(row["attempt_directory"])))
    assert (backend.launches, backend.connections, backend.requests) == (0, 0, 0)
    assert not Path(row["attempt_directory"]).exists()


def test_sealing_never_spawns_or_connects(candidate, tmp_path, monkeypatch):
    import socket
    import subprocess

    from app.simulation.openttd.proof import terrain_attempt as attempt
    from app.simulation.openttd.proof.terrain_seal import seal_candidate

    monkeypatch.setattr(attempt, "PROJECT", prep.PROJECT)
    monkeypatch.setattr(attempt, "source_freeze", prep.source_freeze)

    def forbidden(*args, **kwargs):
        raise AssertionError("Native activity forbidden")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    p = seal_candidate(candidate, tmp_path / "sealed", tmp_path / "unconsumed")
    assert p.spec.lifecycle.process is None
    assert not (tmp_path / "unconsumed").exists()


def test_attempt_consumption_is_durable(sealed, monkeypatch):
    import os

    from app.simulation.openttd.proof.terrain_seal import consume_authorized_attempt

    calls = []
    original = os.fsync

    def observe(fd):
        calls.append(fd)
        return original(fd)

    monkeypatch.setattr(os, "fsync", observe)
    a = approval(sealed)
    consume_authorized_attempt(
        sealed.directory, Path(a["attempt_directory"]), a, authority=lambda x: x == a
    )
    assert len(calls) >= 3, "Claim parent, consumption file and attempt directory need fsync"


class ControlledApprovalRegistry:
    """Opaque controlled receipt lookup; not a production issuer or signing key."""

    def __init__(self, value):
        from app.simulation.openttd.proof.terrain_authorization import OneLaunchAuthorization

        a = OneLaunchAuthorization.from_mapping(value)
        self.subject = a.canonical_bytes()
        self.issuer = a.issuer_id
        self.evidence = a.approval_evidence

    def __call__(self, value):
        from app.simulation.openttd.proof.terrain_authorization import OneLaunchAuthorization

        a = OneLaunchAuthorization.from_mapping(value)
        return (
            a.issuer_id == self.issuer
            and a.canonical_bytes() == self.subject
            and a.approval_evidence == self.evidence
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("issuer_id", "UNKNOWN_ISSUER"),
        ("approval_evidence", "forged"),
        ("authorization_id", "different"),
        ("proof_operation", "other-operation"),
        ("schema", "other-schema"),
        ("version", 2),
        ("approval_evidence", ""),
        ("approval_evidence", "x" * 4097),
        ("authorized_launch_count", 0),
    ],
)
def test_strict_approval_contract_rejects(sealed, field, value):
    from app.simulation.openttd.proof.terrain_seal import validate_authorization

    a = approval(sealed)
    registry = ControlledApprovalRegistry(a)
    target = Path(a["attempt_directory"])
    a[field] = value
    with pytest.raises(PermissionError):
        validate_authorization(sealed.directory, target, a, authority=registry)
    assert not target.exists()


def test_controlled_canonical_approval_never_production(sealed):
    from app.simulation.openttd.proof.terrain_authorization import OneLaunchAuthorization
    from app.simulation.openttd.proof.terrain_seal import validate_authorization

    a = approval(sealed)
    b = dict(reversed(list(a.items())))
    assert (
        OneLaunchAuthorization.from_mapping(a).canonical_bytes()
        == OneLaunchAuthorization.from_mapping(b).canonical_bytes()
    )
    target = Path(a["attempt_directory"])
    assert validate_authorization(
        sealed.directory, target, b, authority=ControlledApprovalRegistry(a)
    )
    with pytest.raises(PermissionError, match="issuer is not configured"):
        validate_authorization(sealed.directory, target, b)
    assert not target.exists()


def test_concurrent_consumption_at_most_one(sealed):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from app.simulation.openttd.proof.terrain_seal import consume_authorized_attempt

    a = approval(sealed)
    target = Path(a["attempt_directory"])
    barrier = Barrier(2)
    registry = ControlledApprovalRegistry(a)

    def authority(value):
        valid = registry(value)
        barrier.wait(timeout=10)
        return valid

    def claim():
        try:
            consume_authorized_attempt(sealed.directory, target, a, authority=authority)
            return "STARTED"
        except PermissionError, FileExistsError:
            return "REJECTED"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: claim(), range(2)))
    assert sorted(outcomes) == ["REJECTED", "STARTED"]
    assert json.loads((target / "authorization-consumed.json").read_text())["state"] == "STARTED"


def test_crash_after_claim_retains_consumption(sealed, monkeypatch):
    from app.simulation.openttd.proof import terrain_seal

    a = approval(sealed)
    target = Path(a["attempt_directory"])

    def crash(*args):
        raise OSError("CONTROLLED_SIMULATED_CRASH")

    monkeypatch.setattr(terrain_seal, "write_json", crash)
    with pytest.raises(OSError, match="SIMULATED_CRASH"):
        terrain_seal.consume_authorized_attempt(
            sealed.directory, target, a, authority=ControlledApprovalRegistry(a)
        )
    assert target.is_dir()
    (target / "failure.json").write_text('{"controlled_crash":true}')
    with pytest.raises(PermissionError, match="replayed"):
        terrain_seal.consume_authorized_attempt(
            sealed.directory, target, a, authority=ControlledApprovalRegistry(a)
        )
    assert (target / "failure.json").exists()


def test_source_change_during_approval_fails_after_durable_claim(sealed):
    from app.simulation.openttd.proof.terrain_seal import consume_authorized_attempt

    a = approval(sealed)
    target = Path(a["attempt_directory"])
    registry = ControlledApprovalRegistry(a)

    def authority(value):
        valid = registry(value)
        Path(next(iter(prep.source_freeze()))).write_bytes(b"changed after verification")
        return valid

    with pytest.raises(ValueError, match="Frozen"):
        consume_authorized_attempt(sealed.directory, target, a, authority=authority)
    assert (target / "authorization-consumed.json").exists()


def test_unsigned_extra_flag_is_not_approval(sealed):
    from app.simulation.openttd.proof.terrain_seal import validate_authorization

    a = approval(sealed)
    a["authorized"] = True
    with pytest.raises(PermissionError, match="fields"):
        validate_authorization(
            sealed.directory, Path(a["attempt_directory"]), a, authority=lambda _: True
        )
