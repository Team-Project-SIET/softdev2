"""Historical provenance must survive relocation of disposable proof workspaces."""

import shutil

import pytest

from app.simulation.openttd.proof.historical_protection import (
    capture_protection,
    explicit_protection_base,
    protection_digest,
    validate_protection,
)


def test_captured_repository_base_survives_external_workspace(tmp_path):
    project = tmp_path / "project"
    runtime = project / "artifacts/runtime"
    protected = runtime / "protected"
    protected.mkdir(parents=True)
    (protected / "proof.json").write_bytes(b"original protected proof")
    history = capture_protection(project, runtime, runtime / "candidate", runtime / "attempt")
    history["provenance_base"] = str(project)
    history["sha256"] = protection_digest(history)
    disposable = tmp_path / "disposable"
    disposable.mkdir()
    assert validate_protection(project, history) == 1
    # The old inferred base reproduces the exact wrong-root failure.
    assert validate_protection(explicit_protection_base(history, project), history) == 1


@pytest.fixture
def captured(tmp_path):
    project = tmp_path / "trusted-project"
    runtime = project / "artifacts/runtime"
    protected = runtime / "protected"
    protected.mkdir(parents=True)
    path = protected / "proof.json"
    path.write_bytes(b"immutable historical evidence")
    value = capture_protection(project, runtime, runtime / "candidate", runtime / "attempt")
    value["provenance_base"] = str(project)
    value["sha256"] = protection_digest(value)
    return project, path, value


def test_explicit_fixture_root_is_cwd_and_cleanup_independent(captured, tmp_path, monkeypatch):
    project, _, value = captured
    disposable = tmp_path / "candidate"
    disposable.mkdir()
    shutil.rmtree(disposable)
    monkeypatch.chdir(tmp_path)
    root = explicit_protection_base(value, project)
    assert root == project
    assert validate_protection(root, value) == value["unique_count"] == 1


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "modified",
        "wrong_root",
        "traversal",
        "symlink",
        "root_symlink",
        "ambiguous",
        "no_base",
        "relative_base",
    ],
)
def test_explicit_historical_root_rejects_substitution(captured, tmp_path, change):
    project, path, value = captured
    trusted = project
    if change == "missing":
        path.unlink()
    elif change == "modified":
        path.write_bytes(b"changed")
    elif change == "wrong_root":
        trusted = tmp_path / "other-project"
        trusted.mkdir()
    elif change == "traversal":
        value["roots"] = ["../other-project"]
    elif change == "symlink":
        external = tmp_path / "replacement"
        external.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(external)
    elif change == "root_symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(project, target_is_directory=True)
        value["provenance_base"] = str(alias)
    elif change == "ambiguous":
        value["provenance_base"] = [str(project), str(tmp_path)]
    elif change == "no_base":
        del value["provenance_base"]
    else:
        value["provenance_base"] = "trusted-project"
    value["sha256"] = protection_digest(value)
    with pytest.raises(ValueError):
        validate_protection(explicit_protection_base(value, trusted), value)
