"""Controlled offline tests for the D4 native corridor staging contract (Seed 17).

No OpenTTD launch, no AdminPort connection, no native mutation, and no claim
on any retained artifact: staging, the pinned D3 prerequisite binding, the
sealed corridor pins, budgets, authorization payload reuse, preflight gates,
freeze drift and the never-consumed fail-closed verdicts are exercised against
explicitly controlled evidence directories only. The pinned retained D3
attempt (whose receipt-bound ``after.sav`` is the authoritative corridor
world) is read, never written, and its distinct diagnostic save is never an
acceptable substitute. The prerequisite replay re-verifies the retained
authorization under the real pinned operator anchor, so these tests
substitute no synthetic identity anywhere.
"""

import hashlib
import json
from pathlib import Path

import pytest

import app.simulation.openttd.proof.corridor_construction_native as d4
from app.simulation.openttd.corridor_construction import CorridorReadback, CorridorRequest
from app.simulation.openttd.proof import operator_authorization
from app.simulation.openttd.proof.harness import sha256
from app.simulation.openttd.proof.operator_authorization import (
    FORBIDDEN_ENV_KEYS,
    authorization_payload,
    canonical_authorization_bytes,
)
from app.simulation.openttd.proof.terrain_clearing import (
    ClearingNativeBackend,
    claim_status,
    retained_welcome,
)
from app.simulation.openttd.proof.world_correspondence import SOURCE_SAVE_GS_NAME

# Three distinct post-D3 corridor regions are certified offline: the bounded
# two-straight-run shape with one corner, the depot facility south of the
# run-A end, and the two stop/front pairs. Every number here binds the exact
# compiled derivation through d4.corridor_facts() in the facts tests; the
# constants ordered below are the same 24-tile witness path.
SCHEDULE_SPAN_BOUND = 36


@pytest.fixture(scope="module")
def staged(tmp_path_factory):
    prepared = d4.prepare_candidate(tmp_path_factory.mktemp("d4-staging") / "candidate")
    yield prepared
    prepared.spec.workspace.close()


def metadata_of(prepared) -> dict:
    return json.loads((prepared.directory / "PRELAUNCH.json").read_text())


def _restamp_prelaunch(directory):
    (directory / "PRELAUNCH.sha256").write_text(sha256(directory / "PRELAUNCH.json") + "\n")


def _add_freeze_probe(directory, source):
    """Alias one extra frozen entry to a byte-identical in-candidate copy.

    Drift tests must stay read-only against real sources: the probe copy is
    byte-identical to the reviewed module at staging time, so any later byte
    change is exactly the "frozen source changed after preparation" condition
    the freeze contract guards.
    """
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    probe = directory / "freeze-probe" / source.name
    probe.parent.mkdir(exist_ok=True)
    probe.write_bytes(source.read_bytes())
    metadata["frozen"][str(probe.resolve())] = sha256(source)
    (directory / "PRELAUNCH.json").write_text(
        json.dumps(metadata, sort_keys=True, indent=2) + "\n"
    )
    _restamp_prelaunch(directory)
    return probe


# --- staging correctness and the pinned prerequisite lineage -----------------


def test_operator_anchor_must_stay_seeded_for_prerequisite_replay():
    """The staging path re-verifies the retained D3 authorization in place."""
    anchor = operator_authorization.OPERATOR_PUBLIC_KEY_HEX
    assert anchor
    assert operator_authorization.operator_key_identity(anchor).startswith(
        "sha256-ed25519-public-key:"
    )


def test_staged_composition_carries_the_retained_save_identity(staged):
    composition, bridge, version = d4.staged_composition()
    gs = staged.spec.workspace.root / "game" / SOURCE_SAVE_GS_NAME
    assert gs.joinpath("info.nut").read_bytes() == composition["info.nut"]
    assert gs.joinpath("main.nut").read_bytes() == composition["main.nut"]
    assert bridge == "NetworkFreightProof" and version == 1
    main_text = gs.joinpath("main.nut").read_text()
    assert "class NetworkFreightProof extends D4CorridorProof" in main_text
    ai = staged.spec.workspace.root / "ai" / d4.STAGED_AI_DIRECTORY
    for name in ("info.nut", "main.nut"):
        assert sha256(ai / name) == sha256(d4.AI_PACKAGE / name)


def test_staged_candidate_binds_the_pinned_d3_prerequisite(staged):
    metadata = metadata_of(staged)
    assert metadata["schema"] == d4.D4_PRELAUNCH_SCHEMA
    assert metadata["milestone"] == d4.MILESTONE_CONSTRUCTION
    assert metadata["kind"] == d4.KIND
    assert metadata["attempt"] == d4.CORRIDOR_ATTEMPT
    save_digest = sha256(d4.PINNED_PREREQUISITE / "after.sav")
    assert save_digest == d4.PINNED_PREREQUISITE_AFTER_SAVE
    prerequisite = metadata["prerequisite"]
    assert prerequisite["schema"] == d4.D4_PREREQUISITE_SCHEMA
    assert prerequisite["attempt"] == "D3-TERRAFORMING-1"
    assert prerequisite["milestone"] == "D3-TERRAFORMING"
    assert prerequisite["directory"] == str(d4.PINNED_PREREQUISITE)
    assert prerequisite["prelaunch_sha256"] == sha256(d4.PINNED_PREREQUISITE / "PRELAUNCH.json")
    assert prerequisite["after_save_sha256"] == save_digest
    assert prerequisite["verification"].endswith("pinned authoritative after-save digest")
    world = metadata["world"]
    assert world["mode"] == "PREREQUISITE_ATTEMPT_SOURCE_SAVE_LOAD"
    assert world["retained_directory"] == str(d4.PINNED_PREREQUISITE)
    assert world["source_save"] == "after.sav"
    assert world["save_sha256"] == save_digest
    assert world["qualified_save_sha256"] is None
    assert world["expected_welcome"] == retained_welcome()
    assert metadata["game_script_identity"]["name"] == SOURCE_SAVE_GS_NAME
    assert metadata["game_script_identity"]["create_instance"] == "NetworkFreightProof"
    assert metadata["game_script_identity"]["version"] == 1
    assert metadata["bootstrap_command"] == f"start_ai {d4.STAGED_AI_DIRECTORY}"
    assert metadata["execution_command"][1:4] == [
        "-m",
        "app.simulation.openttd.proof.corridor_construction_native",
        "run",
    ]
    assert metadata["execution_command"][-1] == str(staged.directory)
    assert metadata["pin_provenance"]["manifest_verified"] is True
    assert metadata["pin_provenance"]["source"] == d4.CENSUS_DIRECTORY.name
    assert metadata["authorization"].startswith("PENDING")
    assert "no authorization file exists" in metadata["authorization"]
    assert not (set(metadata["environment_overrides"]) & FORBIDDEN_ENV_KEYS)
    assert claim_status(staged.directory) == "ABSENT"


def test_staged_plan_policy_binds_the_compiled_schedule(staged):
    plan = metadata_of(staged)["plan_policy"]
    schedule = d4.corridor_schedule()
    assert plan["schedule"] == schedule
    assert plan["plan_digest"] == d4.plan_digest_of(schedule)
    assert plan["company"] == 0
    assert plan["target_tile"] == int(schedule[0]["start"]) == 45747
    assert plan["max_cost"] == d4.MAX_CORRIDOR_COST
    assert plan["route"] == d4.route_policy()
    assert plan["prerequisite_world"]["schema"] == d4.D4_PREREQUISITE_SCHEMA


def test_staged_source_save_is_the_pinned_verified_after_world(staged):
    root = staged.spec.workspace.root
    assert sha256(root / "source.sav") == d4.PINNED_PREREQUISITE_AFTER_SAVE
    assert sha256(root / "source.sav") == sha256(d4.PINNED_PREREQUISITE / "after.sav")
    diagnostic = sha256(d4.PINNED_PREREQUISITE / "after-diagnostic.sav")
    assert diagnostic != d4.PINNED_PREREQUISITE_AFTER_SAVE
    config = root.joinpath("openttd.cfg").read_text()
    assert "[game_creation]" not in config
    assert "[game_scripts]\nRoadFreightProof = \n" in config
    assert "ai_in_multiplayer = true" in config


def test_prerequisite_binding_pins_the_verified_d3_attempt():
    binding = d4.prerequisite_binding(d4.PINNED_PREREQUISITE)
    assert binding["schema"] == d4.D4_PREREQUISITE_SCHEMA
    assert binding["role"] == "PREREQUISITE_ATTEMPT"
    assert binding["attempt"] == "D3-TERRAFORMING-1"
    assert binding["save"] == "after.sav"
    assert binding["save_sha256"] == d4.PINNED_PREREQUISITE_AFTER_SAVE
    assert binding["qualified_save_sha256"] is None
    assert binding["prelaunch_digest"] == sha256(d4.PINNED_PREREQUISITE / "PRELAUNCH.json")
    assert binding["cleared_chain_tiles"] == [45999, 49326]
    assert binding["verification"].startswith("full replay verification")


def test_staging_refuses_any_unpinned_prerequisite(tmp_path):
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    with pytest.raises(d4.CorridorStagingError, match="pinned D3"):
        d4.prepare_candidate(tmp_path / "candidate", prerequisite=unrelated)
    with pytest.raises(d4.CorridorStagingError, match="pinned D3"):
        d4.prerequisite_binding(unrelated)
    assert not (tmp_path / "candidate").exists()


def test_preflight_rehearsal_conserves_the_sealed_candidate(staged):
    prior = sha256(staged.directory / "PRELAUNCH.json")
    metadata = d4.preflight(staged)
    assert sha256(staged.directory / "PRELAUNCH.json") == prior
    assert metadata["attempt"] == d4.CORRIDOR_ATTEMPT
    assert not (staged.directory / "CLAIM.json").exists()
    assert claim_status(staged.directory) == "ABSENT"


def test_tampered_workspace_config_refuses_d4_preflight(tmp_path):
    prepared = d4.prepare_candidate(tmp_path / "candidate")
    try:
        config = prepared.spec.workspace.config
        config.write_text(config.read_text() + "# tampered\n")
        with pytest.raises(ValueError):
            d4.preflight(prepared)
    finally:
        prepared.spec.workspace.close()


def test_drifted_source_save_refuses_d4_preflight(tmp_path):
    prepared = d4.prepare_candidate(tmp_path / "candidate")
    try:
        (prepared.spec.workspace.root / "source.sav").write_bytes(b"tampered world bytes")
        with pytest.raises(ValueError):
            d4.preflight(prepared)
    finally:
        prepared.spec.workspace.close()


def test_frozen_source_drift_refuses_d4_preflight(tmp_path):
    """Post-preparation frozen drift of the D4 module itself refuses preflight."""
    prepared = d4.prepare_candidate(tmp_path / "candidate")
    try:
        probe = _add_freeze_probe(prepared.directory, Path(d4.__file__))
        probe.write_bytes(probe.read_bytes() + b"\n# modified after preparation\n")
        with pytest.raises(ValueError, match="Frozen source"):
            d4.preflight(prepared)
        assert not (prepared.directory / "CLAIM.json").exists()
    finally:
        prepared.spec.workspace.close()


def test_removed_closure_entry_refuses_d4_preflight(tmp_path):
    prepared = d4.prepare_candidate(tmp_path / "candidate")
    try:
        target = str(Path(d4.__file__).resolve())
        metadata = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
        assert target in metadata["frozen"]
        del metadata["frozen"][target]
        (prepared.directory / "PRELAUNCH.json").write_text(
            json.dumps(metadata, sort_keys=True, indent=2) + "\n"
        )
        _restamp_prelaunch(prepared.directory)
        with pytest.raises(ValueError, match="closure is not frozen"):
            d4.preflight(prepared)
        assert not (prepared.directory / "CLAIM.json").exists()
    finally:
        prepared.spec.workspace.close()


def test_seal_and_claim_gates_refuse_drifted_or_drafted_launch_boundaries(tmp_path):
    """The outermost preflight gates: a drifted seal and any existing claim."""
    prepared = d4.prepare_candidate(tmp_path / "candidate")
    try:
        directory = prepared.directory
        prelaunch = directory / "PRELAUNCH.json"
        original = prelaunch.read_bytes()
        prelaunch.write_bytes(original + b"\n# drifted after staging\n")
        with pytest.raises(ValueError, match="prelaunch seal mismatch"):
            d4.preflight(prepared)
        prelaunch.write_bytes(original)
        (directory / "CLAIM.json").write_text("{}\n")
        with pytest.raises(ValueError, match="one native attempt already consumed"):
            d4.preflight(prepared)
        (directory / "CLAIM.json").unlink()
        # The restored candidate returns to the passing gate, boundary intact.
        d4.preflight(prepared)
    finally:
        prepared.spec.workspace.close()


# --- sealed corridor facts, schedule, budgets and route scope -----------------


def test_corridor_facts_bind_the_sealed_witness_and_runs():
    facts = d4.corridor_facts()
    assert facts["corridor"] == (
        45748,
        45747,
        45746,
        45745,
        45744,
        45743,
        45999,
        46255,
        46511,
        46767,
        47023,
        47279,
        47535,
        47791,
        48047,
        48303,
        48559,
        48815,
        49071,
        49327,
        49583,
        49839,
        50095,
        50351,
    )
    corridor = facts["corridor"]
    assert len(set(corridor)) == len(corridor) == 24
    assert min(corridor) >= 0 and max(corridor) <= 0xFFFF
    witness = d4.route_policy()["witness_path"]
    assert witness == list(corridor)
    assert facts["run_a"] == [45747, 45746, 45745, 45744, 45743]
    assert facts["run_b"][0] == 45999 and facts["run_b"][-1] == 50095
    assert len(facts["run_b"]) == 17
    assert facts["corner"] == (45743, 45999)
    assert facts["stops"] == (45748, 50351)
    assert facts["fronts"] == (45747, 50095)
    assert facts["depot"] == dict(tile_id=45487, front_tile_id=45743, orientation="south")
    assert facts["width"] == 256


def test_corridor_tiles_read_post_d3_flat_cleared_ground():
    """The corridor footprint is the compiled final levelling projection."""
    corridor = d4.corridor_facts()["corridor"]
    _proposal, doc, spec = d4.compiled_levelling()
    tiles = {int(t.tile_id): t for t in doc.tiles}
    post = dict(tiles)
    for op in spec.ops:
        if op.kind == "clear":
            post[int(op.tile_id)] = post[int(op.tile_id)].model_copy(update={"tree": False})
        else:
            for shift in op.to_payload()["shifts"]:
                post[int(shift["tile"])] = post[int(shift["tile"])].model_copy(
                    update={"min_height": shift["after_min"], "slope": shift["after_slope"]}
                )
    flags = (
        "tree",
        "road",
        "water",
        "coast",
        "farm",
        "rock",
        "rough",
        "rail",
        "water_transport",
        "air_transport",
    )
    for tile in corridor:
        fact = post[tile]
        assert (fact.min_height, fact.slope) == (2, 0)
        for flag in flags:
            assert getattr(fact, flag) is False, (tile, flag)
        assert fact.buildable is True
        assert fact.industry_id is None


def test_corridor_schedule_is_the_compiled_six_ops():
    schedule = d4.corridor_schedule()
    assert [(entry["kind"], entry["index"]) for entry in schedule] == [
        ("full", 0),
        ("full", 1),
        ("road", 2),
        ("station", 3),
        ("station", 4),
        ("depot", 5),
    ]
    run_a, run_b = schedule[0], schedule[1]
    assert (run_a["start"], run_a["end"], run_a["run_len"]) == (45747, 45743, 5)
    assert tuple(run_a["tiles"]) == (45747, 45746, 45745, 45744, 45743)
    assert (run_b["start"], run_b["end"], run_b["run_len"]) == (45999, 50095, 17)
    assert run_b["tiles"][0] == 45999 and run_b["tiles"][-1] == 50095
    corner = schedule[2]
    assert (corner["start"], corner["end"], corner["run_len"]) == (45743, 45999, 2)
    assert tuple(corner["tiles"]) == (45743, 45999)
    pickup, delivery = schedule[3], schedule[4]
    assert pickup == dict(kind="station", index=3, tile=45748, front=45747, stop_role="pickup")
    assert delivery == dict(
        kind="station", index=4, tile=50351, front=50095, stop_role="delivery"
    )
    depot = schedule[5]
    assert depot == dict(
        kind="depot", index=5, tile=45487, front=45743, orientation="south"
    )
    for entry in schedule:
        if entry.get("run_len") is not None:
            assert 1 <= entry["run_len"] <= SCHEDULE_SPAN_BOUND


def test_stop_coverage_pins_bind_the_sealed_census_anchors():
    pins = d4.coverage_pins()
    pickup = next(pin for pin in pins if pin["role"] == "pickup")
    delivery = next(pin for pin in pins if pin["role"] == "delivery")
    assert (pickup["tile"], pickup["industry_id"], pickup["cargo_id"]) == (45748, 0, 1)
    assert pickup["industry_covered"] is True and pickup["producer_count"] == 1
    assert (delivery["tile"], delivery["industry_id"], delivery["cargo_id"]) == (50351, 1, 1)
    assert delivery["industry_covered"] is True
    route = d4.route_policy()
    assert route["pickup_coverage"] == pickup
    assert route["delivery_coverage"] == delivery


def test_route_policy_scope_is_pure_observation():
    route = d4.route_policy()
    corridor = d4.corridor_facts()["corridor"]
    assert route["witness_path"] == list(corridor)
    assert route["expected_pairs"] == len(corridor) - 1 == 23
    assert (route["pickup"], route["pickup_front"]) == (45748, 45747)
    assert (route["delivery"], route["delivery_front"]) == (50351, 50095)
    assert route["depot"] == 45487 and route["depot_front"] == 45743
    assert route["depot_orientation"] == "south"
    assert "pure observation" in route["statement"]
    assert "it never issues a build assertion" in route["statement"]


def test_budgets_match_the_staged_contract():
    assert d4.budgets() == {
        "launches": 1,
        "connection_attempts": 1,
        "requests": 25,
        "real_clears": 0,
        "real_raises": 0,
        "road_ops": 6,
        "gsadmin_bytes": 1450,
        "response_bytes": 640,
        "retries": 0,
        "reconnects": 0,
        "readiness_seconds": 45,
        "request_seconds": 10,
        "total_seconds": 900,
    }
    assert d4.PLANNED_CORRIDOR_REQUESTS == len(d4.corridor_schedule()) * 3 + 1 == 19
    assert d4.CORRIDOR_REQUEST_BUDGET == d4.budgets()["requests"] == 19 + 6


def test_plan_policy_carries_the_shared_scope_and_identity():
    plan = d4.plan_policy()
    assert plan["command"] == (
        "GSRoad.BuildRoadFull + GSRoad.BuildRoad + GSRoad.BuildRoadStation "
        "+ GSRoad.BuildRoadDepot"
    )
    assert "re-observe" in plan["stale_rule"]
    assert "wire contract v4" in plan["identity"]
    assert "classified CLEAR unowned flat ground" in plan["prerequisite_world"]["statement"]


# --- authorization payload, planned exchanges and wire identities -------------


def test_authorization_payload_adds_the_ordered_schedule_scope(staged):
    """The shared scalar builder gains schedule + digest keys, additively."""
    metadata = metadata_of(staged)
    seal = sha256(staged.directory / "PRELAUNCH.json")
    payload = authorization_payload(metadata, seal)
    schedule = d4.corridor_schedule()
    assert payload["milestone"] == d4.MILESTONE_CONSTRUCTION
    assert payload["attempt"] == d4.CORRIDOR_ATTEMPT
    assert payload["schema"] == d4.D4_PRELAUNCH_SCHEMA
    assert payload["target_tile"] == 45747
    assert payload["source_world"]["source_save"] == "after.sav"
    assert payload["source_world"]["save_sha256"] == d4.PINNED_PREREQUISITE_AFTER_SAVE
    assert payload["operation_schedule"] == schedule
    assert payload["plan_digest"] == d4.plan_digest_of(schedule)
    digest = hashlib.sha256(canonical_authorization_bytes(payload)).hexdigest()
    assert digest == d4.staged_authorization_payload_digest(staged.directory)


def test_planned_exchange_inventory_is_exactly_schedule_bound():
    schedule = d4.corridor_schedule()
    expected: set[str] = set()
    for position, entry in enumerate(schedule):
        expected.add(f"inspect-{position:02d}")
        expected.add(f"{entry['kind']}-{position:02d}")
        expected.add(f"confirm-{position:02d}")
    expected.add("route-00")
    assert d4._scheduled_request_ids(schedule) == expected
    assert len(expected) == d4.PLANNED_CORRIDOR_REQUESTS == 19


def test_wire_requests_map_the_planned_schedule_pins():
    """Every planned request is built by the production wire builder."""
    schedule = d4.corridor_schedule()
    seal = "a" * 64
    planned: list[CorridorRequest] = []
    for position, entry in enumerate(schedule):
        kind = entry["kind"]
        inspect_request = d4._corridor_request(
            "inspect", f"inspect-{position:02d}", seal, 0, d4.MAX_CORRIDOR_COST, entry
        )
        command_request = d4._corridor_request(
            kind, f"{kind}-{position:02d}", seal, 0, d4.MAX_CORRIDOR_COST, entry
        )
        read_request = d4._corridor_request(
            "read", f"confirm-{position:02d}", seal, 0, d4.MAX_CORRIDOR_COST, entry
        )
        for request in (inspect_request, command_request, read_request):
            assert request.company == 0 and request.max_cost == d4.MAX_CORRIDOR_COST
            assert len(request.to_bytes()) <= 512
            for field in ("start", "end", "tile", "front"):
                assert getattr(inspect_request, field) == getattr(command_request, field)
        assert inspect_request.target == kind and read_request.target == kind
        assert command_request.target is None
        planned.extend((inspect_request, command_request, read_request))
    witness = tuple(d4.route_policy()["witness_path"])
    route_request = CorridorRequest(
        op="route",
        request_id="route-00",
        plan=seal,
        company=0,
        max_cost=0,
        tiles=witness,
    )
    assert route_request.target is None
    assert tuple(route_request.tiles) == witness == d4.corridor_facts()["corridor"]
    assert route_request.plan == seal
    assert len(route_request.to_bytes()) <= 512
    planned.append(route_request)
    assert len(planned) == d4.PLANNED_CORRIDOR_REQUESTS == 19


# --- launch lineage and never-consumed behavior -------------------------------


def test_launch_marker_schema_continues_the_shared_d2_lineage():
    """The staged launch marker is the shared D2 schema re-scoped additively."""
    assert ClearingNativeBackend.launch_marker_schema == "d2-clearing-native-launch-consumed"
    assert d4.CorridorNativeBackend.launch_marker_schema == d4.D4_LAUNCH_CONSUMED_SCHEMA


def test_unconsumed_candidate_verifies_fail_closed(staged):
    """No candidate may claim a receipt before its one-shot consumption.

    The verdict must be the structured AUTHORIZATION_UNVERIFIED state, not a
    crash: a never-consumed candidate holds no result.json, request files or
    receipt, and the fail-closed claim gate answers before any deeper record
    is interpreted.
    """
    assert not (staged.directory / "CLAIM.json").exists()
    verdict = d4.verify_corridor_attempt(staged.directory)
    assert verdict == {
        "verification": "AUTHORIZATION_UNVERIFIED",
        "authorization_state": "CLAIM_ABSENT",
        "statement": (
            "the candidate was never consumed by an operator authorization; "
            "no verified receipt is possible"
        ),
    }
    assert claim_status(staged.directory) == "ABSENT"


def test_exit_status_zero_only_for_the_verified_receipt():
    assert d4.exit_status(dict(verified=True, status="NATIVE_CORRIDOR_VERIFIED")) == 0
    for status in (
        "FAILED",
        "FAILED_CLEANUP",
        "PHASE_HALTED_PREFIX_PRESERVED",
        "NOT_DISPATCHED",
    ):
        assert d4.exit_status(dict(verified=False, status=status)) == 1


# --- replay-verifier regressions over the consumed D4 attempt shape -----------
#
# Milestone D4's one consumed attempt (`D4-CORRIDOR-1`, `PHASE_HALTED_PREFIX_
# PRESERVED` with the verified op-00 prefix) preserved stopped-state evidence
# whose complete-attempt replay these tests pin: the production verifier must
# return the preserved-halt verdict for it offline, read-only, without any
# launch or claim consumption. The retained files are only ever read; the
# candidate itself (claim consumed) is never re-staged, re-run or re-authorized.

CONSUMED_D4_CANDIDATE = d4.PROJECT / "artifacts/experiments/d4-corridor-native-candidate-1"

_requires_consumed_evidence = pytest.mark.skipif(
    not (CONSUMED_D4_CANDIDATE / "corridor-00-intent.json").is_file(),
    reason="the consumed D4-CORRIDOR-1 retained evidence is not present",
)

# Every scheduled op after the prefix-preserving halt recomputes as pending;
# the verified op-00 prefix stays distinguishable from the incomplete phase.
_PENDING_AFTER_HALT = tuple(f"op-{index:02d}" for index in range(2, 6))


def _matching_admitted_intent(entry) -> d4.CorridorIntent:
    """An admitted intent whose own pins equal the staged entry's pins."""
    return d4.CorridorIntent(
        prelaunch_digest="0" * 64,
        source_save_digest="1" * 64,
        company=0,
        kind=entry["kind"],
        start=entry["start"],
        end=entry["end"],
        tile=entry.get("tile"),
        front=entry.get("front"),
        max_cost=2000,
        native_test_cost=785,
        before_digest="2" * 64,
        run_len=entry["run_len"],
    )


def test_verify_inputs_pin_contract_is_staged_entry_versus_admitted_intent():
    """The verify comparison binds admitted intents to their staged entries.

    The comparison is exactly `_pins(entry) != _pins(entry, intent=intent)`:
    the staged entry's own pins against the pins the admitted intent derives
    from its own kind. An entry-less `_pins(intent=...)` call is not a valid
    binding of this contract and must stay a TypeError.
    """
    entry = d4.corridor_schedule()[0]
    assert entry["kind"] == "full"
    intent = _matching_admitted_intent(entry)
    assert d4._pins(entry) == d4._pins(entry, intent=intent)
    drifted = intent.model_copy(update={"end": 50095})
    assert d4._pins(entry) != d4._pins(entry, intent=drifted)
    with pytest.raises(TypeError):
        d4._pins(intent=intent)


@_requires_consumed_evidence
def test_retained_readback_evidence_parses_the_json_boundary_directly():
    """Retained readback files are strict-contract JSON documents.

    The evidence boundary must parse them exactly like the intent branch (and
    the shared D2/D3 retained-file semantics): ``model_validate_json`` on the
    retained bytes. Under the strict contract a raw text feed can never
    validate — a str is no dict and the retained JSON arrays cannot
    strict-coerce into the contract fields — so the historical text-feed
    boundary silently dropped every readback evidence file it touched.
    """
    raw = (CONSUMED_D4_CANDIDATE / "corridor-00-independent.json").read_bytes()
    readback = CorridorReadback.model_validate_json(raw)
    assert readback.request_id == "confirm-00"
    assert readback.status == "READ"
    # The identical document, pretty-printed exactly like the runner wrote
    # its evidence files, parses the same way (compact or pretty whitespace
    # never changes the boundary).
    pretty = (json.dumps(json.loads(raw), indent=2, sort_keys=True) + "\n").encode()
    parsed = CorridorReadback.model_validate_json(pretty)
    assert parsed == readback
    # Document the defect mechanism itself: the historical text feed refuses.
    with pytest.raises(ValueError):
        CorridorReadback.model_validate(pretty.decode())


@_requires_consumed_evidence
def test_retained_d4_attempt_replays_as_phase_halted_evidence_preserved():
    """The production verifier replays the consumed attempt without crashing.

    Regression for the two replay defects together: (1) the admitted-intent
    lint crashed on the `_pins()` argument binding, and (2) the retained
    readback boundary could never parse the retained pretty-JSON readbacks,
    silently stripping the verified op-00 evidence (the first defect alone is
    masked by the second until both are repaired). After the repairs the
    unchanged production verifier returns the preserved-halt verdict, the
    verified prefix separate from the incomplete phase, and nothing relabeled.
    """
    verdict = d4.verify_corridor_attempt(CONSUMED_D4_CANDIDATE)
    assert verdict["verification"] == "PHASE_HALTED_EVIDENCE_PRESERVED"
    assert verdict["result_status"] == "PHASE_HALTED_PREFIX_PRESERVED"
    assert verdict["completed"] == ["full"]
    assert verdict["failed"]["label"] == "op-01"
    assert verdict["pending"] == list(_PENDING_AFTER_HALT)
    assert verdict["error"] == "corridor attempt lacks retained execution evidence"
