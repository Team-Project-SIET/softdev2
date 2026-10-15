"""Controlled exact-set protection and the enrichment 489/491 scope regression."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from app.simulation.openttd.proof.historical_protection import (
    capture_protection,
    protection_digest,
    validate_protection,
)


def fixture(tmp_path):
    runtime = tmp_path / "artifacts/runtime"
    old = runtime / "old-proof"
    old.mkdir(parents=True)
    (old / "receipt.json").write_text("receipt")
    (old / "report.md").write_text("report")
    (runtime / "root-report.json").write_text("root report")
    (tmp_path / "CONTEXT.md").write_text("architecture")
    current = runtime / "prelaunch-v2"
    current.mkdir()
    return runtime, old, current


def test_exact_set_hashes_count_and_shared_authority(tmp_path):
    runtime, old, current = fixture(tmp_path)
    manifest = capture_protection(tmp_path, runtime, current, runtime / "attempt")
    assert manifest["paths"] == sorted(
        [
            "CONTEXT.md",
            "artifacts/runtime/root-report.json",
            "artifacts/runtime/old-proof/receipt.json",
            "artifacts/runtime/old-proof/report.md",
        ]
    )
    assert manifest["unique_count"] == len(set(manifest["paths"])) == 4
    assert manifest["sha256"] == protection_digest(manifest)
    assert all(
        e["sha256"] == hashlib.sha256((tmp_path / e["path"]).read_bytes()).hexdigest()
        for e in manifest["entries"]
    )
    assert validate_protection(tmp_path, manifest) == 4


@pytest.mark.parametrize("change", ["missing", "changed", "rename", "same-count-substitution"])
def test_protected_change_fails(tmp_path, change):
    runtime, old, current = fixture(tmp_path)
    manifest = capture_protection(tmp_path, runtime, current, runtime / "attempt")
    path = old / "receipt.json"
    if change == "changed":
        path.write_text("changed")
    elif change == "missing":
        path.unlink()
    else:
        path.rename(old / "replacement.json")
    with pytest.raises(ValueError, match="Historical"):
        validate_protection(tmp_path, manifest)


def test_post_freeze_failure_and_unprotected_runtime_do_not_retroactively_enter(tmp_path):
    runtime, old, current = fixture(tmp_path)
    manifest = capture_protection(tmp_path, runtime, current, runtime / "attempt")
    failure = runtime / "prelaunch-gate-failure"
    failure.mkdir()
    (failure / "report.md").write_text("new failure")
    (runtime / "transient.tmp").write_text("not captured")
    (current / "logs").mkdir()
    (current / "logs/stdout.log").write_text("transient")
    assert validate_protection(tmp_path, manifest) == 4
    next_freeze = runtime / "prelaunch-v3"
    next_freeze.mkdir()
    newer = capture_protection(tmp_path, runtime, next_freeze, runtime / "attempt")
    assert "artifacts/runtime/prelaunch-gate-failure/report.md" in newer["paths"]


def test_pre_freeze_artifact_is_required_and_new_file_in_captured_root_fails(tmp_path):
    runtime, old, current = fixture(tmp_path)
    (old / "prior-failure.md").write_text("legitimate history")
    manifest = capture_protection(tmp_path, runtime, current, runtime / "attempt")
    assert "artifacts/runtime/old-proof/prior-failure.md" in manifest["paths"]
    (old / "extra.json").write_text("substitution must not pass")
    with pytest.raises(ValueError, match="path set"):
        validate_protection(tmp_path, manifest)


@pytest.mark.parametrize("change", ["duplicate", "count", "paths", "digest"])
def test_manifest_internal_accounting_rejects_tamper(tmp_path, change):
    runtime, old, current = fixture(tmp_path)
    manifest = capture_protection(tmp_path, runtime, current, runtime / "attempt")
    bad = copy.deepcopy(manifest)
    if change == "duplicate":
        bad["entries"][-1] = bad["entries"][0]
    elif change == "count":
        bad["unique_count"] += 1
    elif change == "paths":
        bad["paths"].pop()
    else:
        bad["sha256"] = "0" * 64
    if change != "digest":
        bad["sha256"] = protection_digest(bad)
    with pytest.raises(ValueError, match="Historical"):
        validate_protection(tmp_path, bad)


def test_489_491_reproduction_and_corrected_fixture(tmp_path):
    runtime, old, current = fixture(tmp_path)
    for i in range(487):
        (old / f"evidence-{i}.json").write_text(str(i))
    from app.simulation.openttd.proof.preflight import historical_snapshot

    legacy = historical_snapshot(runtime, current)
    assert sum(len(rows) for rows in legacy.values()) == 489
    with pytest.raises(AssertionError):
        assert sum(len(rows) for rows in legacy.values()) == 491
    repaired = capture_protection(tmp_path, runtime, current, runtime / "attempt")
    legacy_paths = {f"artifacts/runtime/{n}/{p}" for n, rows in legacy.items() for p in rows}
    assert set(repaired["paths"]) - legacy_paths == {
        "CONTEXT.md",
        "artifacts/runtime/root-report.json",
    }
    assert validate_protection(tmp_path, repaired) == 491


def test_future_attempt_and_private_credentials_excluded(tmp_path):
    runtime, old, current = fixture(tmp_path)
    future = runtime / "attempt"
    future.mkdir()
    (future / "partial.json").write_text("not history")
    from app.simulation.openttd.admin_crypto import AuthorizedKey

    key = AuthorizedKey.generate()
    (old / ".admin-secret").write_bytes(key._secret)
    manifest = capture_protection(tmp_path, runtime, current, future)
    assert all(".admin-secret" not in p and "/attempt/" not in p for p in manifest["paths"])
    assert "private credential" not in json.dumps(manifest)
    assert key._secret.hex() not in json.dumps(manifest)
    assert manifest["credential_identities"][0]["public_key"] == key.public_hex
    (old / ".admin-secret").write_bytes(AuthorizedKey.generate()._secret)
    with pytest.raises(ValueError, match="credential identity"):
        validate_protection(tmp_path, manifest)


def test_production_preparation_and_gate_share_protected_authority(tmp_path):
    from test_industry_enrichment import make_prepared

    from app.simulation.openttd.proof.preflight import validate_native_inputs

    history = tmp_path / "old-proof"
    history.mkdir()
    report = history / "final-report.md"
    report.write_text("preserve")
    context = Path("CONTEXT.md").read_bytes()
    prepared = make_prepared(tmp_path)
    try:
        manifest = json.loads((prepared.directory / "historical-integrity.json").read_text())
        assert (
            validate_native_inputs(prepared)["protected_unique_count"] == manifest["unique_count"]
        )
        assert report.read_text() == "preserve"
        assert Path("CONTEXT.md").read_bytes() == context
        report.write_text("changed")
        with pytest.raises(ValueError, match="Historical"):
            validate_native_inputs(prepared)
    finally:
        prepared.dispose()


def test_public_loader_accepts_current_enrichment_revision(tmp_path, monkeypatch):
    from test_industry_enrichment import make_prepared

    from app.simulation.openttd.proof import native

    prepared = make_prepared(tmp_path)
    try:
        monkeypatch.setattr(native, "BINARY", prepared.spec.identity.executable)
        monkeypatch.setattr(native, "BINARY_SHA256", prepared.spec.identity.sha256)
        loaded = native.load_prepared(prepared.directory, mode="industry-enrichment")
        assert loaded.directory == prepared.directory
        assert loaded.request == prepared.request
    finally:
        prepared.dispose()
