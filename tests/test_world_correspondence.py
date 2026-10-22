"""Fail-closed world correspondence policy tests (Task D).

Offline only: the retained Seed 17 records are verified read-only; verdict
machinery runs on computed inputs. No OpenTTD launch, no AdminPort connection
and no claim consumption happens in this module.
"""

import shutil
from pathlib import Path

import pytest

from app.simulation.openttd.proof import world_correspondence as wc

RETAINED_RUN = Path("artifacts/demos/playable-demo-698799a2dfb146948fd2983ff2032253")

RETAINED_PRESENT = all(
    (RETAINED_RUN / name).is_file()
    for name in ("native-save-correspondence.json", "before.sav", "network-facts-0.json")
)

pytestmark = pytest.mark.skipif(
    not RETAINED_PRESENT,
    reason="retained Seed 17 records are not materialized in this checkout",
)


def test_retained_save_binding_verifies_and_binds_the_frozen_save():
    binding = wc.retained_save_binding()
    assert binding["role"] == "SOURCE_SAVE"
    assert binding["save"] == "before.sav"
    assert len(binding["save_sha256"]) == 64
    assert binding["game_script_name"] == wc.SOURCE_SAVE_GS_NAME


def test_retained_save_binding_refuses_tampered_save(tmp_path, monkeypatch):
    tampered = tmp_path / "run"
    shutil.copytree(RETAINED_RUN, tampered, dirs_exist_ok=True)
    save = tampered / "before.sav"
    save.write_bytes(save.read_bytes() + b"\0")
    monkeypatch.setattr(wc, "SEED17_RUN", tampered)
    with pytest.raises(ValueError) as drift:
        wc.retained_save_binding()
    assert "digest mismatch" in str(drift.value)


def test_fallback_schedule_is_sealed_and_explicit():
    schedule = wc.same_session_schedule()
    assert schedule["mode"] == wc.SAME_SESSION_MODE
    assert schedule["facts_pages"] == 90
    assert schedule["classification_pages"] == 90
    assert schedule["session_requests"] == 180
    assert schedule["facts_response_bytes_limit"] == 103 * 508
    assert "never silently grown" in schedule["statement"]
    plan = wc.same_session_facts_plan("same-session-facts-bank")
    assert len(plan) == 90
    bands: dict[str, list[int]] = {}
    for request in plan:
        bands.setdefault(str(request.region), []).append(request.cursor)
    assert len(bands) == 2
    for band_cursors in bands.values():
        assert band_cursors == sorted(band_cursors)
        assert band_cursors[0] == 0


def test_mode_verdicts_stay_fail_closed():
    established = wc.evaluate_correspondence(
        wc.SOURCE_SAVE_MODE, bound=True, save_binding={"save": "before.sav"}
    )
    assert established["status"] == "CORRESPONDENCE_ESTABLISHED"
    partial = wc.evaluate_correspondence(wc.FRESH_GENERATION_MODE, bound=False)
    assert partial["status"] == "PARTIAL_CORRESPONDENCE"
    rejected = wc.evaluate_correspondence(
        wc.FRESH_GENERATION_MODE,
        bound=False,
        coherence_failures=((-1, "WORLD_IDENTITY_MISMATCH:seed"),),
    )
    assert rejected["status"] == "REJECTED"
    tile_drift = wc.evaluate_correspondence(
        wc.SOURCE_SAVE_MODE,
        bound=False,
        coherence_failures=((12, "HEIGHT_DIFFERS_FROM_TILE_FACT"),),
        save_binding={"save": "before.sav"},
    )
    assert tile_drift["status"] == "REJECTED"
    with pytest.raises(ValueError):
        wc.evaluate_correspondence("UNDECLARED_MODE", bound=True)


def test_source_save_without_binding_rejects():
    verdict = wc.evaluate_correspondence(wc.SOURCE_SAVE_MODE, bound=True)
    assert verdict["status"] == "REJECTED"
    assert "verified retained save binding" in verdict["statement"]


def test_missing_fresh_bank_rejects_cross_run_fusion():
    facts = wc.retained_census_facts()
    contradictions = wc.fresh_fact_contradictions(facts, ())
    assert contradictions[0] == (facts.tiles[0].tile_id, "FRESH_FACT_MISSING")
    assert contradictions[-1] == (-1, "FRESH_FACT_SURPLUS")
    verdict = wc.evaluate_correspondence(
        wc.SAME_SESSION_MODE, bound=True, fresh_contradictions=contradictions
    )
    assert verdict["status"] == "REJECTED"
    assert "cross-run fusion is refused" in verdict["statement"]


def test_matching_fresh_bank_fuses_and_order_is_ignored():
    facts = wc.retained_census_facts()
    reordered = tuple(reversed(facts.tiles))
    assert wc.fresh_fact_contradictions(facts, reordered) == ()
    verdict = wc.evaluate_correspondence(wc.SAME_SESSION_MODE, bound=True)
    assert verdict["status"] == "CORRESPONDENCE_ESTABLISHED"


def test_staged_save_verification_gate(tmp_path):
    binding = wc.retained_save_binding()
    missing = tmp_path / "workspace.sav"
    with pytest.raises(ValueError):
        wc.verify_staged_source_save(binding, missing)
    shutil.copyfile(RETAINED_RUN / binding["save"], missing)
    wc.verify_staged_source_save(binding, missing)  # must pass byte-verified
    binding_bad = dict(binding, save_sha256="0" * 64)
    with pytest.raises(ValueError):
        wc.verify_staged_source_save(binding_bad, missing)
