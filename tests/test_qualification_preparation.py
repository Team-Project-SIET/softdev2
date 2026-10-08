"""Public qualification proof gates and cleanup, with controlled encrypted peers."""

import asyncio
import hashlib
import json
import subprocess
import sys
from functools import partial

import pytest
from test_qualification_coordinator import QualificationWire
from test_raw_production_proof import ControlledCombinedBackend

from app.simulation.openttd.proof import __main__ as cli
from app.simulation.openttd.proof.harness import manifest, prepare_proof
from app.simulation.openttd.proof.qualification_attempt import (
    QualificationLifecycle,
    QualificationProofState,
    execute_qualification_attempt,
)
from app.simulation.openttd.proof.qualification_authority import qualification_authority
from app.simulation.openttd.proof.qualification_contract import (
    ATTEMPT_DIRECTORY,
    KIND,
    first_request,
    qualification_contract,
)
from app.simulation.openttd.proof.qualification_native import QualificationNativeBackend
from app.simulation.openttd.qualification_clock import EconomyClockRequest, IndustryLifetimeRequest
from app.simulation.openttd.qualification_session import ProductionQualificationSession


def prepared(tmp_path):
    from test_real_ack_graphics import graphics_archive

    # Controlled predecessor is distinct from immutable real Attempt 1 evidence.
    from app.simulation.openttd.proof.harness import write_json

    for number in (1, 2, 3):
        previous = tmp_path / f"openttd-15.3-two-rollover-qualification-real-attempt{number}"
        if not previous.exists():
            previous.mkdir()
            old_freeze = tmp_path / f"controlled-freeze-v{number}"
            old_freeze.mkdir()
            write_json(
                old_freeze / "PRELAUNCH.json",
                dict(mode=KIND, prelaunch_revision=number if number < 3 else 4),
            )
            record = dict(
                status="REAL_FAILED",
                launches=1,
                connections=1,
                requests_sent=62 if number == 1 else 185,
                preparation=str(old_freeze),
                attempt_id=f"two-rollover-qualification-v{number}-native-attempt{number}",
            )
            write_json(previous / "proof-evidence.json", record)
            (previous / "artifact-manifest.sha256").write_text(manifest(previous))

    binary = tmp_path / "controlled-openttd"
    binary.write_bytes(b"controlled, never executed")
    binary.chmod(0o700)
    graphics = tmp_path / "graphics.zip"
    graphics_digest = graphics_archive(graphics)
    return prepare_proof(
        tmp_path / "prelaunch",
        mode=KIND,
        binary=binary,
        binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        graphics=graphics,
        graphics_sha256=graphics_digest,
    )


class ControlledQualificationBackend(ControlledCombinedBackend, QualificationNativeBackend):
    def __init__(self, *, industries=(2, 17), failure=None, authorized_one_launch=True):
        QualificationNativeBackend.__init__(self, authorized_one_launch=True)
        self._peer = None
        self.industries = industries
        self.failure = failure

    @property
    def peer(self):
        if self._peer is None:
            self._peer = QualificationWire(industries=self.industries)
        return self._peer

    async def evidence(self, prepared, request, exchange):
        if self.failure == "evidence":
            raise ValueError("missing controlled qualification evidence")
        if isinstance(request, (EconomyClockRequest, IndustryLifetimeRequest)):
            evidence = await self.peer.native_evidence(request, exchange)
            with prepared.spec.stderr_path.open("ab") as stream:
                stream.write(evidence.raw_log)
            return await QualificationNativeBackend.evidence(self, prepared, request, exchange)
        return await ControlledCombinedBackend.evidence(self, prepared, request, exchange)

    def configure_transport(self, prepared, protocol):
        QualificationNativeBackend.configure_transport(self, prepared, protocol)


@pytest.mark.parametrize(
    "phase,values", qualification_contract()["resources"]["phase_bounds"].items()
)
def test_frozen_independent_phase_bounds(phase, values):
    expected = {
        "clock": (304, 82384, 2432),
        "anchor_structural": (96, 49152, 1024),
        "anchor_lifetime": (32, 7936, 256),
        "final_structural": (96, 49152, 1024),
        "final_lifetime": (32, 7936, 256),
        "production": (512, 171520, 4096),
    }
    assert tuple(values.values()) == expected[phase]


@pytest.mark.parametrize(
    "field,value",
    [
        ("application_requests", 1072),
        ("response_bytes", 368080),
        ("query_operations", 9088),
        ("lifecycle_frames", 6),
        ("post_auth_frames", 9094),
        ("clock_requests", 304),
        ("wait_polls", 299),
        ("poll_interval", 1),
        ("timeout", 300),
    ],
)
def test_resource_arithmetic_exact(field, value):
    assert qualification_contract()["resources"][field] == value


@pytest.mark.parametrize("state", list(QualificationProofState)[1:-1])
def test_lifecycle_rejects_skipped_barrier(state):
    life = QualificationLifecycle()
    if state is QualificationProofState.CLEANUP_STARTED:
        life.advance(state)  # Failure cleanup allowed early; cannot subsequently complete.
        with pytest.raises(ValueError):
            life.advance(QualificationProofState.COMPLETED)
    elif state is QualificationProofState.LAUNCHED:
        life.advance(state)
        assert life.states[-1] is state
    else:
        with pytest.raises(ValueError):
            life.advance(state)


def test_freeze_identity_and_private_exclusion(tmp_path):
    p = prepared(tmp_path)
    try:
        m = json.loads((p.directory / "PRELAUNCH.json").read_text())
        assert m["proof_kind"] == KIND
        assert m["attempt_id"] == "two-rollover-qualification-v5-native-attempt4"
        assert m["attempt_directory"] == str(tmp_path / ATTEMPT_DIRECTORY)
        assert p.request == first_request()
        assert p.key_path.stat().st_mode & 0o777 == 0o600
        secret = p.key_path.read_bytes()
        assert all(
            secret not in f.read_bytes() and secret.hex().encode() not in f.read_bytes()
            for f in p.directory.rglob("*")
            if f.is_file() and f != p.key_path
        )
        assert (p.directory / "artifact-manifest.sha256").read_text() == manifest(p.directory)
        assert (
            json.loads((p.directory / "qualification-contract.json").read_text())
            == qualification_contract()
        )
    finally:
        p.dispose()


@pytest.mark.parametrize(
    "metadata,value",
    [
        ("attempt_directory", "other"),
        ("checkpoint_head", "wrong"),
        ("proof_kind", "industry-production"),
        ("polling_policy_digest", "wrong"),
        ("qualification_contract_digest", "wrong"),
    ],
)
def test_frozen_override_rejected(tmp_path, metadata, value):
    from app.simulation.openttd.proof.preflight import preflight_prepared

    p = prepared(tmp_path)
    try:
        path = p.directory / "PRELAUNCH.json"
        m = json.loads(path.read_text())
        m[metadata] = value
        path.write_text(json.dumps(m))
        with pytest.raises(ValueError):
            preflight_prepared(p, ControlledQualificationBackend())
    finally:
        p.dispose()


def test_public_guarded_preflight(tmp_path, monkeypatch, capsys):
    p = prepared(tmp_path)
    monkeypatch.setattr(cli, "load_prepared", lambda directory, mode: p)
    monkeypatch.setattr(cli, "QualificationNativeBackend", ControlledQualificationBackend)
    monkeypatch.setattr(
        sys, "addaudithook", lambda hook: None
    )  # assertions below block both boundary APIs
    monkeypatch.setattr(
        subprocess, "Popen", lambda *a, **kw: pytest.fail("subprocess in guarded preflight")
    )
    monkeypatch.setattr(
        sys, "argv", ["proof", "preflight", "--mode", KIND, "--directory", str(p.directory)]
    )
    try:
        cli.main()
        result = json.loads(capsys.readouterr().out)
        assert result["state"] == "READY_TO_LAUNCH"
        assert result["qualification_runner_loaded"] and result["ownership_loaded"]
        assert result["resources"]["post_auth_frames"] == 9094
        assert result["launches"] == result["connections"] == result["requests"] == 0
        assert (
            not result["subprocess_created"]
            and not result["admin_connected"]
            and not result["request_sent"]
        )
    finally:
        p.dispose()


@pytest.mark.parametrize("industries,failure", [((2, 17), None), ((), None), ((2, 17), "evidence")])
def test_owned_qualification_cleanup_before_acceptance(tmp_path, monkeypatch, industries, failure):
    from app.simulation.openttd.proof import qualification_attempt

    async def run():
        b = ControlledQualificationBackend(industries=industries, failure=failure)
        monkeypatch.setattr(
            qualification_attempt,
            "ProductionQualificationSession",
            partial(
                ProductionQualificationSession,
                pace=b.peer.pace,
                monotonic=lambda: b.peer.virtual_time,
            ),
        )
        p = prepared(tmp_path)
        result = await execute_qualification_attempt(p, b)
        return p, b, result

    p, b, result = asyncio.run(run())
    assert result["status"] == ("MOCK_SUCCESS" if failure is None else "MOCK_FAILED"), result[
        "error"
    ]
    assert not p.key_path.exists() and not p.spec.workspace.root.exists()
    assert result["source_integrity"]
    if failure is None:
        assert result["qualified_for_planning"]
        assert result["states"][-1] == "COMPLETED"
        assert result["states"].index("POSTRUN_INTEGRITY_VERIFIED") < result["states"].index(
            "COMPLETED"
        )
        assert (
            result["accounting"]["total_post_auth_frames"]
            == result["accounting"]["query_operations"] + 6
        )
        assert b.qualification_coordinator.production.qualified_for_planning
    else:
        assert result["states"][-1] == "FAILED"


def test_native_authority_exact_date_domains():
    authority = qualification_authority()
    assert authority["clock"]["C++"][0] == "ScriptDate::GetCurrentDate"
    assert authority["lifetime"]["C++"] == "ScriptIndustry::GetConstructionDate"
    assert authority["lifetime"]["domain"].startswith("CALENDAR")
    assert authority["timing"]["tick_ms"] == 27


def test_contract_zero_targets_and_exclusions():
    c = qualification_contract()
    assert c["zero_targets_allowed"] and not c["initial_production_used"]
    assert not c["atomic_snapshot"] and not c["p08_integration"]
    assert c["production_response_bound"] == 335
    assert c["production_level"] == "DEFERRED / NOT INCLUDED"


def test_distinct_lineage_ignores_unrelated_production_failure(tmp_path):
    from app.simulation.openttd.proof.qualification_lineage import capture_lineage

    old = tmp_path / "openttd-15.3-industry-production-real-attempt1"
    old.mkdir()
    (old / "proof-attempt.json").write_text(json.dumps({"proof_kind": "industry-production"}))
    value = capture_lineage(
        tmp_path / "prelaunch",
        1,
        tmp_path / "openttd-15.3-two-rollover-qualification-real-attempt1",
    )
    assert value["attempt_number"] == 1
    assert not value["post_launch_predecessors"]
    assert not value["prelaunch_continuation_exception_used"]


def test_lineage_rejects_destination_override(tmp_path):
    from app.simulation.openttd.proof.qualification_lineage import capture_lineage

    with pytest.raises(ValueError):
        capture_lineage(tmp_path / "prelaunch", 1, tmp_path / "other")


def test_lifecycle_complete_only_after_all_cleanup_states():
    life = QualificationLifecycle()
    for state in list(QualificationProofState)[1:-1]:
        life.advance(state)
    assert life.states[-1] is QualificationProofState.COMPLETED
    with pytest.raises(ValueError):
        life.advance(QualificationProofState.LAUNCHED)


def test_composed_package_has_persistent_canonical_source(tmp_path):
    p = prepared(tmp_path)
    try:
        m = json.loads((p.directory / "runtime-materializations.json").read_text())
        source = p.directory / "bridge-inputs/main.nut"
        assert (
            source.read_bytes()
            == (p.spec.workspace.game / "NoMutationBridge/main.nut").read_bytes()
        )
        assert any(v["canonical_source"] == str(source) for v in m["entries"])
        root = p.spec.workspace.root
        p.dispose()
        assert not root.exists() and source.is_file()
    finally:
        p.dispose()


@pytest.mark.parametrize("failure", ["integrity", "terminal"])
def test_finalization_failure_cannot_publish_qualification(tmp_path, monkeypatch, failure):
    from app.simulation.openttd.proof import (
        qualification_attempt,
        qualification_lineage,
        raw_production_attempt,
    )

    if failure == "integrity":
        original = raw_production_attempt.finalize_cleanup

        def fail(*args):
            original(*args)
            raise ValueError("controlled post-run integrity failure")

        monkeypatch.setattr(raw_production_attempt, "finalize_cleanup", fail)
    else:

        def fail(*args):
            raise ValueError("controlled terminal evidence failure")

        monkeypatch.setattr(qualification_lineage, "retain_attempt_identity", fail)

    async def run():
        b = ControlledQualificationBackend()
        monkeypatch.setattr(
            qualification_attempt,
            "ProductionQualificationSession",
            partial(
                ProductionQualificationSession,
                pace=b.peer.pace,
                monotonic=lambda: b.peer.virtual_time,
            ),
        )
        p = prepared(tmp_path)
        return p, await execute_qualification_attempt(p, b)

    p, result = asyncio.run(run())
    assert result["status"] == "MOCK_FAILED"
    assert not result["qualified_for_planning"]
    assert result["states"][-1] == "FAILED"
    observation = json.loads(
        (tmp_path / ATTEMPT_DIRECTORY / "production-observation.json").read_text()
    )
    assert not observation["complete"] and not observation["qualified_for_planning"]
    assert not p.spec.workspace.root.exists()


def test_public_prepare_default_destination(monkeypatch, capsys):
    from types import SimpleNamespace

    from app.simulation.openttd.proof.harness import PROJECT
    from app.simulation.openttd.proof.qualification_contract import PRELAUNCH_DIRECTORY

    def fake(directory, *, mode):
        assert mode == KIND
        assert directory == PROJECT / "artifacts/runtime" / PRELAUNCH_DIRECTORY
        return SimpleNamespace(directory=directory)

    monkeypatch.setattr(cli, "prepare_proof", fake)
    monkeypatch.setattr(sys, "argv", ["proof", "prepare", "--mode", KIND])
    cli.main()
    assert "PRELAUNCH only" in capsys.readouterr().out
