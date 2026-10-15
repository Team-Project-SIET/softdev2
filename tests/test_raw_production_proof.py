"""Combined public/native ownership seams with an encrypted synthetic peer only."""

import asyncio
import hashlib
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from test_complete_raw_production import CombinedWire
from test_structural_production import ControlledEncryptedBackend

from app.simulation.openttd.industry_cargo import IndustryCargoRequest
from app.simulation.openttd.industry_page import IndustryPageRequest
from app.simulation.openttd.industry_production import (
    IndustryProductionRecord,
    IndustryProductionRequest,
)
from app.simulation.openttd.proof import __main__ as cli
from app.simulation.openttd.proof.economy_authority import (
    calendar_economy_month,
    economy_authority,
    economy_clock_contract,
)
from app.simulation.openttd.proof.harness import manifest, prepare_proof
from app.simulation.openttd.proof.raw_production_attempt import (
    RawProductionLifecycle,
    RawProductionProofState,
    RawProductionRunner,
    execute_raw_production_attempt,
)
from app.simulation.openttd.proof.raw_production_contract import (
    RAW_PRODUCTION_ATTEMPT_DIRECTORY,
    raw_production_contract,
)
from app.simulation.openttd.proof.raw_production_native import RawProductionNativeBackend


def prepared(tmp_path):
    from test_real_ack_graphics import graphics_archive

    binary = tmp_path / "controlled-openttd"
    binary.write_bytes(b"controlled, never executed")
    binary.chmod(0o700)
    graphics = tmp_path / "graphics.zip"
    digest = graphics_archive(graphics)
    return prepare_proof(
        tmp_path / "prelaunch",
        mode="complete-raw-production",
        binary=binary,
        binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        graphics=graphics,
        graphics_sha256=digest,
    )


class ControlledCombinedBackend(RawProductionNativeBackend):
    """Native runner and secure observer, without a subprocess or network socket."""

    kind = "MOCK"

    def preflight(self, prepared):
        from app.simulation.openttd.admin_crypto import AuthorizedKey

        self._key = AuthorizedKey.from_bytes(prepared.key_path.read_bytes())

    def validate_launch(self, prepared):
        assert prepared.spec.identity.executable.read_bytes() == b"controlled, never executed"

    async def launch(self, prepared):
        from unittest.mock import Mock

        self._prepared = prepared
        self.process = Mock(spec=subprocess.Popen)
        prepared.spec.stderr_path.write_text(
            "dbg: [script:4] [18] [I] BRIDGE_STARTED protocol=1 api=15\n"
            "Using the OpenGFX base graphics set\n"
        )
        prepared.spec.stdout_path.write_text("")

    async def authenticate(self, prepared, gates):
        template = type(ControlledEncryptedBackend())
        return await getattr(template, "authenticate")(self, prepared, gates)

    def health(self):
        pass

    async def cleanup(self, prepared):
        if self.secure_connection is not None:
            await self.secure_connection.close(quit=True)
        return dict(
            reaped=True,
            remaining_processes=[],
            graceful_attempted=True,
            returncode=0,
            cleanup_error=None,
            admin_frame_accounting=self.accounting.snapshot(),
        )

    def __init__(self, *, industries=(2, 17), produces=(1, 63), cargoes=(1, 9, 63), failure=None):
        super().__init__(authorized_one_launch=True)
        self._peer = None
        self._peer_options = dict(
            industries=industries,
            produces=produces,
            cargoes=cargoes,
            fail=failure if failure in ("timeout", "disconnect") else None,
            duplicate=failure == "duplicate",
        )
        self.failure = failure

    @property
    def peer(self):
        if self._peer is None:
            self._peer = CombinedWire(**self._peer_options)
            self._peer.date = calendar_economy_month(712223).start_date + 4
        return self._peer

    async def evidence(self, prepared, request, exchange):
        if isinstance(request, IndustryProductionRequest):
            if self.failure == "evidence":
                raise ValueError("controlled missing production evidence")
            if self.failure == "month":
                raise ValueError("controlled economy window failure")
            if self.failure == "replacement":
                from test_secure_admin import KEY, Writer

                from app.simulation.openttd.secure_admin import SecureAdminSession

                self.session = SecureAdminSession(asyncio.StreamReader(), Writer(), key=KEY)
            if self.failure == "process":
                from unittest.mock import Mock

                self.process = Mock(spec=subprocess.Popen)
            evidence = await self.peer.evidence_for(request, exchange)
        elif isinstance(request, IndustryPageRequest):
            evidence = await self.peer.evidence(request, exchange)
        elif isinstance(request, IndustryCargoRequest):
            evidence = await self.peer.cargo_evidence(request, exchange)
        else:
            evidence = await self.peer.catalog_evidence(request, exchange)
        with prepared.spec.stderr_path.open("ab") as stream:
            stream.write(evidence.raw_log)
        return await super().evidence(prepared, request, exchange)


def run_proof(tmp_path, **kwargs):
    p = prepared(tmp_path)
    backend = ControlledCombinedBackend(**kwargs)
    result = asyncio.run(execute_raw_production_attempt(p, backend))
    return p, backend, result


@pytest.mark.parametrize(
    "industries,produces,cargoes",
    [
        ((), (), (1,)),
        ((17,), (), (1,)),
        ((0,), (1,), (1, 9)),
        ((2, 17), (1, 63), (1, 9, 63)),
        (tuple(range(32)), tuple(range(16)), tuple(range(64))),
    ],
)
def test_complete_owned_encrypted_combined_session(tmp_path, industries, produces, cargoes):
    p, b, result = run_proof(tmp_path, industries=industries, produces=produces, cargoes=cargoes)
    assert result["status"] == "MOCK_SUCCESS", result["error"]
    c = b.combined_coordinator
    assert c.structural.complete and c.production.complete
    assert c.production.source is c.structural
    assert not c.production.qualified_for_planning
    assert c.production.qualification.rollover_count == 0
    assert tuple(r.pair for r in c.production.records) == tuple(
        (i, k) for i in industries for k in produces
    )
    assert c.production.source_structural_world_digest == c.structural.structural_world_digest
    assert b.coordinator.context is c.context is c.production.context
    assert b.secure_connection._frame_observer.__self__ is b.accounting
    assert result["accounting"]["query_operations"] == 4 * result["requests_sent"]
    assert result["accounting"]["total_post_auth_frames"] == 4 * result["requests_sent"] + 6
    assert result["states"] == [
        s.name for s in RawProductionProofState if s is not RawProductionProofState.FAILED
    ]
    assert result["source_integrity"]
    assert not p.spec.workspace.root.exists() and not p.key_path.exists()
    dest = p.directory.with_name(RAW_PRODUCTION_ATTEMPT_DIRECTORY)
    assert json.loads((dest / "production-observation.json").read_text())["complete"]
    assert json.loads((dest / "combined-session.json").read_text())["complete"]
    assert json.loads((dest / "process-lifecycle.json").read_text())["sockets_closed"]
    assert c.evidence.events.index("STRUCTURAL_WORLD_VERIFIED") < c.evidence.events.index(
        "PRODUCTION_TARGET_SET_FINALIZED"
    )
    assert c.evidence.events.index("PRODUCTION_TARGET_SET_FINALIZED") < c.evidence.events.index(
        "COMPLETE_PRODUCTION_COVERAGE_VALIDATED"
    )
    assert "PRODUCTION_QUALIFICATION_EVALUATED" in c.evidence.events
    assert result["retries"] == result["reconnects"] == 0


@pytest.mark.parametrize(
    "failure", ["timeout", "disconnect", "duplicate", "evidence", "replacement", "process"]
)
def test_failed_production_never_retries_or_publishes_complete(tmp_path, failure):
    p, b, result = run_proof(tmp_path, failure=failure)
    assert result["status"] == "MOCK_FAILED"
    assert result["states"][-1] == "FAILED"
    assert len(b.peer.production_requests) == 1
    assert b.combined_coordinator.structural.complete
    assert b.combined_coordinator.production is None
    assert result["retries"] == result["reconnects"] == 0
    dest = p.directory.with_name(RAW_PRODUCTION_ATTEMPT_DIRECTORY)
    assert not json.loads((dest / "production-observation.json").read_text())["complete"]
    assert not json.loads((dest / "combined-session.json").read_text())["complete"]
    assert not p.key_path.exists() and not p.spec.workspace.root.exists()


def test_public_guarded_preflight_dispatches_combined_runner_without_native_activity(
    tmp_path, monkeypatch, capsys
):
    p = prepared(tmp_path)
    import app.simulation.openttd.proof.native as native

    monkeypatch.setattr(cli, "RawProductionNativeBackend", lambda **kw: ControlledCombinedBackend())
    monkeypatch.setattr(native, "BINARY", p.spec.identity.executable)
    monkeypatch.setattr(native, "BINARY_SHA256", p.spec.identity.sha256)
    hooks = []
    monkeypatch.setattr(sys, "addaudithook", hooks.append)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "proof",
            "preflight",
            "--mode",
            "complete-raw-production",
            "--directory",
            str(p.directory),
        ],
    )

    def forbidden(*args, **kwargs):
        pytest.fail("guarded preflight attempted native process/connect/request")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(ControlledCombinedBackend, "industry_production", forbidden, raising=False)
    cli.main()
    value = json.loads(capsys.readouterr().out)
    assert value["state"] == "READY_TO_LAUNCH"
    assert value["proof_kind"] == "complete-raw-production"
    assert value["production_runner_loaded"] and value["combined_runner_loaded"]
    assert value["economy_authority_loaded"] and value["combined_lifecycle_loaded"]
    assert value["launch_boundary_reached"] and value["process_creation_blocked"]
    assert value["max_application_requests"] == 608
    assert value["max_response_bytes"] == 220672
    assert value["max_query_operations"] == 5120
    assert value["max_total_post_auth_frames"] == 5126
    assert value["launches"] == value["connections"] == value["requests"] == 0
    for event in ("socket.connect", "subprocess.Popen"):
        with pytest.raises(PermissionError):
            hooks[0](event, ())
    assert not p.directory.with_name(RAW_PRODUCTION_ATTEMPT_DIRECTORY).exists()
    p.dispose()


@pytest.mark.parametrize(
    "field,value",
    [
        ("attempt_directory", "alternate"),
        ("proof_kind", "industry-production"),
        ("proof_config_sha256", "0" * 64),
        ("economy_authority_digest", "0" * 64),
        ("frame_accounting_identity", "0" * 64),
        ("baseline_head", "0" * 40),
        ("attempt_id", "industry-production-v3-native-attempt2"),
    ],
)
def test_frozen_metadata_override_is_rejected(tmp_path, field, value):
    from app.simulation.openttd.proof.preflight import validate_native_inputs

    p = prepared(tmp_path)
    data = json.loads((p.directory / "PRELAUNCH.json").read_text())
    data[field] = value
    (p.directory / "PRELAUNCH.json").write_text(json.dumps(data))
    (p.directory / "artifact-manifest.sha256").write_text(manifest(p.directory))
    with pytest.raises(ValueError):
        validate_native_inputs(p)
    p.dispose()


def test_freeze_contains_fresh_credential_identity_without_private_bytes(tmp_path):
    p = prepared(tmp_path)
    key = p.key_path.read_bytes()
    assert p.key_path.stat().st_mode & 0o777 == 0o600
    frozen = json.loads((p.directory / "source-freeze.json").read_text())
    assert str(p.key_path) not in frozen
    assert all(
        key not in path.read_bytes() and key.hex().encode() not in path.read_bytes()
        for path in p.directory.iterdir()
        if path.is_file()
    )
    value = json.loads((p.directory / "PRELAUNCH.json").read_text())
    assert value["attempt_directory"] == str(
        p.directory.with_name(RAW_PRODUCTION_ATTEMPT_DIRECTORY)
    )
    assert value["predecessor_attempt_ids"] == []
    assert value["source_input_count"] == len(frozen)
    p.dispose()


def test_native_economy_api_authority_and_field_domain():
    source = Path("tests/reference/economy_clock_15_3")
    cpp = (source / "script_date.cpp").read_text()
    header = (source / "script_date.hpp").read_text()
    assert "ScriptDate::GetCurrentDate()" in cpp
    assert "(ScriptDate::Date)TimerGameEconomy::date.base()" in cpp
    assert "static Date GetCurrentDate();" in header
    assert "enum Date" in header
    assert '"game;GS"' in (source / "CMakeLists.txt").read_text()
    assert '"^Script" "${APIUC}"' in (source / "SquirrelExport.cmake").read_text()
    contract = economy_clock_contract()
    assert contract["gamescript_binding"] == "GSDate.GetCurrentDate"
    assert contract["fields"] == ["economy_date_before", "economy_date_after"]
    assert contract["equal_brackets_valid"]
    assert not contract["welcome_is_current_date"]
    assert economy_authority()["sha256"] == economy_authority()["sha256"]


@pytest.mark.parametrize(
    "year,leap",
    [(0, True), (4, True), (100, False), (400, True), (1900, False), (1950, False), (2000, True)],
)
def test_native_year_zero_and_century_calendar_boundaries(year, leap):
    from app.simulation.openttd.proof.economy_authority import _year_start

    february = calendar_economy_month(_year_start(year) + 31)
    assert (february.year, february.month) == (year, 2)
    assert february.end_date - february.start_date == (29 if leap else 28)
    assert calendar_economy_month(february.end_date).month == 3


@pytest.mark.parametrize("date", [-1, True, 2147483647, "712223"])
def test_invalid_native_clock_identity_rejected(date):
    with pytest.raises(ValueError):
        calendar_economy_month(date)


@pytest.mark.parametrize("delta", [0, 4, 30])
def test_equal_brackets_later_in_initial_month_are_valid_not_historical_constants(delta):
    month = calendar_economy_month(712223)
    date = month.start_date + delta
    assert month.contains(IndustryProductionRecord(0, 1, date, date, 0, 0, 0))
    assert not raw_production_contract()["qualified_for_planning"]


def test_lifecycle_requires_every_runtime_and_postrun_barrier_before_completion():
    lifecycle = RawProductionLifecycle()
    for state in list(RawProductionProofState)[1:-2]:
        with pytest.raises(ValueError):
            lifecycle.advance(RawProductionProofState.COMPLETED)
        lifecycle.advance(state)
    lifecycle.advance(RawProductionProofState.COMPLETED)
    with pytest.raises(ValueError):
        lifecycle.advance(RawProductionProofState.LAUNCHED)


def test_cleanup_after_partial_failure_cannot_claim_completed():
    lifecycle = RawProductionLifecycle()
    lifecycle.advance(RawProductionProofState.CLEANUP_STARTED)
    for state in list(RawProductionProofState)[11:16]:
        lifecycle.advance(state)
    with pytest.raises(ValueError):
        lifecycle.advance(RawProductionProofState.COMPLETED)
    lifecycle.fail()
    assert lifecycle.states[-1] is RawProductionProofState.FAILED


def test_post_disposal_integrity_failure_after_semantic_success_is_failed(tmp_path, monkeypatch):
    import app.simulation.openttd.proof.raw_production_attempt as owner

    original = owner.finalize_cleanup

    def failed(p, frozen, cleanup):
        original(p, frozen, cleanup)
        raise ValueError("controlled post-disposal integrity failure")

    monkeypatch.setattr(owner, "finalize_cleanup", failed)
    p, b, result = run_proof(tmp_path)
    assert b.combined_coordinator.production.complete
    assert result["status"] == "MOCK_FAILED"
    assert result["states"][-1] == "FAILED"
    assert "COMPLETED" not in result["states"]
    assert not p.key_path.exists() and not p.spec.workspace.root.exists()
    assert not json.loads(
        (
            p.directory.with_name(RAW_PRODUCTION_ATTEMPT_DIRECTORY) / "production-observation.json"
        ).read_text()
    )["complete"]


def test_native_preflight_failure_has_no_process_connection_request_and_is_immutable(
    tmp_path, monkeypatch
):
    p = prepared(tmp_path)
    backend = ControlledCombinedBackend()

    def fail(p):
        raise ValueError("controlled prelaunch rejection")

    monkeypatch.setattr(backend, "validate_launch", fail)
    with pytest.raises(ValueError):
        asyncio.run(execute_raw_production_attempt(p, backend))
    assert backend.launches == 0 and backend.session is None
    failure = p.directory.with_name(p.directory.name + "-gate-failure")
    assert json.loads((failure / "proof-attempt.json").read_text())["classification"] == "PRELAUNCH"
    assert not p.directory.with_name(RAW_PRODUCTION_ATTEMPT_DIRECTORY).exists()
    p.dispose()


def test_combined_kind_ignores_industry_production_failure_lineage(tmp_path):
    from app.simulation.openttd.proof.raw_production_lineage import capture_lineage

    (tmp_path / "openttd-15.3-industry-production-real-attempt1").mkdir()
    lineage = capture_lineage(
        tmp_path / "prelaunch", 1, tmp_path / RAW_PRODUCTION_ATTEMPT_DIRECTORY
    )
    assert lineage["attempt_number"] == 1
    assert not lineage["post_launch_predecessors"]
    assert not lineage["prelaunch_continuation_exception_used"]


def test_query_accounting_replacement_rejected(tmp_path, monkeypatch):
    p = prepared(tmp_path)
    b = ControlledCombinedBackend()
    monkeypatch.setattr(b, "accounting", object())
    with pytest.raises(ValueError, match="accounting"):
        RawProductionRunner(p, b)
    p.dispose()


def test_terminal_persistence_failure_cannot_retain_final_success(tmp_path, monkeypatch):
    import app.simulation.openttd.proof.raw_production_attempt as owner
    from app.simulation.openttd.proof.raw_production_lineage import read_attempt

    original = owner.write_json
    failed = False

    def write(path, value):
        nonlocal failed
        if path.name == "proof-evidence.json" and not failed:
            failed = True
            raise OSError("controlled terminal persistence failure")
        original(path, value)

    monkeypatch.setattr(owner, "write_json", write)
    p, b, result = run_proof(tmp_path)
    dest = p.directory.with_name(RAW_PRODUCTION_ATTEMPT_DIRECTORY)
    assert b.combined_coordinator.production.complete
    assert result["status"] == "MOCK_FAILED"
    assert result["states"][-1] == "FAILED" and "COMPLETED" not in result["states"]
    assert result["source_integrity"]
    assert not p.key_path.exists() and not p.spec.workspace.root.exists()
    for name in ("combined-session.json", "production-observation.json", "production-session.json"):
        assert not json.loads((dest / name).read_text())["complete"]
    assert not (dest / "production-canonical.json").exists()
    assert read_attempt(dest).classification == "RUNTIME"
    assert read_attempt(dest).terminal_status == "MOCK_FAILED"


def test_native_brackets_crossing_initial_month_fail_without_waiting(tmp_path):
    p = prepared(tmp_path)
    b = ControlledCombinedBackend()

    async def run():
        b.peer.date = calendar_economy_month(712223).end_date
        return await execute_raw_production_attempt(p, b)

    result = asyncio.run(run())
    assert result["status"] == "MOCK_FAILED"
    assert b.combined_coordinator is not None
    assert b.combined_coordinator.structural.complete
    assert len(b.peer.production_requests) == 1
    assert result["retries"] == result["reconnects"] == 0
    assert not p.spec.workspace.root.exists() and not p.key_path.exists()


def test_postlaunch_failure_requires_new_attempt_and_newer_freeze(tmp_path):
    from app.simulation.openttd.proof.raw_production_lineage import (
        capture_lineage,
        validate_lineage,
    )

    p, _, result = run_proof(tmp_path, failure="evidence")
    assert result["launches"] == result["connections"] == 1
    future = tmp_path / "openttd-15.3-complete-raw-production-real-attempt2"
    revision = tmp_path / "openttd-15.3-complete-raw-production-real-prelaunch-v2"
    lineage = capture_lineage(revision, 2, future)
    assert lineage["attempt_number"] == 2
    assert not lineage["prelaunch_continuation_exception_used"]
    assert lineage["post_launch_predecessors"][0]["classification"] == "RUNTIME"
    assert validate_lineage(revision, lineage, 2, future) == 1
    with pytest.raises(ValueError):
        capture_lineage(revision, 1, future)
    with pytest.raises(ValueError):
        validate_lineage(
            revision, lineage, 2, p.directory.with_name(RAW_PRODUCTION_ATTEMPT_DIRECTORY)
        )


def test_cleanup_failure_blocks_completed_even_after_semantic_success(tmp_path, monkeypatch):
    p = prepared(tmp_path)
    b = ControlledCombinedBackend()
    original = b.cleanup

    async def fail(prepared):
        value = await original(prepared)
        value["cleanup_error"] = "controlled cleanup failure"
        return value

    monkeypatch.setattr(b, "cleanup", fail)
    result = asyncio.run(execute_raw_production_attempt(p, b))
    assert b.combined_coordinator is not None
    assert b.combined_coordinator.production.complete
    assert result["status"] == "MOCK_FAILED"
    assert result["states"][-1] == "FAILED" and "COMPLETED" not in result["states"]
    assert not result["source_integrity"] and not p.key_path.exists()
    dest = p.directory.with_name(RAW_PRODUCTION_ATTEMPT_DIRECTORY)
    assert not json.loads((dest / "production-observation.json").read_text())["complete"]
    # Disposal was deliberately blocked by the unproved cleanup; this controlled
    # fake process has already been reaped, so its test-owned workspace can go.
    p.dispose()


def test_unproven_bridge_rejected_before_fresh_credential_generation(tmp_path, monkeypatch):
    from app.simulation.openttd.admin_crypto import AuthorizedKey
    from app.simulation.openttd.proof import raw_production_preparation

    monkeypatch.setattr(raw_production_preparation, "PROVEN_BRIDGE_DIGEST", "0" * 64)

    def forbidden():
        pytest.fail("credential created before non-credential inputs validated")

    monkeypatch.setattr(AuthorizedKey, "generate", forbidden)
    with pytest.raises(ValueError, match="bridge unchanged identity"):
        prepared(tmp_path)
    failure = json.loads((tmp_path / "prelaunch/PRELAUNCH-FAILURE.json").read_text())
    assert failure["proof_kind"] == "complete-raw-production"
    assert failure["prelaunch_revision"] == 1
    assert failure["gameplay_launches"] == failure["connections"] == failure["requests"] == 0
    assert not (tmp_path / "prelaunch/isolated/.admin-secret").exists()
