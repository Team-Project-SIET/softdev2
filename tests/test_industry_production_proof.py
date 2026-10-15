"""Single-native preparation exercised with controlled IO only; native activity zero."""

import asyncio
import hashlib
import json
import socket
import subprocess
import sys
from dataclasses import FrozenInstanceError, replace
from unittest.mock import AsyncMock

import pytest
from test_real_ack_graphics import graphics_archive

from app.simulation.openttd.admin_protocol import encode_admin_frame
from app.simulation.openttd.gamescript_bridge import BridgePackage
from app.simulation.openttd.gamescript_transport import encode_gamescript
from app.simulation.openttd.industry_production import (
    PRODUCTION_NETWORK_SEQUENCE,
    IndustryProductionReceipt,
    IndustryProductionRecord,
    IndustryProductionResponse,
)
from app.simulation.openttd.industry_production_evidence import parse_industry_production_evidence
from app.simulation.openttd.proof.harness import prepare_proof
from app.simulation.openttd.proof.production_attempt import (
    ProductionLifecycle,
    ProductionProofState,
)
from app.simulation.openttd.proof.production_contract import (
    FRAME_LIMITS,
    MAX_QUERY_OPERATIONS,
    MAX_TOTAL_POST_AUTH_FRAMES,
    PRODUCTION_ATTEMPT_DIRECTORY,
    PRODUCTION_REQUEST,
    PRODUCTION_REVISION,
    production_contract,
    production_contract_digest,
)
from app.simulation.openttd.proof.production_lineage import capture_lineage, relevant_failures
from app.simulation.openttd.proof.production_native import (
    ProductionFrameBudget,
    ProductionNativeBackend,
    ProductionRecordedSession,
)
from app.simulation.openttd.proof.production_preparation import (
    HISTORICAL_STRUCTURAL,
    select_historical_target,
    validate_production_preparation,
    validate_target,
)
from app.simulation.openttd.proof.production_verification import verify_industry_production
from app.simulation.openttd.proof.structural_contract import StructuralFrameBudget
from app.simulation.openttd.runtime.identity import RuntimeIdentity


def response(produced=0, transported=0, pct=0):
    return IndustryProductionResponse(
        PRODUCTION_REQUEST.request_id,
        IndustryProductionRecord(0, 1, 712223, 712223, produced, transported, pct),
    )


def native_log(result):
    r = result.record
    suffix = "".join(f" {n}={getattr(r, n)}" for n in r.__dataclass_fields__)
    return (
        "dbg: [script:4] [18] [I] BRIDGE_REQUEST_RECEIVED request_id="
        + result.request_id
        + " type=industry_production protocol=1\n"
        + "dbg: [script:4] [18] [I] INDUSTRY_PRODUCTION_READ request_id="
        + result.request_id
        + suffix
        + "\n"
        + "dbg: [script:4] [18] [I] BRIDGE_RESPONSE_SENT request_id="
        + result.request_id
        + " type=industry_production_result status=ok protocol=1\n"
        + "dbg: [script:4] [18] [I] BRIDGE_POST_RESPONSE_ALIVE request_id="
        + result.request_id
        + "\n"
    ).encode()


@pytest.fixture
def prepared(tmp_path):
    binary = tmp_path / "binary"
    binary.write_bytes(b"controlled binary")
    binary.chmod(0o700)
    graphics = tmp_path / "graphics.zip"
    digest = graphics_archive(graphics)
    value = prepare_proof(
        tmp_path / "prelaunch",
        mode="industry-production",
        binary=binary,
        binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        graphics=graphics,
        graphics_sha256=digest,
    )
    yield value
    value.dispose()


def test_historical_first_produced_target():
    target = select_historical_target()
    assert (target["industry_id"], target["cargo_id"]) == (0, 1)
    assert target["supporting_directory"] == str(HISTORICAL_STRUCTURAL)
    assert (
        target["structural_digest"]
        == "060fb6368d2f73deaf3081ec14c9081b4cad4c70541981fe9199131afbc7ac11"
    )
    assert target["same_run_structural_provenance"] == "NOT PROVEN BY THIS SLICE"
    validate_target(target)


@pytest.mark.parametrize("pair", [(1, 1), (0, 0), (9, 8)])
def test_accepted_only_arbitrary_or_nonfirst_target_rejected(pair):
    target = select_historical_target()
    target.update(industry_id=pair[0], cargo_id=pair[1])
    with pytest.raises(ValueError):
        validate_target(target)


def test_synthetic_authority_rejected(tmp_path):
    with pytest.raises(ValueError, match="Synthetic"):
        select_historical_target(tmp_path)


def test_canonical_request_exact():
    expected = (
        b'{"cargo_id":1,"industry_id":0,"protocol":1,'
        b'"request_id":"openttd15-industry-production-001","type":"industry_production"}'
    )
    assert PRODUCTION_REQUEST.to_bytes() == expected
    assert PRODUCTION_REQUEST.request_digest == hashlib.sha256(expected).hexdigest()
    assert len(expected) == 121


def test_payload_schema_bounds():
    contract = production_contract()
    worst = IndustryProductionResponse(
        "x" * 64, IndustryProductionRecord(63999, 63, 2147483647, 2147483647, 65535, 65535, 100)
    ).to_bytes()
    assert len(worst) == contract["worst_case_response_bytes"] == 335
    assert len(worst) <= 512 and len(worst) < 1450
    assert contract["application_headroom"] == 177 and contract["native_headroom"] == 1115
    assert "production_level" not in json.loads(worst)
    assert set(json.loads(worst)) == set(contract["fields"])


@pytest.mark.parametrize("values", [(0, 0, 0), (120, 60, 50), (1, 65535, 100)])
def test_raw_semantic_result_unqualified_and_immutable(tmp_path, values):
    r = response(*values)
    receipt = IndustryProductionReceipt.correlate(PRODUCTION_REQUEST.to_bytes(), r.to_bytes())
    result = verify_industry_production(
        PRODUCTION_REQUEST,
        r.to_bytes(),
        receipt,
        runtime=RuntimeIdentity(tmp_path / "binary", "15.3", "f" * 64),
        bridge=BridgePackage(tmp_path, "e" * 64),
    )
    assert result.verified and result.semantic_validation_result == "VALID_RAW_V1_RECORD"
    assert result.record.last_month_produced == values[0]
    assert result.record.last_month_transported == values[1]
    assert result.record.last_month_transported_pct == values[2]
    assert result.economy_window_bracket == (712223, 712223)
    assert not result.qualified_for_planning and not result.complete_coverage
    assert result.independent_production_source is None
    with pytest.raises(FrozenInstanceError):
        result.verified = False


@pytest.mark.parametrize(
    "field,value",
    [
        ("request_id", "wrong"),
        ("type", "industry_cargo_result"),
        ("industry_id", 1),
        ("cargo_id", 2),
        ("industry_id", -1),
        ("cargo_id", -1),
        ("last_month_produced", -1),
        ("last_month_transported", -1),
        ("last_month_transported_pct", 101),
        ("economy_date_before", -1),
        ("economy_date_after", 0),
        ("production_level", 16),
    ],
)
def test_wrong_or_invalid_response_rejected(tmp_path, field, value):
    r = response().to_bytes()
    obj = json.loads(r)
    obj[field] = value
    bad = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    receipt = IndustryProductionReceipt.correlate(PRODUCTION_REQUEST.to_bytes(), r)
    with pytest.raises(ValueError):
        verify_industry_production(
            PRODUCTION_REQUEST,
            bad,
            receipt,
            runtime=RuntimeIdentity(tmp_path / "binary", "15.3", "f" * 64),
            bridge=BridgePackage(tmp_path, "e" * 64),
        )


def test_oversized_response_rejected():
    with pytest.raises(ValueError):
        IndustryProductionResponse.parse(response().to_bytes() + b" " * 513)


@pytest.mark.parametrize("missing", [0, 1, 2, 3])
def test_missing_native_evidence_fails(missing):
    r = response()
    lines = native_log(r).splitlines(keepends=True)
    with pytest.raises(ValueError):
        parse_industry_production_evidence(
            b"".join(lines[:missing] + lines[missing + 1 :]), r.request_id
        ).require_complete(PRODUCTION_REQUEST, r)


def test_native_evidence_semantics():
    r = response(120, 60, 50)
    evidence = parse_industry_production_evidence(native_log(r), r.request_id)
    evidence.require_complete(PRODUCTION_REQUEST, r)
    assert production_contract()["transported"] == "OpenTTD station-allocation metric"
    assert production_contract()["rollover_waiting"] is False


def test_receipt_alone_cannot_complete_lifecycle():
    state = ProductionLifecycle()
    for value in list(ProductionProofState)[1:6]:
        state.advance(value)
    with pytest.raises(ValueError):
        state.advance(ProductionProofState.COMPLETED)


def test_budget_arithmetic_and_shared_object():
    budget = ProductionFrameBudget()
    assert isinstance(budget, StructuralFrameBudget)
    assert MAX_QUERY_OPERATIONS == 4
    assert MAX_TOTAL_POST_AUTH_FRAMES == 10 == 2 + 3 + 4 + 1
    for phase, ceiling in FRAME_LIMITS.items():
        if phase != "establishment":
            budget.enter(phase)
        for _ in range(ceiling):
            budget.observe("outbound", encode_admin_frame(1 if phase == "cleanup" else 2))
    assert budget.total_frames == 10 and budget.query_operations == 4
    with pytest.raises(ValueError):
        budget.observe("outbound", encode_admin_frame(1))
    assert budget.total_frames == 10 and budget.failed


@pytest.mark.parametrize("phase", list(FRAME_LIMITS))
def test_over_phase_budget_fails(phase):
    budget = ProductionFrameBudget()
    budget.consume(phase, FRAME_LIMITS[phase])
    with pytest.raises(ValueError):
        budget.consume(phase)


@pytest.mark.parametrize("mode", ["retry", "second_type", "wrong_pair"])
def test_recorded_request_guard(mode):
    session = type("Session", (), {"reader": None, "_writer": None, "send": AsyncMock()})()
    recorded = ProductionRecordedSession(session)

    async def exercise():
        await recorded.send(encode_gamescript(PRODUCTION_REQUEST.to_bytes()))
        payload = (
            PRODUCTION_REQUEST.to_bytes()
            if mode == "retry"
            else (
                b'{"type":"ping"}'
                if mode == "second_type"
                else replace(PRODUCTION_REQUEST, cargo_id=2).to_bytes()
            )
        )
        with pytest.raises(ValueError):
            await recorded.send(encode_gamescript(payload))

    asyncio.run(exercise())
    assert session.send.await_count == 1


def test_auth_reconnect_guard():
    backend = ProductionNativeBackend(authorized_one_launch=True)
    backend._connection_claimed = True
    with pytest.raises(ValueError, match="One Admin"):
        asyncio.run(backend.authenticate(None, None))


def test_lineage_excludes_structural_failures(tmp_path):
    (tmp_path / "openttd-15.3-structural-world-real-prelaunch-gate-failure").mkdir()
    lineage = capture_lineage(tmp_path / "freeze", 1, tmp_path / PRODUCTION_ATTEMPT_DIRECTORY)
    assert lineage["proof_kind"] == "industry-production"
    assert lineage["supersedes_prelaunch_attempts"] == []
    assert relevant_failures(tmp_path) == []


def test_frozen_credential_target_destination(prepared):
    d = prepared.directory
    meta = json.loads((d / "PRELAUNCH.json").read_text())
    assert meta["industry_id"] == 0 and meta["cargo_id"] == 1
    assert meta["proof_kind"] == "industry-production"
    assert meta["attempt_id"] == f"industry-production-v{PRODUCTION_REVISION}-native-attempt1"
    assert meta["predecessor_attempt_ids"] == []
    assert meta["attempt_directory"] == str(d.with_name(PRODUCTION_ATTEMPT_DIRECTORY))
    assert meta["proof_config_sha256"] == production_contract_digest()
    assert (d / "request.json").read_bytes() == PRODUCTION_REQUEST.to_bytes()
    assert prepared.key_path.stat().st_mode & 0o777 == 0o600
    frozen = json.loads((d / "source-freeze.json").read_text())
    assert str(prepared.key_path) not in frozen
    secret = prepared.key_path.read_bytes()
    assert all(
        secret not in p.read_bytes() and secret.hex().encode() not in p.read_bytes()
        for p in d.iterdir()
        if p.is_file()
    )


def test_destination_override_rejected(prepared):
    d = prepared.directory
    meta = json.loads((d / "PRELAUNCH.json").read_text())
    bridge = json.loads((d / "bridge-package-identity.json").read_text())
    meta["attempt_directory"] += "-invented"
    with pytest.raises(ValueError):
        validate_production_preparation(prepared, meta, bridge)


def test_public_guarded_preflight_zero_activity(prepared, monkeypatch, capsys):
    import app.simulation.openttd.proof.native as native
    from app.simulation.openttd.proof import __main__ as cli

    monkeypatch.setattr(native, "BINARY", prepared.spec.identity.executable)
    monkeypatch.setattr(native, "BINARY_SHA256", prepared.spec.identity.sha256)

    class Backend:
        def __init__(self, **kwargs):
            pass

        def preflight(self, value):
            assert value.request == PRODUCTION_REQUEST

        def validate_launch(self, value):
            assert value.request == PRODUCTION_REQUEST

    monkeypatch.setattr(cli, "ProductionNativeBackend", Backend)
    monkeypatch.setattr(sys, "addaudithook", lambda guard: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "proof",
            "preflight",
            "--mode",
            "industry-production",
            "--directory",
            str(prepared.directory),
        ],
    )
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("subprocess forbidden"))
    monkeypatch.setattr(
        socket.socket, "connect", lambda *a, **k: pytest.fail("Admin connect forbidden")
    )
    monkeypatch.setattr(
        ProductionNativeBackend,
        "industry_production",
        lambda *a, **k: pytest.fail("request forbidden"),
    )
    cli.main()
    result = json.loads(capsys.readouterr().out)
    assert result["state"] == "READY_TO_LAUNCH"
    assert result["native_api_authority_loaded"] is True
    assert result["launches"] == result["connections"] == result["requests"] == 0
    assert result["accounting_wired"] and result["target_loaded"] and result["request_loaded"]
    assert result["max_query_operations"] == 4 and result["max_total_post_auth_frames"] == 10
    assert result["process_creation_blocked"] and result["final_subprocess_boundary_validated"]


@pytest.mark.parametrize(
    "failure",
    [None, "receipt", "read", "sent", "alive", "semantic", "cleanup", "disposal", "integrity"],
)
def test_controlled_full_lifecycle_retains_failure_without_retry(prepared, failure):
    from app.simulation.openttd.industry_production import IndustryProductionExchange
    from app.simulation.openttd.proof.attempt import Gate
    from app.simulation.openttd.proof.production_attempt import execute_production_attempt

    class Backend:
        kind = "CONTROLLED"
        session = None
        _connection_claimed = False
        launches = 0
        calls = 0
        accounting = ProductionFrameBudget()

        def preflight(self, value):
            pass

        def validate_launch(self, value):
            pass

        async def launch(self, value):
            self.launches += 1
            value.spec.stdout_path.write_bytes(b"controlled\n")
            value.spec.stderr_path.write_bytes(b"controlled startup\n")

        async def authenticate(self, value, gates):
            self.session = object()
            self._connection_claimed = True
            self.accounting.consume("establishment", 2)
            for gate in (
                Gate.ADMIN_CONNECTED,
                Gate.AUTHENTICATED,
                Gate.ENCRYPTION,
                Gate.PROTOCOL,
                Gate.WELCOME,
                Gate.IDENTITY,
            ):
                gates.advance(gate)
            return dict(
                auth=dict(method="X25519_AuthorizedKey", encrypted=True),
                protocol=dict(version=3),
                welcome={},
            )

        async def subscribe(self):
            self.accounting.consume("setup", 3)

        async def wait_production(self, value, *, complete):
            if not complete:
                return None
            lines = native_log(response()).splitlines(keepends=True)
            missing = {"read": 1, "sent": 2, "alive": 3}.get(failure)
            raw = b"".join(lines if missing is None else lines[:missing] + lines[missing + 1 :])
            value.spec.stderr_path.write_bytes(raw)
            return parse_industry_production_evidence(raw, PRODUCTION_REQUEST.request_id)

        async def industry_production(self, request):
            self.calls += 1
            self.accounting.consume("production", 4)
            payload = response().to_bytes()
            receipt = IndustryProductionReceipt.correlate(request.to_bytes(), payload)
            if failure == "receipt":
                receipt = replace(receipt, response_payload_sha256="f" * 64)
            self.exchange = IndustryProductionExchange(request.to_bytes(), payload, receipt)
            if failure == "semantic":
                self.exchange = replace(
                    self.exchange,
                    response_payload=payload.replace(b'"cargo_id":1', b'"cargo_id":2'),
                )
            return self.exchange

        def production_network_evidence(self):
            receipt = getattr(self, "exchange", None)
            return dict(
                ordered_sequence=PRODUCTION_NETWORK_SEQUENCE,
                requests_sent=self.calls,
                matching_responses=self.calls,
                retries=0,
                request_sha256=PRODUCTION_REQUEST.request_digest,
                response_sha256=None
                if receipt is None
                else receipt.receipt.response_payload_sha256,
            )

        def production_response_payload(self):
            exchange = getattr(self, "exchange", None)
            return exchange.response_payload if exchange is not None else None

        def production_receipt(self):
            exchange = getattr(self, "exchange", None)
            return exchange.receipt if exchange is not None else None

        def health(self):
            pass

        async def cleanup(self, value):
            self.accounting.consume("cleanup", 1)
            self.session = None
            if failure == "integrity":
                value.spec.identity.executable.write_bytes(b"changed immutable binary")
            if failure == "disposal":
                (value.spec.workspace.root / "escape").symlink_to(value.spec.identity.executable)
            return dict(
                reaped=True,
                remaining_processes=[],
                graceful_attempted=True,
                returncode=1 if failure == "cleanup" else 0,
            )

    backend = Backend()
    result = asyncio.run(execute_production_attempt(prepared, backend))
    assert backend.calls == backend.launches == 1
    if failure is None:
        assert result["states"][-8:] == [
            "RUNTIME_SEMANTICS_VERIFIED",
            "CLEANUP_STARTED",
            "PROCESS_REAPED",
            "ENDPOINTS_CLOSED",
            "CREDENTIAL_REMOVED",
            "WORKSPACE_DISPOSED",
            "POSTRUN_INTEGRITY_VERIFIED",
            "COMPLETED",
        ]
        assert not prepared.spec.workspace.root.exists()
        from app.simulation.openttd.proof.harness import verify_freeze

        verify_freeze(json.loads((prepared.directory / "source-freeze.json").read_text()))
    else:
        assert "COMPLETED" not in result["states"] and result["states"][-1] == "FAILED"
    if failure == "disposal":
        # Test-only cleanup of its own injected symlink; no historical file restored.
        (prepared.spec.workspace.root / "escape").unlink()
    if failure == "integrity":
        assert "RUNTIME_SEMANTICS_VERIFIED" in result["states"]
        assert result["source_integrity"] is False and not prepared.spec.workspace.root.exists()
    assert not result["qualified_for_planning"]
    assert result["status"] == ("CONTROLLED_SUCCESS" if failure is None else "CONTROLLED_FAILED")
    destination = prepared.directory.with_name(PRODUCTION_ATTEMPT_DIRECTORY)
    assert (destination / "proof-attempt.json").exists()
    assert (destination / "production-response.json").exists()
    assert (destination / "process-lifecycle.json").exists()
    assert not prepared.key_path.exists()
    assert result["connections"] == result["requests_sent"] == result["launches"] == 1
    with pytest.raises(ValueError, match="already claimed"):
        asyncio.run(execute_production_attempt(prepared, backend))


@pytest.mark.parametrize(
    "name",
    [
        "openttd-15.3-structural-world-real-attempt1",
        "openttd-15.3-cargo-catalog-real-attempt1",
        "openttd-15.3-industry-capability-enrichment-real-attempt1",
        "openttd-15.3-industry-inventory-real-attempt1",
        "openttd-15.3-industry-production-controlled-verification",
        "openttd-15.3-industry-production-controlled-verification-v2",
    ],
)
def test_retained_historical_manifest_byte_identity(name):
    from app.simulation.openttd.proof.harness import PROJECT, manifest

    directory = PROJECT / "artifacts/runtime" / name
    assert (directory / "artifact-manifest.sha256").read_text() == manifest(directory)


def test_architecture_authority_unchanged():
    # Authority identity from the retained controlled milestone, never edited here.
    import json

    from app.simulation.openttd.proof.harness import PROJECT

    frozen = json.loads(
        (
            PROJECT
            / "artifacts/runtime/openttd-15.3-structural-world-real-prelaunch/source-freeze.json"
        ).read_text()
    )
    assert (
        hashlib.sha256((PROJECT / "CONTEXT.md").read_bytes()).hexdigest()
        == frozen[str(PROJECT / "CONTEXT.md")]
    )


def test_proof_has_no_qualification_rollover_state_or_planning_imports():
    import ast

    from app.simulation.openttd.proof.harness import PROJECT

    for path in (PROJECT / "app/simulation/openttd/proof").glob("production_*.py"):
        tree = ast.parse(path.read_text())
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        assert not any(
            n.startswith(
                ("app.planning", "app.evaluation", "app.simulation.openttd.production_observation")
            )
            for n in imports
        )
    assert production_contract()["qualified_for_planning"] is False
    assert production_contract()["max_application_requests"] == 1
    assert production_contract()["additional_command_types"] == 0
    assert production_contract()["retries"] == production_contract()["reconnects"] == 0
