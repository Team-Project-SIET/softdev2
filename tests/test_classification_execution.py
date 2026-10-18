"""Execution-candidate staging tests (Task A).

Offline only: staging happens in tmp directories; the pinned OpenTTD binary
and the OpenGFX archive are verified and copied but never launched; the
reserved endpoints are closed immediately. The frozen prepared candidate is
verified read-only through the binding re-derivation.
"""

import hashlib
import json
from pathlib import Path

import pytest

from app.simulation.openttd.proof import classification_execution as execution
from app.simulation.openttd.proof.classification_execution import (
    AI_PACKAGE_NAME,
    EXEC_KIND,
    SOURCE_SAVE_MODE,
    budgets,
    execution_argv,
    execution_package,
    load_execution,
    prepare_execution,
    save_compatible_info_bytes,
    source_candidate_binding,
    staged_ai_digest,
    staged_ai_identity,
    staged_ai_package_bytes,
    validate_execution_package,
)
from app.simulation.openttd.proof.harness import BINARY, sha256
from app.simulation.openttd.proof.world_correspondence import (
    FRESH_GENERATION_MODE,
    SOURCE_SAVE_GS_NAME,
)
from app.simulation.openttd.terrain_classification_bridge import (
    classification_package_bytes,
    classification_package_digest,
)

REAL_ARTIFACTS = Path("artifacts/demos/classification-seed17-b6fb1410")

pytestmark = pytest.mark.skipif(
    not (BINARY.is_file() and REAL_ARTIFACTS.is_dir()),
    reason="pinned OpenTTD binary or retained classification candidate missing",
)


@pytest.fixture(scope="module")
def staged(tmp_path_factory):
    return prepare_execution(tmp_path_factory.mktemp("classification-exec") / "attempt")


def read_candidate(directory: Path) -> dict:
    return json.loads((directory / "CANDIDATE.json").read_bytes())


def read_prelaunch(directory: Path) -> dict:
    return json.loads((directory / "PRELAUNCH.json").read_bytes())


def test_staged_execution_records(staged):
    candidate = read_candidate(staged.directory)
    assert candidate["kind"] == EXEC_KIND
    assert candidate["correspondence_mode"] == SOURCE_SAVE_MODE
    assert candidate["state"] == "PENDING_AUTHORIZATION"
    assert candidate["authorized"] is False
    assert candidate["native_launches"] == 0
    assert candidate["requests_sent"] == 0
    assert candidate["maximum_launches"] == 1
    assert candidate["plan"]["pages_count"] == 90
    assert candidate["plan"]["tiles"] == 450
    assert candidate["plan"]["region"] == [170, 171, 15, 30]
    assert candidate["plan"]["bands"] == [[170, 171, 15, 17], [170, 188, 15, 13]]
    metadata = read_prelaunch(staged.directory)
    assert metadata["attempt_identity"] == staged.attempt_identity
    argv = metadata["argv"]
    assert argv[0] == str(BINARY)
    assert argv[1].startswith("-D127.0.0.1:")
    assert argv[-1] == "-dscript=4,grf=1,net=3"
    assert "-G" not in argv  # the retained save is loaded, never a fresh seed
    index = argv.index("-g")
    assert argv[index + 1].endswith("source.sav")
    assert "isolated" in argv[index + 1]
    assert metadata["world"] == dict(seed=17, width=256, height=256, source="COPIED_NATIVE_SAVE")
    assert (staged.directory / "PRELAUNCH.sha256").read_text().strip() == sha256(
        staged.directory / "PRELAUNCH.json"
    )


def test_staged_package_is_save_composition_of_frozen_main(staged):
    composed = execution_package(SOURCE_SAVE_MODE)
    frozen_main = classification_package_bytes()["main.nut"]
    assert composed["main.nut"] == frozen_main
    info = save_compatible_info_bytes().decode()
    assert info.count(f'function GetName() {{ return "{SOURCE_SAVE_GS_NAME}"; }}') == 1
    assert info.count("function GetVersion() { return 1; }") == 1
    assert info.count('function GetShortName() { return "RFP1"; }') == 1
    assert info.count('function CreateInstance() { return "NoMutationBridge"; }') == 1
    seams = validate_execution_package(SOURCE_SAVE_MODE)
    assert seams["package_digest"] == staged.package_digest
    read = read_candidate(staged.directory)
    assert read["package"]["digest"] == staged.package_digest


def test_execution_argv_shapes():
    config = Path("/tmp/never/openttd.cfg")
    save = Path("/tmp/never/source.sav")
    save_argv = execution_argv(SOURCE_SAVE_MODE, config, 42800, save)
    assert save_argv[-3:] == ("-g", str(save), "-dscript=4,grf=1,net=3")
    fresh_argv = execution_argv(FRESH_GENERATION_MODE, config, 42800)
    assert fresh_argv[-4:] == ("-G", "17", "-g", "-dscript=4,grf=1,net=3")
    with pytest.raises(ValueError):
        execution_argv(SOURCE_SAVE_MODE, config, 42800, None)


def test_sealed_budgets():
    sealed = budgets(SOURCE_SAVE_MODE)
    assert sealed["requests"] == sealed["session_requests"] == 90
    assert sealed["pages_limit"] == 103
    assert sealed["tile_facts_requests"] == 0
    assert sealed["retries"] == sealed["reconnects"] == sealed["mutations"] == 0
    assert sealed["launches"] == sealed["connections"] == 1
    assert sealed["observation_seconds"] == 600
    with pytest.raises(ValueError):
        budgets(FRESH_GENERATION_MODE)


def test_preflight_passes_and_refuses_a_written_claim(staged):
    assert staged.preflight()["argv"]
    (staged.directory / "CLAIM.json").write_text("{}\n")
    try:
        with pytest.raises(ValueError):
            staged.preflight()
    finally:
        (staged.directory / "CLAIM.json").unlink()
    assert isinstance(staged.preflight(), dict)


def test_preflight_refuses_drifted_staged_files(staged):
    metadata = staged.preflight()
    package = Path(metadata["workspace"]) / "game" / SOURCE_SAVE_GS_NAME / "main.nut"
    original = package.read_bytes()
    package.write_bytes(original + b"\n")
    try:
        with pytest.raises(ValueError):
            staged.preflight()
    finally:
        package.write_bytes(original)
    config = Path(metadata["config"])
    text = config.read_text()
    config.write_text(text.replace("terrain_type = 0\n", ""))
    try:
        with pytest.raises(ValueError):
            staged.preflight()
    finally:
        config.write_text(text)
    assert isinstance(staged.preflight(), dict)


def test_preflight_refuses_prelaunch_tamper(staged):
    seal = (staged.directory / "PRELAUNCH.sha256").read_text()
    (staged.directory / "PRELAUNCH.sha256").write_text("0" * 64 + "\n")
    try:
        with pytest.raises(ValueError):
            staged.preflight()
    finally:
        (staged.directory / "PRELAUNCH.sha256").write_text(seal)


def test_load_execution_round_trip(staged):
    loaded = load_execution(staged.directory)
    assert loaded.attempt_identity == staged.attempt_identity
    assert loaded.mode == staged.mode == SOURCE_SAVE_MODE
    assert loaded.package_digest == staged.package_digest


def test_source_candidate_binding_verifies_frozen_candidate():
    directory, stored = source_candidate_binding()
    assert stored["kind"] == "tile-classification-capture"
    assert stored["state"] == "PENDING_AUTHORIZATION"
    assert stored["authorized"] is False
    assert stored["native_launches"] == 0 and stored["requests_sent"] == 0
    assert stored["package"]["digest"] == classification_package_digest()
    assert directory.name.startswith("classification-seed17-")


def test_source_candidate_binding_refuses_drift(tmp_path, monkeypatch):
    records = sorted(Path("artifacts/demos").glob("classification-seed17-*/CANDIDATE.json"))
    assert len(records) == 1
    stored = json.loads(records[0].read_bytes())
    monkeypatch.setattr(execution, "ARTIFACT_ROOT", tmp_path)
    # 1. a drifted page digest fails closed
    drifted = tmp_path / "classification-seed17-drifted"
    drifted.mkdir()
    pages = [dict(page) for page in stored["plan"]["pages"]]
    pages[0]["request_payload_sha256"] = "0" * 64
    (drifted / "CANDIDATE.json").write_text(
        json.dumps(dict(stored, plan=dict(stored["plan"], pages=pages)))
    )
    with pytest.raises(ValueError) as drifted_plan:
        source_candidate_binding()
    assert "plan drifted" in str(drifted_plan.value)
    # 2. two candidate directories are ambiguous
    other = tmp_path / "classification-seed17-also"
    other.mkdir()
    (other / "CANDIDATE.json").write_text(json.dumps(stored))
    with pytest.raises(ValueError) as ambiguous:
        source_candidate_binding()
    assert "found 2" in str(ambiguous.value)
    other.joinpath("CANDIDATE.json").unlink()
    other.rmdir()
    # 3. a written claim means the frozen attempt is consumed
    (drifted / "CANDIDATE.json").write_text(json.dumps(stored))
    (drifted / "CLAIM.json").write_text("{}\n")
    with pytest.raises(ValueError) as claim_bad:
        source_candidate_binding()
    assert "claim" in str(claim_bad.value)


def test_staged_ai_package_restores_retained_identity(staged):
    """A SOURCE_SAVE runtime stages exactly the retained save's stored AI
    package (RoadProofCompany/version 1), and the candidate/PRELAUNCH records
    seal its identity."""
    identity = read_prelaunch(staged.directory)["ai_package"]
    package = staged_ai_package_bytes()
    assert identity["name"] == AI_PACKAGE_NAME == "RoadProofCompany"
    assert identity["digest"] == staged_ai_digest(package)
    assert identity == staged_ai_identity(package)
    assert set(identity["files"]) == {"info.nut", "main.nut"}
    candidate = read_candidate(staged.directory)
    assert candidate["ai_package"] == identity
    # The staged bytes on disk are byte-exact with the package sources.
    metadata = staged.preflight()
    ai_directory = Path(metadata["workspace"]) / "ai" / AI_PACKAGE_NAME
    for file_name, data in sorted(package.items()):
        assert (ai_directory / file_name).read_bytes() == data


def test_staged_ai_identity_matches_retained_save(staged):
    """The staged AI package carries the retained identity and its controller
    provably never dies (the dummy-AI instant death cannot recur)."""
    metadata = staged.preflight()
    ai_directory = Path(metadata["workspace"]) / "ai" / AI_PACKAGE_NAME
    info = (ai_directory / "info.nut").read_bytes().decode()
    main = (ai_directory / "main.nut").read_bytes().decode()
    assert 'function GetName() { return "RoadProofCompany"; }' in info
    assert "function GetVersion() { return 1; }" in info
    assert "class RoadProofCompany extends AIController" in main
    assert "while (true) Sleep(1)" in main


def test_preflight_refuses_drifted_staged_ai(staged):
    """A staged AI file that drifted from the sealed identity refuses the
    launch. The staged-tree freeze is the outer net (every staged byte is
    pinned); the dedicated staged-AI check behind it is defense-in-depth."""
    metadata = staged.preflight()
    ai_file = Path(metadata["workspace"]) / "ai" / AI_PACKAGE_NAME / "info.nut"
    original = ai_file.read_bytes()
    ai_file.write_bytes(original + b"\n")
    try:
        with pytest.raises(ValueError):
            staged.preflight()
    finally:
        ai_file.write_bytes(original)
    assert isinstance(staged.preflight(), dict)


def test_staged_ai_digest_convention():
    files = {"b.nut": b"two", "a.nut": b"one"}
    # Same name\\0len\\0bytes convention as the GameScript package binding.
    expected = hashlib.sha256(
        b"a.nut\0" + (3).to_bytes(8, "big") + b"one" + b"b.nut\0" + (3).to_bytes(8, "big") + b"two"
    ).hexdigest()
    assert staged_ai_digest(files) == expected


def test_missing_retained_ai_sources_fail_closed(tmp_path, monkeypatch):
    """Without the retained AI package sources, staging a SOURCE_SAVE runtime
    fails instead of staging a runtime that cannot resolve the save."""
    monkeypatch.setattr(execution, "AI_PACKAGE_PROJECT", tmp_path)
    with pytest.raises(ValueError) as missing:
        staged_ai_package_bytes()
    assert "Retained AI package source missing" in str(missing.value)


def test_ai_identity_drift_fails_staging(tmp_path, monkeypatch):
    """A staged AI package that lost the retained RoadProofCompany identity is
    refused before any runtime is built from it."""
    monkeypatch.setattr(execution, "AI_PACKAGE_PROJECT", tmp_path)
    (tmp_path / "info.nut").write_bytes(
        b'function GetName() { return "OtherCompany"; }\nfunction GetVersion() { return 1; }\n'
    )
    (tmp_path / "main.nut").write_bytes(b"class OtherCompany extends AIController {}\n")
    with pytest.raises(ValueError) as lost:
        staged_ai_package_bytes()
    assert "RoadProofCompany" in str(lost.value)
