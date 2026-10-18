"""Tile Classification V2 capture preparation tests (Task B).

Offline only: no OpenTTD launch, no AdminPort connection, no authorization
consumption. The candidate is materialized inside tmp directories; the real
prepared artifact (if present) is only verified read-only.
"""

import hashlib
import json
from pathlib import Path

import pytest

from app.simulation.openttd.proof import classification_execution as execution
from app.simulation.openttd.proof import terrain_classification_preparation as prep

CANDIDATE_FILES = (
    "CANDIDATE.json",
    "classification-requests.json",
    "receipts-required.json",
    "cleanup.json",
    "AUTHORIZATION_REQUIRED.json",
)


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    directory = tmp_path_factory.mktemp("classification-prep") / "attempt"
    return prep.prepare(directory)


def read_candidate(directory: Path) -> dict:
    return json.loads((directory / "CANDIDATE.json").read_bytes())


def rewrite_candidate(directory: Path, candidate: dict) -> None:
    (directory / "CANDIDATE.json").write_bytes(
        json.dumps(candidate, sort_keys=True, indent=2).encode()
    )


def test_prepare_materializes_a_pending_authorization_candidate(prepared):
    stored = read_candidate(prepared.directory)
    assert stored["kind"] == "tile-classification-capture"
    assert stored["state"] == "PENDING_AUTHORIZATION"
    assert stored["authorized"] is False
    assert stored["maximum_launches"] == 1
    assert stored["native_launches"] == 0
    assert stored["requests_sent"] == 0
    assert "ONE fresh operator authorization" in stored["authorization"]
    for name in CANDIDATE_FILES:
        assert (prepared.directory / name).is_file()
    plan = stored["plan"]
    assert plan["request_id"] == "seed17-tile-classification-v2"
    assert plan["region"] == [170, 171, 15, 30]
    assert plan["pages_count"] == 90 and plan["tiles"] == 450 and plan["bands"] == 2
    assert len(plan["pages"]) == 90
    assert stored["budgets"] == {
        "pages_limit": 103,
        "total_response_bytes_limit": 103 * 508,
        "requests": 90,
        "gsadmin_bytes_per_page": 508,
        "observation_seconds": 600,
        "launches": 1,
        "connections": 1,
        "retries": 0,
    }


def test_prepared_launch_command_mirrors_the_retained_seed17_prelaunch(prepared):
    stored = read_candidate(prepared.directory)
    argv = stored["launch_command_template"]["argv"]
    assert argv[0] == str(prep.BINARY)
    assert argv[1] == "-D127.0.0.1:{reserved_game_port}"
    # The fixed tail must mirror the retained Seed 17 prelaunch argv order
    # exactly (the flags that produced that world).
    assert argv[-6:] == ["-x", "-X", "-G", "17", "-g", "-dscript=4,grf=1,net=3"]
    assert stored["launch_command_template"]["binary_sha256"] == prep.BINARY_SHA256
    # Frozen correspondence: the prepared binary identity equals the retained
    # prelaunch record's binary (offline check against the retained evidence).
    prelaunch = json.loads((prep.SEED17_RUN / "PRELAUNCH.json").read_bytes())
    assert Path(argv[0]).name == Path(prelaunch["argv"][0]).name
    assert prelaunch["argv"][-6:] == argv[-6:]
    assert list(stored["launch_command_template"]["fixed_arguments"]) == argv[-6:]


def test_prepared_request_pages_match_the_deterministic_plan(prepared):
    stored = read_candidate(prepared.directory)
    plan = prep.request_plan()
    assert [hashlib.sha256(payload).hexdigest() for payload in plan] == [
        page["request_payload_sha256"] for page in stored["plan"]["pages"]
    ]
    pages = json.loads((prepared.directory / "classification-requests.json").read_bytes())
    assert pages["request_id"] == "seed17-tile-classification-v2"
    assert len(pages["pages"]) == 90
    assert all(len(page["request"].encode()) <= 159 for page in pages["pages"])
    # Every request binds the same id and the echoing schema-2 contract.
    assert all('"schema":2' in page["request"] for page in pages["pages"])
    # The composed package carries the exact six-field request gate.
    composed = classification_package_source()
    assert "request.len()!=6" in composed


def classification_package_source() -> str:
    from app.simulation.openttd.terrain_classification_bridge import (
        classification_package_bytes,
    )

    return classification_package_bytes()["main.nut"].decode()


def test_prepared_receipts_and_cleanup_requirements(prepared):
    stored = read_candidate(prepared.directory)
    assert len(stored["receipts_required"]) == 5
    assert any("coherence" in statement for statement in stored["receipts_required"])
    cleanup = json.loads((prepared.directory / "cleanup.json").read_bytes())
    assert cleanup["steps"] == stored["cleanup"]
    assert all(isinstance(step, str) for step in cleanup["steps"])
    authorization = json.loads((prepared.directory / "AUTHORIZATION_REQUIRED.json").read_bytes())
    assert authorization["state"] == "PENDING_AUTHORIZATION"
    assert authorization["launch_command_template"] == stored["launch_command_template"]


def test_preflight_reverifies_every_frozen_seam(prepared):
    stored = prepared.preflight()
    assert stored["state"] == "PENDING_AUTHORIZATION"
    assert prepared.package_digest == read_candidate(prepared.directory)["package"]["digest"]


def test_preflight_refuses_tampered_candidates(prepared):
    original = read_candidate(prepared.directory)
    rewrite_candidate(prepared.directory, {**original, "authorized": True})
    try:
        with pytest.raises(ValueError):
            prepared.candidate
    finally:
        rewrite_candidate(prepared.directory, original)
    for tampered in (
        {**original, "state": "AUTHORIZED"},
        {**original, "attempt_identity": "0" * 64},
        {**original, "native_launches": 1},
    ):
        rewrite_candidate(prepared.directory, tampered)
        try:
            with pytest.raises((ValueError, PermissionError)):
                prepared.preflight()
        finally:
            rewrite_candidate(prepared.directory, original)
    assert prepared.preflight()["state"] == "PENDING_AUTHORIZATION"


def test_preflight_refuses_drifted_frozen_source_or_plan(prepared):
    original = read_candidate(prepared.directory)
    # A drifted frozen-source digest stops the preflight outright.
    drifted = dict(original)
    drifted["frozen_source"] = dict(original["frozen_source"])
    some_path = next(iter(drifted["frozen_source"]))
    drifted["frozen_source"][some_path] = "0" * 64
    rewrite_candidate(prepared.directory, drifted)
    try:
        with pytest.raises(ValueError):
            prepared.preflight()
    finally:
        rewrite_candidate(prepared.directory, original)
    # A drifted package digest means the staged composition moved.
    rewrite_candidate(
        prepared.directory, {**original, "package": {**original["package"], "digest": "9" * 64}}
    )
    try:
        with pytest.raises(ValueError) as drifted_package:
            prepared.preflight()
        assert "composition drifted" in str(drifted_package.value)
    finally:
        rewrite_candidate(prepared.directory, original)
    # A drifted per-page request digest means the plan moved.
    pages = [dict(page) for page in original["plan"]["pages"]]
    pages[0] = {**pages[0], "request_payload_sha256": "0" * 64}
    drifted_plan = {**original, "plan": {**original["plan"], "pages": pages}}
    rewrite_candidate(prepared.directory, drifted_plan)
    try:
        with pytest.raises(ValueError) as drifted_plan_error:
            prepared.preflight()
        assert "request plan drifted" in str(drifted_plan_error.value)
    finally:
        rewrite_candidate(prepared.directory, original)
    assert prepared.preflight()["plan"]["pages_count"] == 90


def test_preparation_refuses_a_malformed_staged_handler(tmp_path, monkeypatch):
    """A handler missing a required composition seam fails preparation."""
    import app.simulation.openttd.terrain_classification_bridge as bridge

    handler = (
        "function TileClassificationPage(request) {\n"
        '    if (request.type != "tile_classification_page") return null;\n'
        '    if (typeof request.schema!="integer" || request.schema!=2) return null;\n'
        "    local predicates=[buildable,water,coast,tree,farm,rock,rough,"
        "road_tile,road_track,road0,rail,water_transport,airport,house,station];\n"
        "    TILE_CLASSIFICATION_READ\n"
        "}\n"
        "class NoMutationBridge extends TerrainClassificationBridge {}\n"
    )
    fake = tmp_path / "terrain_classification.nut"
    fake.write_text(handler)
    monkeypatch.setattr(bridge, "CLASSIFICATION_HANDLER_FILE", fake)
    with pytest.raises(ValueError) as invalid:
        prep.validate_staging_seams()
    assert "authority changed" in str(invalid.value) or "shape gate missing" in str(invalid.value)
    with pytest.raises(ValueError):
        prep.prepare(tmp_path / "refused")
    monkeypatch.undo()
    # The genuine composition still verifies after the refused attempt.
    assert prep.validate_staging_seams()["classification_package_digest"]


def test_preparation_requires_the_retained_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(prep, "SEED17_RUN", tmp_path / "absent")
    with pytest.raises(ValueError) as missing:
        prep.retained_facts()
    assert "retained Seed 17 evidence missing" in str(missing.value)
    with pytest.raises(ValueError) as missing_welcome:
        prep.retained_welcome()
    assert "runtime identity" in str(missing_welcome.value)


@pytest.mark.skipif(
    not any(Path("artifacts/demos").glob("classification-seed17-*/CANDIDATE.json")),
    reason="the prepared real candidate has not been materialized in this checkout",
)
def test_real_prepared_candidate_verifies_offline():
    """The frozen candidate verifies through its task-meaningful artifacts.

    The historical record freezes the pre-execution source tree it proposed to
    launch with. The execution task (Tasks A-D) extends runtime modules
    additively by design, so that byte snapshot is superseded as an induction
    target: the active binding re-derives the load-bearing artifacts (plan
    payload digests page by page, composed package digest, retained references,
    unconsumed one-shot state) while the record itself stays untouched. The
    CURRENT source tree is pinned by the execution candidate's own frozen
    inventory (see test_classification_execution).
    """
    binding = execution.source_candidate_binding()
    directory, stored = binding
    assert directory.name.startswith("classification-seed17-")
    assert stored["authorized"] is False
    assert stored["plan"]["request_id"] == "seed17-tile-classification-v2"
