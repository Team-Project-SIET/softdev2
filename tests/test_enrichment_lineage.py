"""Exact immutable predecessor evidence; no native execution in these tests."""

import json
from pathlib import Path

import pytest

PREFIX = "openttd-15.3-industry-capability-enrichment-real-prelaunch"


def failure(parent, revision=3, **changes):
    preparation = parent / f"{PREFIX}-v{revision}"
    preparation.mkdir(exist_ok=True)
    (preparation / "PRELAUNCH.json").write_text(
        json.dumps({"mode": "industry-enrichment", "prelaunch_revision": revision})
    )
    path = parent / f"{preparation.name}-gate-failure"
    path.mkdir()
    record = dict(
        state="PRELAUNCH_FAILED",
        launches=0,
        connections=0,
        requests=0,
        preparation=str(preparation),
        run_invoked=False,
    )
    record.update(changes)
    (path / "PRELAUNCH-FAILURE.json").write_text(json.dumps(record))
    from app.simulation.openttd.proof.harness import manifest

    (path / "artifact-manifest.sha256").write_text(manifest(path))
    return path


def test_production_new_freeze_acknowledges_preserved_failure(tmp_path):
    from test_industry_enrichment import make_prepared

    from app.simulation.openttd.proof.preflight import validate_native_inputs

    prior = failure(tmp_path)
    prepared = make_prepared(tmp_path)
    try:
        result = validate_native_inputs(prepared)
        assert prior.exists()
        assert result.get("lineage_validated") is True
        assert result["lineage_predecessor_count"] == 1
    finally:
        prepared.dispose()


def setup_lineage(tmp_path, **changes):
    from app.simulation.openttd.proof.enrichment_lineage import capture_lineage

    old = failure(tmp_path, **changes)
    new = tmp_path / f"{PREFIX}-v4"
    new.mkdir()
    destination = tmp_path / "openttd-15.3-industry-capability-enrichment-real-attempt1"
    return old, new, destination, capture_lineage(new, 4, destination)


def test_no_previous_failure_passes(tmp_path):
    from app.simulation.openttd.proof.enrichment_lineage import capture_lineage, validate_lineage

    new = tmp_path / "prelaunch"
    new.mkdir()
    dest = tmp_path / "attempt"
    value = capture_lineage(new, 4, dest)
    assert validate_lineage(new, value, 4, dest) == 0


def test_acknowledged_preserved_prelaunch_passes(tmp_path):
    from app.simulation.openttd.proof.enrichment_lineage import validate_lineage

    old, new, dest, value = setup_lineage(tmp_path)
    before = {p.name: p.read_bytes() for p in old.iterdir()}
    assert validate_lineage(new, value, 4, dest) == 1
    assert value["supersedes_prelaunch_attempts"][0]["classification"] == "PRELAUNCH"
    assert {p.name: p.read_bytes() for p in old.iterdir()} == before


@pytest.mark.parametrize("change", ["unknown", "missing", "hash", "rename"])
def test_predecessor_evidence_changes_fail(tmp_path, change):
    from app.simulation.openttd.proof.enrichment_lineage import validate_lineage
    from app.simulation.openttd.proof.harness import manifest

    old, new, dest, value = setup_lineage(tmp_path)
    if change == "unknown":
        failure(tmp_path, revision=2)
    elif change == "missing":
        for p in old.iterdir():
            p.unlink()
        old.rmdir()
    elif change == "rename":
        old.rename(tmp_path / f"{PREFIX}-renamed-failure")
    else:
        p = old / "PRELAUNCH-FAILURE.json"
        record = json.loads(p.read_text())
        record["reason"] = "changed"
        p.write_text(json.dumps(record))
        (old / "artifact-manifest.sha256").write_text(manifest(old))
    with pytest.raises(ValueError):
        validate_lineage(new, value, 4, dest)


@pytest.mark.parametrize(
    "changes",
    [
        {"launches": 1},
        {"connections": 1},
        {"requests": 1},
        {"subprocess_created": True},
        {"attempt_executed": True},
        {"state": "REAL_FAILED"},
        {"states": ["PREPARED", "LAUNCHED", "FAILED"]},
    ],
)
def test_runtime_cannot_use_prelaunch_exception(tmp_path, changes):
    with pytest.raises(ValueError, match="Runtime failure"):
        setup_lineage(tmp_path, **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"launches": True},
        {"connections": False},
        {"requests": "0"},
        {"launches": -1},
        {"requests": None},
        {"state": "IN_PROGRESS"},
    ],
)
def test_exact_activity_counts_and_terminal_state_required(tmp_path, changes):
    with pytest.raises(ValueError):
        setup_lineage(tmp_path, **changes)


@pytest.mark.parametrize("revision", [2, 3])
def test_same_or_older_freeze_reauthorization_forbidden(tmp_path, revision):
    from app.simulation.openttd.proof.enrichment_lineage import capture_lineage

    failure(tmp_path)
    new = tmp_path / "same-freeze"
    new.mkdir()
    with pytest.raises(ValueError, match="Newer freeze"):
        capture_lineage(new, revision, tmp_path / "attempt")


def test_duplicate_and_noncanonical_predecessors_rejected(tmp_path):
    from app.simulation.openttd.proof.enrichment_lineage import (
        capture_lineage,
        digest,
        validate_lineage,
    )

    failure(tmp_path, revision=2)
    failure(tmp_path, revision=3)
    new = tmp_path / "prelaunch"
    new.mkdir()
    dest = tmp_path / "attempt"
    value = capture_lineage(new, 4, dest)
    again = capture_lineage(new, 4, dest)
    assert value == again
    ids = [r["attempt_id"] for r in value["supersedes_prelaunch_attempts"]]
    assert ids == sorted(ids)
    assert value["lineage_digest"] == digest(
        {k: v for k, v in value.items() if k != "lineage_digest"}
    )
    for rows in [
        list(reversed(value["supersedes_prelaunch_attempts"])),
        value["supersedes_prelaunch_attempts"] + value["supersedes_prelaunch_attempts"][:1],
    ]:
        bad = dict(value, supersedes_prelaunch_attempts=rows)
        bad["lineage_digest"] = digest({k: v for k, v in bad.items() if k != "lineage_digest"})
        with pytest.raises(ValueError, match="Duplicate or noncanonical"):
            validate_lineage(new, bad, 4, dest)


def test_classification_uses_evidence_not_directory_name(tmp_path):
    from app.simulation.openttd.proof.enrichment_lineage import read_attempt

    p = failure(tmp_path, launches=1)
    assert "prelaunch" in p.name
    assert read_attempt(p).classification == "RUNTIME"


def test_malformed_evidence_cannot_enter_lineage(tmp_path):
    from app.simulation.openttd.proof.enrichment_lineage import read_attempt
    from app.simulation.openttd.proof.harness import manifest

    p = failure(tmp_path)
    (p / "PRELAUNCH-FAILURE.json").write_text('{"launches":0,"launches":1}')
    (p / "artifact-manifest.sha256").write_text(manifest(p))
    with pytest.raises(ValueError):
        read_attempt(p)


def test_exact_destination_and_lineage_digest_required(tmp_path):
    from app.simulation.openttd.proof.enrichment_lineage import validate_lineage

    old, new, dest, value = setup_lineage(tmp_path)
    with pytest.raises(ValueError, match="destination"):
        validate_lineage(new, value, 4, tmp_path / "attempt1-v4")
    value["lineage_digest"] = "0" * 64
    with pytest.raises(ValueError):
        validate_lineage(new, value, 4, dest)


@pytest.mark.parametrize(
    "argument", ["--force", "--retry", "--ignore-failure", "--skip-proof-gate", "--destination"]
)
def test_cli_rejects_override_and_broad_bypass(monkeypatch, argument):
    import sys

    from app.simulation.openttd.proof import __main__ as cli

    monkeypatch.setattr(
        sys, "argv", ["proof", "preflight", "--mode", "industry-enrichment", argument]
    )
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2


def test_old_v3_revision_loader_rejected(tmp_path):
    from app.simulation.openttd.proof.native import load_prepared

    p = tmp_path / "v3"
    p.mkdir()
    (p / "PRELAUNCH.json").write_text(json.dumps({"attempt": 1, "prelaunch_revision": 3}))
    with pytest.raises(ValueError):
        load_prepared(p, mode="industry-enrichment")


def test_unknown_failure_after_freeze_fails_real_gate(tmp_path):
    from test_industry_enrichment import make_prepared

    from app.simulation.openttd.proof.preflight import validate_native_inputs

    prepared = make_prepared(tmp_path)
    try:
        failure(tmp_path)
        with pytest.raises(ValueError, match="Unknown"):
            validate_native_inputs(prepared)
    finally:
        prepared.dispose()


def test_terminal_attempt_identity_is_immutable_and_bound(tmp_path):
    from app.simulation.openttd.proof.enrichment_lineage import (
        read_attempt,
        retain_attempt_identity,
    )
    from app.simulation.openttd.proof.harness import manifest

    p = failure(tmp_path)
    meta = dict(prelaunch_revision=3, predecessor_attempt_ids=[])
    record = json.loads((p / "PRELAUNCH-FAILURE.json").read_text())
    retain_attempt_identity(p, meta, record)
    (p / "artifact-manifest.sha256").write_text(manifest(p))
    identity = read_attempt(p)
    assert identity.classification == "PRELAUNCH"
    assert len(identity.evidence_manifest_digest) == 64
    with pytest.raises(FileExistsError):
        retain_attempt_identity(p, meta, record)


@pytest.mark.parametrize(
    "changes",
    [
        {"requests_sent": 1},
        {"process_created": "false"},
        {"attempt_executed": 0},
        {"launches": 0.0},
    ],
)
def test_ambiguous_activity_claims_fail_closed(tmp_path, changes):
    with pytest.raises(ValueError):
        setup_lineage(tmp_path, **changes)


def test_process_creation_artifact_overrules_zero_counters(tmp_path):
    from app.simulation.openttd.proof.enrichment_lineage import read_attempt
    from app.simulation.openttd.proof.harness import manifest

    p = failure(tmp_path)
    (p / "process-launch.json").write_text('{"pid":1234}')
    (p / "artifact-manifest.sha256").write_text(manifest(p))
    assert read_attempt(p).classification == "RUNTIME"


def test_public_guarded_preflight_with_preserved_lineage(tmp_path, monkeypatch, capsys):
    import sys
    from unittest.mock import Mock

    from test_industry_enrichment import make_prepared

    from app.simulation.openttd.proof import __main__ as cli

    prior = failure(tmp_path)
    prepared = make_prepared(tmp_path)
    before = {p.name: p.read_bytes() for p in prior.iterdir()}
    create = Mock(side_effect=AssertionError("no subprocess"))
    connect = Mock(side_effect=AssertionError("no live connection"))
    guards = []
    monkeypatch.setattr("subprocess.Popen", create)
    monkeypatch.setattr("socket.socket.connect", connect)
    monkeypatch.setattr(sys, "addaudithook", guards.append)
    monkeypatch.setattr(cli, "load_prepared", lambda directory, mode: prepared)
    monkeypatch.setattr(cli, "EnrichmentNativeBackend", lambda **kwargs: Mock())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "proof",
            "preflight",
            "--mode",
            "industry-enrichment",
            "--directory",
            str(prepared.directory),
        ],
    )
    try:
        cli.main()
        result = json.loads(capsys.readouterr().out)
        assert result["state"] == "READY_TO_LAUNCH"
        assert result["lineage_validated"] is True
        assert result["lineage_predecessor_count"] == 1
        assert result["process_creation_blocked"] is True
        assert result["launches"] == result["connections"] == result["requests"] == 0
        assert (
            Path(result["evidence_destination"]).name
            == "openttd-15.3-industry-capability-enrichment-real-attempt1"
        )
        create.assert_not_called()
        connect.assert_not_called()
        assert {p.name: p.read_bytes() for p in prior.iterdir()} == before
        for event in ("subprocess.Popen", "socket.connect"):
            with pytest.raises(PermissionError):
                guards[0](event, ())
    finally:
        prepared.dispose()


def test_renamed_runtime_attempt_cannot_be_hidden_or_converted(tmp_path):
    from app.simulation.openttd.proof.enrichment_lineage import (
        capture_lineage,
        relevant_failures,
        retain_attempt_identity,
    )
    from app.simulation.openttd.proof.harness import manifest

    p = failure(tmp_path, launches=1)
    record = json.loads((p / "PRELAUNCH-FAILURE.json").read_text())
    retain_attempt_identity(p, dict(prelaunch_revision=3, predecessor_attempt_ids=[]), record)
    (p / "artifact-manifest.sha256").write_text(manifest(p))
    renamed = p.with_name("renamed-outside-enrichment-prefix")
    p.rename(renamed)
    assert renamed in relevant_failures(tmp_path)
    new = tmp_path / "v4"
    new.mkdir()
    with pytest.raises(ValueError, match="Runtime failure"):
        capture_lineage(new, 4, tmp_path / "attempt1")
