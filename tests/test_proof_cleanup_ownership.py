"""Controlled ownership/disposal regression; no native runtime activity."""

import json
from pathlib import Path

import pytest
from test_industry_production_proof import prepared as prepared

from app.simulation.openttd.runtime.ownership import OwnershipGraph, PathClass, PathOwnership


def graph(root, entries):
    return OwnershipGraph((root,), tuple(entries))


@pytest.mark.parametrize(
    "kind",
    [PathClass.IMMUTABLE_SOURCE, PathClass.PROTECTED_HISTORICAL, PathClass.GENERATED_EVIDENCE],
)
@pytest.mark.parametrize("relative", ["", "input"])
def test_persistent_cleanup_overlap_rejected(tmp_path, kind, relative):
    root = tmp_path / "workspace"
    root.mkdir()
    with pytest.raises(ValueError, match="cleanup"):
        graph(root, [PathOwnership(root / relative, kind)]).validate()


def test_duplicate_classification_rejected(tmp_path):
    source = tmp_path / "source"
    with pytest.raises(ValueError, match="ambiguous"):
        graph(
            tmp_path / "workspace",
            [
                PathOwnership(source, PathClass.IMMUTABLE_SOURCE),
                PathOwnership(source, PathClass.RUNTIME_EPHEMERAL),
            ],
        ).validate()


def test_symlink_alias_rejected(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "input").write_text("data")
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError):
        graph(root, [PathOwnership(alias / "input", PathClass.IMMUTABLE_SOURCE)]).validate()


def test_hardlink_alias_rejected(tmp_path):
    import os

    root = tmp_path / "workspace"
    root.mkdir()
    source = tmp_path / "source"
    source.write_text("data")
    copy = root / "copy"
    os.link(source, copy)
    with pytest.raises(ValueError, match="alias"):
        graph(
            root,
            [
                PathOwnership(source, PathClass.IMMUTABLE_SOURCE),
                PathOwnership(copy, PathClass.RUNTIME_EPHEMERAL),
            ],
        ).validate()


def test_owned_ephemeral_copy_deletion_preserves_source_and_evidence(tmp_path):
    from app.simulation.openttd.runtime.config import RuntimeWorkspace

    source = tmp_path / "canonical"
    source.write_text("immutable")
    evidence = tmp_path / "evidence"
    evidence.write_text("retained")
    workspace = RuntimeWorkspace.create(tmp_path / "isolated", retain=True)
    copy = workspace.root / "copy"
    copy.write_bytes(source.read_bytes())
    credential = workspace.root / ".admin-secret"
    credential.write_bytes(b"private bytes")
    credential.chmod(0o600)
    policy = graph(
        workspace.root,
        [
            PathOwnership(source, PathClass.IMMUTABLE_SOURCE),
            PathOwnership(evidence, PathClass.GENERATED_EVIDENCE),
            PathOwnership(copy, PathClass.RUNTIME_EPHEMERAL),
            PathOwnership(credential, PathClass.RUNTIME_CREDENTIAL),
        ],
    )
    policy.validate()
    reopened = RuntimeWorkspace.reopen(workspace.root)
    reopened.close(ownership=policy)
    assert not copy.exists() and not credential.exists() and not workspace.root.exists()
    assert source.read_text() == "immutable" and evidence.read_text() == "retained"


def test_recursive_cleanup_symlink_rejected(tmp_path):
    from app.simulation.openttd.runtime.config import RuntimeWorkspace

    workspace = RuntimeWorkspace.create(tmp_path / "isolated", retain=True)
    source = tmp_path / "source"
    source.write_text("immutable")
    (workspace.root / "escape").symlink_to(source)
    with pytest.raises(ValueError, match="symlink"):
        RuntimeWorkspace.reopen(workspace.root).close()
    assert source.read_text() == "immutable"


def test_historical_deleted_paths_are_all_owned_materializations():
    from app.simulation.openttd.proof.harness import PROJECT

    directory = PROJECT / "artifacts/runtime/openttd-15.3-industry-production-real-prelaunch-v2"
    meta = json.loads((directory / "PRELAUNCH.json").read_text())
    missing = json.loads(
        (
            directory.with_name(
                "openttd-15.3-industry-production-real-attempt1-postrun-verification"
            )
            / "missing-frozen-inputs.json"
        ).read_text()
    )
    root = Path(meta["workspace"])
    frozen = json.loads((directory / "source-freeze.json").read_text())
    assert len(missing) == 16
    for path, identity in missing.items():
        assert Path(path).is_relative_to(root) and frozen[path] == identity["expected"]
        with pytest.raises(ValueError, match="cleanup"):
            graph(root, [PathOwnership(Path(path), PathClass.IMMUTABLE_SOURCE)]).validate()
        graph(root, [PathOwnership(Path(path), PathClass.RUNTIME_EPHEMERAL)]).validate()


def test_real_preparation_disposal_reconciles_all_materializations(prepared):
    import hashlib

    from app.simulation.openttd.proof.harness import verify_freeze
    from app.simulation.openttd.proof.ownership import dispose_and_verify, validate_ownership

    frozen = json.loads((prepared.directory / "source-freeze.json").read_text())
    materializations = json.loads(
        (prepared.directory / "runtime-materializations.json").read_text()
    )
    validate_ownership(prepared, frozen)
    assert all(not Path(p).is_relative_to(prepared.spec.workspace.root) for p in frozen)
    assert all(row["path"] not in frozen for row in materializations["entries"])
    for row in materializations["entries"]:
        if row["derivation"] in ("byte-copy", "generated-template-copy"):
            assert (
                hashlib.sha256(Path(row["canonical_source"]).read_bytes()).hexdigest()
                == row["sha256"]
            )
    secret = prepared.key_path.read_bytes()
    assert prepared.key_path.stat().st_mode & 0o777 == 0o600
    assert all(
        secret not in p.read_bytes() and secret.hex().encode() not in p.read_bytes()
        for p in prepared.directory.rglob("*")
        if p.is_file() and p != prepared.key_path
    )
    result = dispose_and_verify(prepared, frozen)
    assert all(result.values()) and not prepared.spec.workspace.root.exists()
    verify_freeze(frozen)
    assert (prepared.directory / "materialization-inputs/openttd.cfg").exists()
    assert (prepared.directory / "materialization-inputs/private.cfg").exists()


@pytest.mark.parametrize(
    "mode",
    [
        "ack",
        "world-info",
        "industry-page",
        "industry-inventory",
        "industry-cargo",
        "industry-enrichment",
        "cargo-page",
        "cargo-catalog",
        "structural-world",
    ],
)
def test_shared_freeze_has_no_disposable_persistent_paths(
    tmp_path, checkpoint_structural_bridge, monkeypatch, mode
):
    import hashlib

    from test_real_ack_graphics import graphics_archive

    from app.simulation.openttd.proof.harness import prepare_proof
    from app.simulation.openttd.proof.ownership import dispose_and_verify

    binary = tmp_path / "binary"
    binary.write_bytes(b"controlled")
    binary.chmod(0o700)
    archive = tmp_path / "graphics.zip"
    digest = graphics_archive(archive)
    if mode in ("industry-inventory", "industry-cargo", "industry-enrichment"):
        from app.simulation.openttd import gamescript_bridge

        name = (
            "industry_inventory_checkpoint_bridge"
            if mode == "industry-inventory"
            else "industry_capability_checkpoint_bridge"
        )
        monkeypatch.setattr(gamescript_bridge, "BRIDGE_DIRECTORY", Path("tests/fixtures") / name)
    value = prepare_proof(
        tmp_path / "prelaunch",
        mode=mode,
        binary=binary,
        binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        graphics=archive,
        graphics_sha256=digest,
    )
    frozen = json.loads((value.directory / "source-freeze.json").read_text())
    assert not any(Path(p).is_relative_to(value.spec.workspace.root) for p in frozen)
    dispose_and_verify(value, frozen)
    assert not value.spec.workspace.root.exists()


def test_actual_attempt1_post_launch_lineage_is_immutable_failure():
    from app.simulation.openttd.proof.harness import PROJECT
    from app.simulation.openttd.proof.production_lineage import predecessor_row

    row = predecessor_row(
        PROJECT / "artifacts/runtime/openttd-15.3-industry-production-real-attempt1"
    )
    assert row["classification"] == "POST_LAUNCH_FAILURE"
    assert row["terminal_status"] == "FAILED_POSTRUN_INTEGRITY"
    assert row["native_terminal_status"] == "REAL_SUCCESS"
    assert (
        row["launches"],
        row["connections"],
        row["requests"],
        row["retries"],
        row["reconnects"],
    ) == (1, 1, 1, 0, 0)
    assert row["freeze_revision"] == 2
    assert row["postrun_report_digest"] and row["postrun_manifest_digest"]


def historical_lineage_fixture(tmp_path):
    import shutil

    from app.simulation.openttd.proof.harness import PROJECT

    for name in (
        "openttd-15.3-industry-production-real-attempt1",
        "openttd-15.3-industry-production-real-attempt1-postrun-verification",
    ):
        shutil.copytree(PROJECT / "artifacts/runtime" / name, tmp_path / name)
    return tmp_path


def test_v3_lineage_new_attempt2_not_prelaunch_exception(tmp_path):
    from app.simulation.openttd.proof.production_lineage import capture_lineage

    parent = historical_lineage_fixture(tmp_path)
    directory = parent / "openttd-15.3-industry-production-real-prelaunch-v3"
    value = capture_lineage(directory, 3, parent / "openttd-15.3-industry-production-real-attempt2")
    assert value["attempt_number"] == 2
    assert value["post_launch_predecessors"][0]["classification"] == "POST_LAUNCH_FAILURE"
    assert value["supersedes_prelaunch_attempts"] == []
    assert value["prelaunch_continuation_exception_used"] is False
    assert value["fresh_explicit_authorization_required"] is True
    with pytest.raises(ValueError, match="new attempt destination"):
        capture_lineage(directory, 3, parent / "openttd-15.3-industry-production-real-attempt1")
    with pytest.raises(ValueError, match="new attempt destination"):
        capture_lineage(
            directory, 3, parent / "openttd-15.3-industry-production-real-attempt2-override"
        )


@pytest.mark.parametrize(
    "name",
    [
        "openttd-15.3-industry-production-real-prelaunch-v2",
        "openttd-15.3-industry-production-real-attempt1",
        "openttd-15.3-industry-production-real-attempt1-postrun-verification",
    ],
)
def test_consumed_historical_public_evidence_unchanged(name):
    from app.simulation.openttd.proof.harness import PROJECT, manifest

    directory = PROJECT / "artifacts/runtime" / name
    assert (directory / "artifact-manifest.sha256").read_text() == manifest(directory)


def test_prelaunch_only_failure_does_not_consume_native_number(tmp_path):
    from app.simulation.openttd.proof.harness import manifest
    from app.simulation.openttd.proof.production_lineage import capture_lineage

    failed = tmp_path / "openttd-15.3-industry-production-prelaunch-gate-failure"
    failed.mkdir()
    (failed / "PRELAUNCH.json").write_text(
        json.dumps(dict(mode="industry-production", prelaunch_revision=2))
    )
    (failed / "PRELAUNCH-FAILURE.json").write_text(
        json.dumps(
            dict(
                state="PRELAUNCH_FAILED",
                launches=0,
                connections=0,
                requests=0,
                preparation=str(failed),
            )
        )
    )
    (failed / "artifact-manifest.sha256").write_text(manifest(failed))
    lineage = capture_lineage(
        tmp_path / "new-freeze", 3, tmp_path / "openttd-15.3-industry-production-real-attempt1"
    )
    assert lineage["attempt_number"] == 1
    assert lineage["post_launch_predecessors"] == []
    assert lineage["supersedes_prelaunch_attempts"][0]["classification"] == "PRELAUNCH"


def test_postlaunch_predecessor_cannot_be_moved_to_prelaunch_exception(tmp_path):
    from app.simulation.openttd.proof.production_lineage import (
        capture_lineage,
        digest,
        validate_lineage,
    )

    root = historical_lineage_fixture(tmp_path)
    destination = root / "openttd-15.3-industry-production-real-attempt2"
    directory = root / "openttd-15.3-industry-production-real-prelaunch-v3"
    value = capture_lineage(directory, 3, destination)
    value["supersedes_prelaunch_attempts"] = value["post_launch_predecessors"]
    value["post_launch_predecessors"] = []
    value["lineage_digest"] = digest({k: v for k, v in value.items() if k != "lineage_digest"})
    with pytest.raises(ValueError, match="prelaunch continuation"):
        validate_lineage(directory, value, 3, destination)


def test_postrun_hash_validation_observes_disposed_workspace(prepared, monkeypatch):
    from app.simulation.openttd.proof import harness
    from app.simulation.openttd.proof.ownership import dispose_and_verify

    original = harness.verify_freeze
    observed = []

    def verify(frozen):
        observed.append(not prepared.spec.workspace.root.exists())
        original(frozen)

    monkeypatch.setattr(harness, "verify_freeze", verify)
    dispose_and_verify(
        prepared, json.loads((prepared.directory / "source-freeze.json").read_text())
    )
    assert observed == [True]


def test_real_archive_materializations_match_all_sixteen_historical_roles(tmp_path):
    import hashlib

    from app.simulation.openttd.proof.harness import PROJECT, prepare_proof
    from app.simulation.openttd.proof.ownership import dispose_and_verify

    binary = tmp_path / "binary"
    binary.write_bytes(b"controlled-no-native-launch")
    binary.chmod(0o700)
    prepared = prepare_proof(
        tmp_path / "prelaunch",
        mode="industry-production",
        binary=binary,
        binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        graphics=PROJECT / "artifacts/runtime/verified-assets/opengfx-8.0-all.zip",
    )
    materializations = json.loads(
        (prepared.directory / "runtime-materializations.json").read_text()
    )["entries"]
    assert len(materializations) == 16
    assert sum(r["classification"] == "RUNTIME_COPY" for r in materializations) == 12
    assert sum(r["classification"] == "GENERATED_RUNTIME" for r in materializations) == 4
    historical = json.loads(
        (
            PROJECT
            / (
                "artifacts/runtime/"
                "openttd-15.3-industry-production-real-attempt1-postrun-verification"
            )
            / "missing-frozen-inputs.json"
        ).read_text()
    )
    old_root = Path(
        json.loads(
            (
                PROJECT
                / "artifacts/runtime/openttd-15.3-industry-production-real-prelaunch-v2"
                / "PRELAUNCH.json"
            ).read_text()
        )["workspace"]
    )
    assert {
        Path(r["path"]).relative_to(prepared.spec.workspace.root) for r in materializations
    } == {Path(p).relative_to(old_root) for p in historical}
    frozen = json.loads((prepared.directory / "source-freeze.json").read_text())
    dispose_and_verify(prepared, frozen)


@pytest.mark.parametrize("name", ["source-freeze.json", "artifact-manifest.sha256"])
def test_public_freeze_documents_mutated_during_disposal_fail_integrity(
    prepared, monkeypatch, name
):
    from app.simulation.openttd.proof.ownership import dispose_and_verify

    frozen = json.loads((prepared.directory / "source-freeze.json").read_text())
    original = type(prepared).dispose

    def tamper_after_disposal(self):
        original(self)
        path = self.directory / name
        path.write_text(path.read_text() + "\n")

    monkeypatch.setattr(type(prepared), "dispose", tamper_after_disposal)
    with pytest.raises(ValueError, match="after cleanup"):
        dispose_and_verify(prepared, frozen)
    assert not prepared.spec.workspace.root.exists()
