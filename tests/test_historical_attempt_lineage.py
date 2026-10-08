"""Consumed evidence validates historically, never as execution authorization."""

import importlib
import json
from pathlib import Path

import pytest

from app.simulation.openttd.proof import qualification_lineage as lineage

ROOT = Path(__file__).resolve().parents[1] / "artifacts/runtime"
PREFIX = lineage.PREFIX


def freeze(revision):
    suffix = "" if revision == 1 else f"-v{revision}"
    return ROOT / f"{PREFIX}-real-prelaunch{suffix}"


def controlled_freeze(root, revision, number):
    from app.simulation.openttd.proof.harness import manifest, write_json
    from app.simulation.openttd.proof.qualification_contract import qualification_contract

    suffix = "" if revision == 1 else f"-v{revision}"
    directory = root / f"{PREFIX}-real-prelaunch{suffix}"
    directory.mkdir()
    destination = root / f"{PREFIX}-real-attempt{number}"
    value = lineage.derive_next_attempt(directory, revision, destination)
    contract = qualification_contract() | {
        "revision": revision,
        "future_destination": destination.name,
    }
    metadata = dict(
        mode=lineage.KIND,
        proof_kind=lineage.KIND,
        prelaunch_revision=revision,
        attempt_id=value["attempt_id"],
        attempt_directory=str(destination),
        lineage_digest=value["lineage_digest"],
        proof_config_sha256=lineage.digest(contract),
        predecessor_attempt_ids=sorted(r["attempt_id"] for r in lineage.lineage_rows(value)),
    )
    write_json(directory / "PRELAUNCH.json", metadata)
    write_json(directory / "attempt-lineage.json", value)
    write_json(directory / "qualification-contract.json", contract)
    (directory / "artifact-manifest.sha256").write_text(manifest(directory))
    return directory, destination, value


def controlled_consume(frozen, status, *, offline_failure=False):
    from app.simulation.openttd.proof.harness import manifest, write_json

    directory, destination, value = frozen
    destination.mkdir()
    native = dict(
        status=status,
        launches=1,
        connections=1,
        requests_sent=1,
        preparation=str(directory),
        attempt_id=value["attempt_id"],
        states=["COMPLETED"] if status == "REAL_SUCCESS" else ["FAILED"],
        qualified_for_planning=status == "REAL_SUCCESS",
        retries=0,
        reconnects=0,
    )
    write_json(destination / "proof-evidence.json", native)
    if offline_failure:
        write_json(
            destination / "production-observation.json",
            dict(
                complete=True,
                qualified_for_planning=True,
            ),
        )
        write_json(
            destination / "process-lifecycle.json",
            dict(
                cleanup_error=[],
                remaining_processes=[],
                credential_removed=True,
                postrun_integrity_verified=True,
                reaped=True,
                sockets_closed=True,
                workspace_disposed=True,
            ),
        )
        write_json(destination / "source-freeze-post.json", dict(unchanged=True))
        analysis = destination.with_name(destination.name + "-postrun-verification")
        analysis.mkdir()
        suites = {}
        for name in ("focused", "ordinary"):
            suites[name] = dict(tests="1", failures="1", errors="0", skipped="0")
            (analysis / f"{name}.xml").write_text(
                '<testsuites><testsuite tests="1" failures="1" errors="0" skipped="0"/>'
                "</testsuites>"
            )
        write_json(
            analysis / "verification.json",
            dict(
                native_status=status,
                native_lifecycle="COMPLETED",
                final_acceptance="FAILED_POSTRUN_VERIFICATION",
                terminal_reason="controlled offline failure",
                integrity={"integrity": "PASS"},
                tests=suites,
            ),
        )
        (analysis / "final-report.md").write_text(
            "Controlled mandatory offline verification FAILED.\n"
        )
        (analysis / "artifact-manifest.sha256").write_text(manifest(analysis))
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    lineage.retain_attempt_identity(destination, metadata, native)
    (destination / "artifact-manifest.sha256").write_text(manifest(destination))


@pytest.fixture
def controlled_history(tmp_path):
    from app.simulation.openttd.proof.world_attempt import record_prelaunch_failure

    first = controlled_freeze(tmp_path, 1, 1)
    controlled_consume(first, "REAL_FAILED")
    second = controlled_freeze(tmp_path, 2, 2)
    controlled_consume(second, "REAL_SUCCESS", offline_failure=True)
    third = controlled_freeze(tmp_path, 3, 3)
    record_prelaunch_failure(
        third[0], ValueError("Controlled post-consumption test contract failure")
    )
    return controlled_freeze(tmp_path, 4, 3)


@pytest.mark.parametrize("number", [1, 2])
def test_consumed_attempt_historical_identity(number):
    value = lineage.validate_historical_attempt(
        freeze(number), ROOT / f"{PREFIX}-real-attempt{number}"
    )
    assert value.freeze_revision == number
    assert value.launches == value.connections == 1
    assert value.classification == "RUNTIME"


@pytest.mark.parametrize("number", [1, 2])
def test_consumed_destination_rejected_for_execution(number):
    directory = freeze(number)
    value = json.loads((directory / "attempt-lineage.json").read_text())
    with pytest.raises(ValueError):
        lineage.validate_lineage(directory, value, number, ROOT / value["evidence_directory"])


def test_historical_validator_never_discovers_current_history(monkeypatch):
    monkeypatch.setattr(lineage, "relevant_failures", lambda p: pytest.fail("current history read"))
    monkeypatch.setattr(lineage, "capture_lineage", lambda *a: pytest.fail("next derivation"))
    assert lineage.validate_historical_attempt(freeze(2), ROOT / f"{PREFIX}-real-attempt2")


def test_current_next_attempt_preserves_frozen_identity(controlled_history):
    directory, destination, _ = controlled_history
    path = directory.with_name(f"{PREFIX}-real-prelaunch-v2") / "attempt-lineage.json"
    before = path.read_bytes()
    value = lineage.derive_next_attempt(directory, 4, destination)
    assert value["attempt_number"] == 3
    assert value["attempt_id"] == "two-rollover-qualification-v4-native-attempt3"
    assert not value["prelaunch_continuation_exception_used"]
    assert value["fresh_explicit_authorization_required"]
    rows = value["post_launch_predecessors"]
    assert len(rows) == 2
    prelaunch = value["supersedes_prelaunch_attempts"]
    assert len(prelaunch) == 1
    assert prelaunch[0]["freeze_revision"] == 3
    assert prelaunch[0]["classification"] == "PRELAUNCH"
    assert tuple(prelaunch[0][k] for k in ("launches", "connections", "requests")) == (0, 0, 0)
    assert not destination.exists()
    row = next(r for r in rows if r["freeze_revision"] == 2)
    assert row["terminal_status"] == "FAILED_POSTRUN_VERIFICATION"
    assert row["native_terminal_status"] == "REAL_SUCCESS"
    assert row["native_lifecycle"] == "COMPLETED"
    assert row["overall_acceptance"] == "FAILED"
    assert row["offline_verification"] == "FAILED"
    assert row["qualified_for_planning"] is True
    assert row["qualification_complete"] is True
    assert path.read_bytes() == before


@pytest.mark.parametrize("destination", ["real-attempt2", "real-attempt4", "other"])
def test_next_attempt_wrong_destination_rejected(destination, controlled_history):
    with pytest.raises(ValueError):
        lineage.derive_next_attempt(
            controlled_history[0], 4, controlled_history[0].parent / f"{PREFIX}-{destination}"
        )


def test_next_attempt_requires_new_freeze(controlled_history):
    directory, destination, _ = controlled_history
    with pytest.raises(ValueError, match="Newer freeze"):
        lineage.derive_next_attempt(directory, 3, destination)


@pytest.mark.parametrize(
    "module",
    [
        "enrichment",
        "cargo_page",
        "catalog",
        "structural",
        "production",
        "raw_production",
        "qualification",
    ],
)
def test_shared_historical_seam_does_not_scan_history(module, tmp_path, monkeypatch):
    api = importlib.import_module(f"app.simulation.openttd.proof.{module}_lineage")
    destination = tmp_path / f"{api.PREFIX}-real-attempt1"
    value = api.capture_lineage(tmp_path / "freeze", 1, destination)
    destination.mkdir()
    monkeypatch.setattr(api, "relevant_failures", lambda p: pytest.fail("history discovery"))
    assert api.validate_historical_lineage(tmp_path / "freeze", value, 1, destination) == 0
    with pytest.raises(ValueError, match="consumed"):
        api.validate_lineage(tmp_path / "freeze", value, 1, destination)


def test_controlled_consumption_separates_history_and_next(tmp_path):
    from app.simulation.openttd.proof.harness import manifest, write_json

    def consume(number, value, directory):
        directory.mkdir()
        write_json(
            directory / "proof-evidence.json",
            dict(
                status="REAL_FAILED",
                launches=1,
                connections=1,
                requests_sent=number,
                preparation=str(tmp_path / f"freeze-v{number}"),
                attempt_id=value["attempt_id"],
            ),
        )
        (directory / "artifact-manifest.sha256").write_text(manifest(directory))

    frozen = []
    for number in (1, 2):
        directory = tmp_path / f"freeze-v{number}"
        directory.mkdir()
        write_json(directory / "PRELAUNCH.json", dict(mode=lineage.KIND, prelaunch_revision=number))
        destination = tmp_path / f"{PREFIX}-real-attempt{number}"
        value = lineage.derive_next_attempt(directory, number, destination)
        assert value["attempt_number"] == number
        frozen.append((directory, value, number, destination))
        consume(number, value, destination)
    for args in frozen:
        lineage.validate_historical_lineage(*args)
        with pytest.raises(ValueError, match="consumed"):
            lineage.validate_lineage(*args)
    value = lineage.derive_next_attempt(
        tmp_path / "freeze-v3", 3, tmp_path / f"{PREFIX}-real-attempt3"
    )
    assert value["attempt_number"] == 3
    assert len(value["post_launch_predecessors"]) == 2


@pytest.mark.parametrize(
    "name",
    [
        f"{PREFIX}-real-prelaunch",
        f"{PREFIX}-real-prelaunch-v2",
        f"{PREFIX}-real-attempt1",
        f"{PREFIX}-real-attempt2",
        f"{PREFIX}-real-attempt2-postrun-verification",
    ],
)
def test_retained_public_evidence_manifest_exact(name):
    from app.simulation.openttd.proof.harness import manifest

    directory = ROOT / name
    assert (directory / "artifact-manifest.sha256").read_text() == manifest(directory)


def test_offline_verdict_tamper_rejected(tmp_path):
    import shutil

    from app.simulation.openttd.proof.offline_verification import failed_offline_verification

    name = f"{PREFIX}-real-attempt2"
    copied = tmp_path / name
    analysis = copied.with_name(name + "-postrun-verification")
    shutil.copytree(ROOT / analysis.name, analysis)
    native = json.loads((ROOT / name / "proof-evidence.json").read_text())
    assert failed_offline_verification(copied, native)["overall_acceptance"] == "FAILED"
    (analysis / "verification.json").write_text("{}")
    with pytest.raises(ValueError, match="manifest"):
        failed_offline_verification(copied, native)


@pytest.mark.parametrize("status", ["REAL_FAILED", "REAL_SUCCESS"])
def test_after_attempt3_consumption_next_is_attempt4(controlled_history, status):
    directory, destination, frozen = controlled_history
    before = (directory / "attempt-lineage.json").read_bytes()
    controlled_consume(controlled_history, status)
    assert lineage.validate_historical_attempt(directory, destination).terminal_status == status
    with pytest.raises(ValueError, match="consumed"):
        lineage.validate_lineage(directory, frozen, 4, destination)
    next_value = lineage.derive_next_attempt(
        directory.with_name(f"{PREFIX}-real-prelaunch-v5"),
        5,
        destination.with_name(f"{PREFIX}-real-attempt4"),
    )
    assert next_value["attempt_number"] == 4
    assert next_value["attempt_id"] == "two-rollover-qualification-v5-native-attempt4"
    assert len(next_value["post_launch_predecessors"]) == 3
    assert len(next_value["supersedes_prelaunch_attempts"]) == 1
    row = next(r for r in next_value["post_launch_predecessors"] if r["freeze_revision"] == 4)
    assert row["post_launch_failure"] == (status == "REAL_FAILED")
    assert (directory / "attempt-lineage.json").read_bytes() == before
    assert lineage.validate_historical_attempt(directory, destination).terminal_status == status
    with pytest.raises(ValueError, match="consumed"):
        lineage.derive_next_attempt(directory.with_name("next-freeze"), 5, destination)


def test_historical_attempt3_after_consumption_never_derives_next(controlled_history, monkeypatch):
    directory, destination, _ = controlled_history
    controlled_consume(controlled_history, "REAL_SUCCESS")
    monkeypatch.setattr(
        lineage, "relevant_failures", lambda *a: pytest.fail("current history read")
    )
    monkeypatch.setattr(lineage, "derive_next_attempt", lambda *a: pytest.fail("next derivation"))
    identity = lineage.validate_historical_attempt(directory, destination)
    assert identity.proof_kind == lineage.KIND
    assert identity.freeze_revision == 4
    assert identity.evidence_directory == f"{PREFIX}-real-attempt3"
    assert identity.evidence_digest and identity.parent_attempt_ids


@pytest.mark.parametrize("module", ["qualification", "production", "raw_production"])
@pytest.mark.parametrize("status", ["REAL_FAILED", "REAL_SUCCESS"])
def test_shared_terminal_consumption_derives_new_destination(module, status, tmp_path):
    from app.simulation.openttd.proof.harness import manifest, write_json

    api = importlib.import_module(f"app.simulation.openttd.proof.{module}_lineage")
    old = tmp_path / "old-freeze"
    old.mkdir()
    write_json(old / "PRELAUNCH.json", dict(mode=api.KIND, prelaunch_revision=1))
    consumed = tmp_path / f"{api.PREFIX}-real-attempt1"
    consumed.mkdir()
    write_json(
        consumed / "proof-evidence.json",
        dict(
            status=status,
            launches=1,
            connections=1,
            requests_sent=1,
            preparation=str(old),
            states=["COMPLETED"] if status == "REAL_SUCCESS" else ["FAILED"],
        ),
    )
    (consumed / "artifact-manifest.sha256").write_text(manifest(consumed))
    value = api.capture_lineage(
        tmp_path / "new-freeze", 2, tmp_path / f"{api.PREFIX}-real-attempt2"
    )
    assert value["attempt_number"] == 2
    with pytest.raises(ValueError, match="consumed"):
        api.validate_lineage(tmp_path / "new-freeze", value, 2, consumed)


def test_v3_retained_prelaunch_failure_identity():
    directory = ROOT / f"{PREFIX}-real-prelaunch-v3-gate-failure"
    identity = lineage.read_attempt(directory)
    assert identity.classification == "PRELAUNCH"
    assert identity.freeze_revision == 3
    assert (identity.launches, identity.connections, identity.requests) == (0, 0, 0)
    assert identity.terminal_status == "PRELAUNCH_FAILED"
