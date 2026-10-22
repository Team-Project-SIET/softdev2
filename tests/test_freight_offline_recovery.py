"""Derived finalization binds originals without rewriting failed native history."""

import json
import zipfile

import pytest

from app.simulation.openttd import freight_continuous as continuous
from app.simulation.openttd.proof.harness import manifest, sha256, write_json
from app.simulation.openttd.scenario_capital import company_policy_provenance


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "original"
    root.mkdir()
    financing = dict(
        policy_version=1,
        policy_company=0,
        autorenew_set=True,
        autorenew_enabled=False,
        independently_verified=True,
    )
    for name in ("before", "qualified", "after"):
        (root / f"{name}.sav").write_bytes(name.encode())
    write_json(root / "scenario-capital.json", financing)
    write_json(root / "company-policy.json", company_policy_provenance(root, financing))
    archive = root / "frozen-source.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("staged/openttd.cfg", b"frozen config")
    import hashlib

    write_json(
        root / "PRELAUNCH.json",
        dict(
            continuous_years=5,
            workspace="/disposed/world",
            predecessor=dict(executor_source_digest=sha256(archive)),
            frozen={"/disposed/world/openttd.cfg": hashlib.sha256(b"frozen config").hexdigest()},
        ),
    )
    (root / "PRELAUNCH.sha256").write_text(sha256(root / "PRELAUNCH.json") + "\n")
    write_json(
        root / "result.json",
        dict(
            status="FAILED",
            error="FileExistsError: [Errno 17] File exists: '"
            + str(root / "company-policy.json")
            + "'",
        ),
    )
    (root / "artifact-manifest.sha256").write_text(manifest(root))
    return root


def test_derived_recovery_immutable_original_and_finalization(source, tmp_path, monkeypatch):
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    # This test targets immutable metadata; complete replay is deliberately a separate seam.
    monkeypatch.setattr(continuous, "verify_continuous_evidence", lambda *a, **kw: kw)
    output = tmp_path / "derived"
    continuous.recover_continuous_evidence(source, output)
    recovered = continuous.verify_recovery_metadata(source, output)
    assert recovered["original_terminal"]["status"] == "FAILED"
    assert set(recovered["company_policy_final"]["saves"]) == {"before", "qualified", "after"}
    assert before == {p.name: p.read_bytes() for p in source.iterdir()}
    with pytest.raises(FileExistsError):
        continuous.recover_continuous_evidence(source, output)
    with pytest.raises(ValueError, match="separate"):
        continuous.recover_continuous_evidence(source, source / "derived")
    (output / "derived-finalization.json").write_text("{}")
    with pytest.raises(ValueError, match="integrity"):
        continuous.verify_recovery_metadata(source, output)
    (output / "derived-finalization.sha256").write_text(
        sha256(output / "derived-finalization.json")
    )
    with pytest.raises(ValueError, match="differs from original"):
        continuous.verify_recovery_metadata(source, output)


def test_recovery_refuses_original_tamper(source):
    (source / "before.sav").write_bytes(b"changed")
    with pytest.raises(ValueError, match="manifest"):
        continuous._recovery_metadata(source)


def test_recovery_refuses_other_failure(source):
    write_json(source / "result-new.json", {})
    (source / "result.json").write_text(json.dumps(dict(status="FAILED", error="timeout")))
    (source / "artifact-manifest.sha256").write_text(manifest(source))
    with pytest.raises(ValueError, match="exact immutable"):
        continuous._recovery_metadata(source)


def test_recovery_cannot_recreate_missing_native_save(source):
    (source / "after.sav").unlink()
    (source / "artifact-manifest.sha256").write_text(manifest(source))
    with pytest.raises(FileNotFoundError):
        continuous._recovery_metadata(source)


def test_recovery_refuses_staged_source_hash_mismatch(source):
    metadata = json.loads((source / "PRELAUNCH.json").read_bytes())
    metadata["frozen"]["/disposed/world/openttd.cfg"] = "0" * 64
    (source / "PRELAUNCH.json").write_text(json.dumps(metadata))
    (source / "PRELAUNCH.sha256").write_text(sha256(source / "PRELAUNCH.json"))
    (source / "artifact-manifest.sha256").write_text(manifest(source))
    with pytest.raises(ValueError, match="source member"):
        continuous._recovery_metadata(source)
