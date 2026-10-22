"""Controlled read-only cloning tests; copied historical bytes grant no authority."""

import hashlib
import json
import socket
import subprocess
import zipfile
from types import SimpleNamespace

import pytest

from app.experiments import paired_source as paired


@pytest.fixture(autouse=True)
def no_native(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("offline cloning launched a process or opened an Admin connection")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


@pytest.fixture
def source(tmp_path, monkeypatch):
    copied = tmp_path / "CONTROLLED-copied-source"
    copied.mkdir()

    # Native labels exercise the parser; the evaluator double grants no runtime authority.
    def sha(data):
        return hashlib.sha256(data).hexdigest()

    def write(name, data):
        (copied / name).write_text(json.dumps(data))

    (copied / "before.sav").write_bytes(b"CONTROLLED before qualification")
    (copied / "qualified.sav").write_bytes(b"CONTROLLED qualified initial state")
    staged = {
        "openttd.cfg": b"[economy]\nmultiple_industry_per_town = true\n",
        "info.nut": b"CONTROLLED info",
        "main.nut": b"CONTROLLED main",
    }
    with zipfile.ZipFile(copied / "frozen-source.zip", "w") as archive:
        for name, data in staged.items():
            archive.writestr("staged/" + name, data)
    world = {"structural_world_digest": "a" * 64, "production_digest": "b" * 64}
    write("world-planning-observation.json", world)
    write(
        "prepared-source-links.json",
        dict(
            original_save_digest=paired.digest(copied / "before.sav"),
            post_qualification_save_digest=paired.digest(copied / "qualified.sav"),
            loaded_source_digest=None,
            runtime_digest="c" * 64,
            configuration_digest=sha(staged["openttd.cfg"]),
            bridge_digest=sha(
                b"".join(
                    n.encode() + b"\0" + staged[n] for n in sorted(staged) if n.endswith(".nut")
                )
            ),
            world_id="CONTROLLED-world",
            world_observation_digest=sha(
                json.dumps(world, sort_keys=True, separators=(",", ":")).encode()
            ),
            final_structural_digest="a" * 64,
            qualified_production_digest="b" * 64,
            evidence_kind="owned-native-save-snapshots",
        ),
    )
    write("PRELAUNCH.json", {"world": {"seed": 17}, "binary_sha256": "c" * 64})
    (copied / "PRELAUNCH.sha256").write_text(paired.digest(copied / "PRELAUNCH.json"))
    write("runtime-identity.json", {"welcome": {"seed": 17}})
    write("graphics-identity.json", {"name": "CONTROLLED-content"})
    write("planning-policy.json", {"observation": "CONTROLLED-identical"})
    write("native-save-correspondence.json", {"classification": "CONTROLLED-placeholder"})
    monkeypatch.setattr(
        paired,
        "evaluate_freight",
        lambda _: SimpleNamespace(status="verified-delivery", network_report={}),
    )
    return copied


def test_clones_share_qualified_initial_state_settings_and_policy(source, tmp_path):
    before = {name: paired.digest(source / name) for name in paired.SOURCE_FILES}
    first = paired.prepare_paired_source(source, tmp_path / "first")
    second = paired.prepare_paired_source(source, tmp_path / "second")
    assert first == second
    assert first["source_file"] == "qualified.sav"
    assert first["source_sha256"] != first["original_save_sha256"]
    for name in first["clone_files"]:
        expected = (tmp_path / "first" / "baseline" / name).read_bytes()
        assert expected == (tmp_path / "first" / "feedback" / name).read_bytes()
        assert expected == (tmp_path / "second" / "baseline" / name).read_bytes()
    assert (tmp_path / "first/baseline/source.sav").read_bytes() == (
        source / "qualified.sav"
    ).read_bytes()
    assert first["native_launches"] == first["admin_connections"] == 0
    assert "NOT_RELOADED" in first["runtime_correspondence"]
    assert first["observation_policy"]
    assert first["content_identity"]
    assert before == {name: paired.digest(source / name) for name in paired.SOURCE_FILES}


@pytest.mark.parametrize("name", ["source.sav", "settings.cfg", "bridge/main.nut"])
def test_clone_tampering_rejected_independently(source, tmp_path, name):
    output = tmp_path / "pair"
    paired.prepare_paired_source(source, output)
    (output / "feedback" / name).write_bytes(b"tampered CONTROLLED clone")
    with pytest.raises(ValueError, match="feedback clone identity mismatch"):
        paired.verify_paired_source(output)


@pytest.mark.parametrize(
    "name", ["graphics-identity.json", "planning-policy.json", "qualified.sav"]
)
def test_source_drift_rejected(source, tmp_path, name):
    output = tmp_path / "pair"
    paired.prepare_paired_source(source, output)
    (source / name).write_bytes(b"CONTROLLED drift")
    with pytest.raises(ValueError):
        paired.verify_paired_source(output)


def test_unverified_source_rejected_without_output(source, tmp_path, monkeypatch):
    monkeypatch.setattr(
        paired, "evaluate_freight", lambda _: SimpleNamespace(status="failed", network_report=None)
    )
    output = tmp_path / "pair"
    with pytest.raises(ValueError, match="independently verified"):
        paired.prepare_paired_source(source, output)
    assert not output.exists()


def test_missing_settings_provenance_cannot_create_clones(source, tmp_path):
    (source / "frozen-source.zip").unlink()
    with pytest.raises(FileNotFoundError):
        paired.prepare_paired_source(source, tmp_path / "pair")
    assert not (tmp_path / "pair").exists()


def test_source_save_identity_tampering_rejected_before_output(source, tmp_path):
    (source / "qualified.sav").write_bytes(b"CONTROLLED incorrect save")
    with pytest.raises(ValueError, match="native save identity mismatch"):
        paired.prepare_paired_source(source, tmp_path / "pair")
    assert not (tmp_path / "pair").exists()


@pytest.mark.parametrize(
    "field,value",
    [("seed", 999), ("content_identity", {}), ("observation_policy", {}), ("native_launches", 1)],
)
def test_forged_manifest_rejected(source, tmp_path, field, value):
    output = tmp_path / "pair"
    manifest = paired.prepare_paired_source(source, output)
    manifest[field] = value
    (output / "source-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="manifest differs"):
        paired.verify_paired_source(output)


def test_forged_clone_hash_and_path_traversal_rejected(source, tmp_path):
    output = tmp_path / "pair"
    manifest = paired.prepare_paired_source(source, output)
    manifest["clone_files"] = {"../../outside.sav": "0" * 64}
    (output / "source-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="manifest differs"):
        paired.verify_paired_source(output)


def test_matching_mutated_clones_and_forged_hash_cannot_rewrite_provenance(source, tmp_path):
    output = tmp_path / "pair"
    manifest = paired.prepare_paired_source(source, output)
    for variant in ("baseline", "feedback"):
        (output / variant / "source.sav").write_bytes(b"CONTROLLED forged save")
    manifest["clone_files"]["source.sav"] = paired.digest(output / "baseline/source.sav")
    (output / "source-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="manifest differs"):
        paired.verify_paired_source(output)


@pytest.mark.parametrize("kind", ["../evil.nut", "/evil.nut", "duplicate", "missing-main"])
def test_unsafe_or_incomplete_staged_archive_rejected_before_output(source, tmp_path, kind):
    path = source / "frozen-source.zip"
    with zipfile.ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    if kind == "missing-main":
        entries.pop("staged/main.nut")
    elif kind != "duplicate":
        entries["staged/" + kind] = b"CONTROLLED unsafe path"
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
        if kind == "duplicate":
            with pytest.warns(UserWarning, match="Duplicate name"):
                archive.writestr("staged/info.nut", b"CONTROLLED duplicate")
    with pytest.raises(ValueError):
        paired.prepare_paired_source(source, tmp_path / "pair")
    assert not (tmp_path / "pair").exists()
