"""Actual clearing handler on a controlled Squirrel VM, native contract checks,
and fail-closed phase behavior. No OpenTTD execution is claimed anywhere."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from squirrel import SQVM

from app.planning.p08_clearing import (
    candidates_for_clear_requirement,
    candidates_for_proposal,
    clearing_candidates,
)
from app.simulation.openttd.terrain_clearing import (
    ALLOWED_CLEARING_CLASSES,
    ClearingReadback,
    ClearingRequest,
    admit_clearing,
    phase_outcome,
    verify_clearing,
)

CENSUS = Path("artifacts/demos/classification-exec-seed17-3a8f9e46")
RETAINED = Path(
    "artifacts/demos/playable-demo-698799a2dfb146948fd2983ff2032253/network-facts-0.json"
)
CENSUS_MAP_DIMS = (256, 256)

SEAL = "a" * 64
SAVE = "b" * 64
MAX_COST = 10000
TREE, FARM, ROCK, ROUGH, CLEAR = 0x0009, 0x0011, 0x0021, 0x0041, 0x0001


def vm_for(
    *,
    dims=256,
    funds=100000,
    invalid=False,
    mode_false=False,
    rejected=False,
    slope_shift=0,
    quote_cost=20,
    exec_cost=20,
):
    vm = SQVM()
    vm.execute(Path("tests/fixtures/gamescript_api_15.nut").read_text())
    vm.execute(f"""
        ::dims <- [{dims}, {dims}]; ::tiles <- {{}}; ::funds <- {funds};
        ::valid_company <- {str(not invalid).lower()};
        ::mode_ok <- {str(not mode_false).lower()};
        ::reject <- {str(rejected).lower()}; ::slope_shift <- {slope_shift};
        ::quote_cost <- {quote_cost}; ::exec_cost <- {exec_cost};
        ::account <- 0; ::tests <- {{}}; ::real_calls <- 0; ::test_calls <- 0;
        class GSCompany {{
            static COMPANY_INVALID = -1;
            static function ResolveCompanyID(c) {{ return ::valid_company && c == 0 ? 0 : -1; }}
            static function GetBankBalance(c) {{ return ::funds; }}
        }}
        class GSCompanyMode {{
            constructor(c) {{ if (c != 0) throw "company"; }}
            static function IsValid() {{ return ::mode_ok; }}
        }}
        class GSAccounting {{
            constructor() {{ ::account++; }}
            function GetCosts() {{ return (::account in ::tests) ? ::quote_cost : ::exec_cost; }}
        }}
        class GSTestMode {{ constructor() {{ ::tests[::account] <- true; }} }}
        class GSMap {{
            static function GetMapSizeX() {{ return ::dims[0]; }}
            static function GetMapSizeY() {{ return ::dims[1]; }}
            static function IsValidTile(t) {{ return t in ::tiles; }}
            static function GetTileX(t) {{ return t % ::dims[0]; }}
            static function GetTileY(t) {{ return t / ::dims[0]; }}
        }}
        class GSTile {{
            static TRANSPORT_ROAD=0; static TRANSPORT_RAIL=1;
            static TRANSPORT_WATER=2; static TRANSPORT_AIR=3;
            static function b(t, n) {{ return (::tiles[t].flags & (1 << n)) != 0; }}
            static function IsBuildable(t) {{ return GSTile.b(t, 0); }}
            static function IsWaterTile(t) {{ return GSTile.b(t, 1); }}
            static function IsCoastTile(t) {{ return GSTile.b(t, 2); }}
            static function HasTreeOnTile(t) {{ return GSTile.b(t, 3); }}
            static function IsFarmTile(t) {{ return GSTile.b(t, 4); }}
            static function IsRockTile(t) {{ return GSTile.b(t, 5); }}
            static function IsRoughTile(t) {{ return GSTile.b(t, 6); }}
            static function IsHouseTile(t) {{ return GSTile.b(t, 13); }}
            static function IsStationTile(t) {{ return GSTile.b(t, 14); }}
            static function HasTransportType(t, kind) {{
                return (kind == 0 && GSTile.b(t, 7)) || (kind == 1 && GSTile.b(t, 10)) ||
                       (kind == 2 && GSTile.b(t, 11));
            }}
            static function GetOwner(t) {{ return ::tiles[t].owner; }}
            static function GetMinHeight(t) {{ return ::tiles[t].elevation; }}
            static function GetSlope(t) {{ return ::tiles[t].slope; }}
            static function DemolishTile(t) {{
                if (::account in ::tests) {{ ::test_calls++; return true; }}
                ::real_calls++;
                if (::reject) return false;
                local entry = ::tiles[t];
                entry.flags = entry.flags & ~(1<<3) & ~(1<<4) & ~(1<<5) & ~(1<<6) | 1;
                entry.slope = entry.slope + ::slope_shift;
                ::funds -= ::exec_cost;
                return true;
            }}
        }}
        class GSRoad {{
            static function IsRoadTile(t) {{ return GSTile.b(t, 7); }}
            static function HasRoadType(t, i) {{ return i == 0 && GSTile.b(t, 9); }}
        }}
        class GSAirport {{
            static function IsAirportTile(t) {{ return GSTile.b(t, 12); }}
        }}
        class GSIndustry {{
            static function GetIndustryID(t) {{ return ::tiles[t].industry; }}
            static function IsValidIndustry(i) {{ return i != null && i >= 0; }}
        }}
    """)
    vm.execute((Path("app/simulation/openttd/terrain_clearing_package") / "main.nut").read_text())
    vm.execute("::bridge <- TerrainClearingProof();")
    return vm


def seed_tile(vm, tile, flags, *, elevation=2, slope=0, owner=-1, industry=None):
    vm.execute(
        f"::tiles[{tile}] <- {{flags={flags}, owner={owner}, elevation={elevation}, "
        f"slope={slope}, industry={json.dumps(industry)}}}"
    )


def counters(vm):
    root = vm.get_roottable()
    return root["test_calls"], root["real_calls"], root["funds"]


def request(op, tile, **changes):
    data = dict(
        op=op,
        request_id=f"{op}-{tile}",
        plan=SEAL,
        company=0,
        tile=tile,
        max_cost=MAX_COST,
    )
    data.update(changes)
    return ClearingRequest(**data)


def handle(vm, q):
    before = len(vm.get_roottable()["replies"])
    vm.execute("::bridge.Handle(" + q.to_bytes().decode() + ");")
    replies = vm.get_roottable()["replies"]
    if len(replies) == before:
        raise AssertionError("handler dropped the request without a correlated reply")
    response = replies[len(replies) - 1]
    data = {}
    for key in response.keys():
        k, v = str(key), response[key]
        data[k] = (
            str(v)
            if k in ("op", "request_id", "plan", "status")
            else (bool(v) if k == "eligible" else (None if v is None else int(v)))
        )
    return ClearingReadback.parse_for(q, json.dumps(data, separators=(",", ":")).encode())


def cycle(vm, tile):
    """One complete verified clearing exchange group on the controlled VM."""
    before = handle(vm, request("inspect", tile))
    intent = admit_clearing(
        before, prelaunch_digest=SEAL, source_save_digest=SAVE, max_cost=MAX_COST
    )
    built = handle(vm, request("clear", tile))
    after = handle(vm, request("read", tile, plan=intent.digest))
    receipt = verify_clearing(intent, before, built, after)
    return intent, before, built, after, receipt


def test_tree_tile_full_receipt_cycle():
    vm = vm_for()
    seed_tile(vm, 46769, TREE, elevation=2)
    intent, before, built, after, receipt = cycle(vm, 46769)
    assert intent.expected_classification == "TREES"
    assert intent.native_test_cost == 20
    assert built.status == "CLEARED" and built.cost == 20
    assert after.classification.value == "CLEAR" and after.owner == -1
    assert after.industry is None and after.eligible is False
    assert (after.elevation, after.slope) == (2, 0)
    assert before.funds - built.funds == 20
    quotes, real, funds = counters(vm)
    # Two test-mode quotes (inspect + clear admission), exactly one real command.
    assert quotes == 2 and real == 1 and funds == 100000 - 20
    assert receipt["schema"] == "company-clearing-receipt-v1"
    assert receipt["execution_request_id"] == "clear-46769"
    assert receipt["readback_request_id"] == "read-46769"
    assert receipt["tile"] == 46769 and receipt["company"] == 0
    assert receipt["original_classification"] == "TREES"
    assert receipt["expected_classification"] == "CLEAR"
    assert receipt["operation"] == "DEMOLISH_CLEAR"
    assert receipt["native_command"] == "CMD_LANDSCAPE_CLEAR"
    assert receipt["native_quote"] == 20 and receipt["cost"] == 20
    assert receipt["execution_status"] == "CLEARED"
    assert receipt["error_code"] is None
    assert receipt["verification"] == "NATIVE_STATE_CHANGED"
    digests = [
        receipt[k] for k in ("plan_digest", "before_digest", "construction_digest", "after_digest")
    ]
    assert len(set(digests)) == 4 and all(len(d) == 64 for d in digests)
    assert receipt["prelaunch_digest"] == SEAL and receipt["source_save_digest"] == SAVE


@pytest.mark.parametrize(
    "flags,elevation,slope", [(TREE, 2, 0), (FARM, 2, 0), (ROCK, 3, 2), (ROUGH, 1, 13)]
)
def test_clearable_classes_for_farm_rock_rough_and_trees(flags, elevation, slope):
    vm = vm_for()
    seed_tile(vm, 47537, flags, elevation=elevation, slope=slope)
    intent, before, built, after, receipt = cycle(vm, 47537)
    expected = {TREE: "TREES", FARM: "FARM", ROCK: "ROCK", ROUGH: "ROUGH"}[flags]
    assert intent.expected_classification == expected
    assert before.classification.value == expected
    assert built.status == "CLEARED" and receipt["original_classification"] == expected
    assert after.classification.value == "CLEAR" and after.owner == -1
    # Clearing never rewrites geometry: the slope survives demolition untouched.
    assert (before.elevation, before.slope) == (after.elevation, after.slope)


def test_already_clear_tile_is_no_op_without_any_command():
    vm = vm_for()
    seed_tile(vm, 51378, CLEAR)
    before = handle(vm, request("inspect", 51378))
    assert before.status == "NO_OP" and not before.eligible and before.cost == 0
    with pytest.raises(ValueError, match="already-clear"):
        admit_clearing(before, prelaunch_digest=SEAL, source_save_digest=SAVE, max_cost=MAX_COST)
    assert handle(vm, request("clear", 51378)).status == "NO_OP"
    assert handle(vm, request("read", 51378)).status == "READ"
    quotes, real, _ = counters(vm)
    # Recognized as NO-OP: no quote and no demolition command is triggered.
    assert quotes == 0 and real == 0


@pytest.mark.parametrize("flags,industry", [(0x2000, None), (0x4000, None), (0x0000, 7)])
def test_houses_stations_and_industries_are_never_cleared(flags, industry):
    vm = vm_for()
    seed_tile(vm, 48042, flags, industry=industry)
    before = handle(vm, request("inspect", 48042))
    assert before.status == "FORBIDDEN_CLASS" and not before.eligible
    with pytest.raises(ValueError):
        admit_clearing(before, prelaunch_digest=SEAL, source_save_digest=SAVE, max_cost=MAX_COST)
    assert handle(vm, request("clear", 48042)).status == "FORBIDDEN_CLASS"
    quotes, real, _ = counters(vm)
    assert quotes == 0 and real == 0


@pytest.mark.parametrize(
    "flags",
    [
        0x0080,  # road
        0x0100,  # road track
        0x0200,  # road source road type
        0x0002,  # water
        0x0004,  # coast
        0x1000,  # airport
        0x0400,  # rail
        0x0800,  # dock
        0x0000,  # unknown occupancy
    ],
)
def test_road_water_coast_airport_rail_dock_unknown_are_forbidden(flags):
    vm = vm_for()
    seed_tile(vm, 47792, flags)
    before = handle(vm, request("inspect", 47792))
    assert before.status == "FORBIDDEN_CLASS"
    built = handle(vm, request("clear", 47792))
    assert built.status == "FORBIDDEN_CLASS"
    quotes, real, _ = counters(vm)
    assert quotes == 0 and real == 0
    with pytest.raises(ValueError):
        admit_clearing(before, prelaunch_digest=SEAL, source_save_digest=SAVE, max_cost=MAX_COST)


def test_foreign_owned_tile_is_refused():
    vm = vm_for()
    seed_tile(vm, 46769, TREE, owner=3)
    before = handle(vm, request("inspect", 46769))
    assert before.status == "OWNERSHIP_MISMATCH" and before.owner == 3
    assert handle(vm, request("clear", 46769)).status == "OWNERSHIP_MISMATCH"
    quotes, real, _ = counters(vm)
    assert quotes == 0 and real == 0
    with pytest.raises(ValueError):
        admit_clearing(before, prelaunch_digest=SEAL, source_save_digest=SAVE, max_cost=MAX_COST)


@pytest.mark.parametrize("invalid,mode_false", [(True, False), (False, True)])
def test_company_gates_run_before_any_native_fact(invalid, mode_false):
    vm = vm_for(invalid=invalid, mode_false=mode_false)
    seed_tile(vm, 46769, TREE)
    before = handle(vm, request("inspect", 46769))
    assert before.status == "INVALID_COMPANY"
    unseeded = handle(vm, request("inspect", 47001))
    assert unseeded.status == ("INVALID_LOCATION" if not invalid else "INVALID_COMPANY")
    quotes, real, _ = counters(vm)
    assert quotes == 0 and real == 0


def test_world_identity_mismatch_is_uncorrelated():
    vm = vm_for()
    seed_tile(vm, 46769, TREE)
    wrong = request("inspect", 46769, plan=SAVE)
    raw = json.dumps(
        {
            "protocol": 2,
            "op": "inspect",
            "request_id": wrong.request_id,
            "plan": SEAL,
            "company": 0,
            "tile": 46769,
            "status": "READY",
            "flags": TREE,
            "industry": None,
            "owner": -1,
            "elevation": 2,
            "slope": 0,
            "eligible": True,
            "funds": 100000,
            "cost": 20,
        },
        separators=(",", ":"),
    ).encode()
    with pytest.raises(ValueError, match="correlation"):
        ClearingReadback.parse_for(wrong, raw)
    real = handle(vm, request("inspect", 46769))
    with pytest.raises(ValueError, match="required"):
        admit_clearing(real, prelaunch_digest=SAVE, source_save_digest=SAVE, max_cost=MAX_COST)


def test_stale_execution_evidence_cannot_attach_to_a_new_intent():
    vm = vm_for()
    seed_tile(vm, 46769, TREE, elevation=2)
    seed_tile(vm, 46770, TREE, elevation=2)
    intent1, before1, built1, after1, _ = cycle(vm, 46769)
    fresh = handle(vm, request("inspect", 46770))
    intent2 = admit_clearing(
        fresh, prelaunch_digest=SEAL, source_save_digest=SAVE, max_cost=MAX_COST
    )
    assert intent2.digest != intent1.digest
    with pytest.raises(ValueError, match="correlation mismatch"):
        verify_clearing(intent2, fresh, built1, after1)


def test_duplicate_request_is_dropped_and_rejected_command_latches():
    vm = vm_for()
    seed_tile(vm, 46769, TREE)
    first = request("inspect", 46769)
    assert handle(vm, first).status == "READY"
    with pytest.raises(AssertionError, match="dropped"):
        handle(vm, first)  # duplicate request_id: no correlated second reply
    # Rejected native command latches before any retry could be granted.
    vm_reject = vm_for(rejected=True)
    seed_tile(vm_reject, 46769, TREE)
    before_a = handle(vm_reject, request("inspect", 46769))
    intent_a = admit_clearing(
        before_a, prelaunch_digest=SEAL, source_save_digest=SAVE, max_cost=MAX_COST
    )
    assert intent_a.prelaunch_digest == SEAL
    built_a = handle(vm_reject, request("clear", 46769))
    assert before_a.status == "READY" and built_a.status == "REJECTED"
    second = handle(vm_reject, request("clear", 46769, request_id="clear-2"))
    assert second.status == "ALREADY_ATTEMPTED"
    assert handle(vm_reject, request("clear", 46769, request_id="clear-3")).status == (
        "ALREADY_ATTEMPTED"
    )
    quotes, real, funds = counters(vm_reject)
    # No automatic retry: the failed command consumed the single real attempt.
    assert real == 1 and funds == 100000 and quotes == 2


def test_cost_ceiling_blocks_the_command():
    vm = vm_for(quote_cost=172)
    seed_tile(vm, 47537, ROUGH)
    before = handle(vm, request("inspect", 47537, max_cost=100))
    assert before.status == "COST_LIMIT" and before.cost == 172
    with pytest.raises(ValueError):
        admit_clearing(before, prelaunch_digest=SEAL, source_save_digest=SAVE, max_cost=100)
    built = handle(vm, request("clear", 47537, max_cost=100))
    assert built.status == "COST_LIMIT"
    quotes, real, _ = counters(vm)
    assert quotes == 2 and real == 0


def test_insufficient_funds_blocks_the_command():
    vm = vm_for(funds=10)
    seed_tile(vm, 46769, TREE)
    before = handle(vm, request("inspect", 46769))
    assert before.status == "INSUFFICIENT_FUNDS" and before.funds == 10
    with pytest.raises(ValueError):
        admit_clearing(before, prelaunch_digest=SEAL, source_save_digest=SAVE, max_cost=MAX_COST)
    assert handle(vm, request("clear", 46769)).status == "INSUFFICIENT_FUNDS"
    quotes, real, funds = counters(vm)
    assert quotes == 2 and real == 0 and funds == 10


def test_native_command_failure_is_not_success_and_latches():
    vm = vm_for(rejected=True)
    seed_tile(vm, 46769, TREE, elevation=2)
    before = handle(vm, request("inspect", 46769))
    intent = admit_clearing(
        before, prelaunch_digest=SEAL, source_save_digest=SAVE, max_cost=MAX_COST
    )
    built = handle(vm, request("clear", 46769))
    assert built.status == "REJECTED" and built.cost == 20
    with pytest.raises(ValueError, match="disagreement"):
        verify_clearing(
            intent, before, built, handle(vm, request("read", 46769, plan=intent.digest))
        )
    quotes, real, funds = counters(vm)
    assert real == 1 and quotes == 2 and funds == 100000
    assert handle(vm, request("clear", 46769, request_id="clear-2")).status == ("ALREADY_ATTEMPTED")


def test_quote_exec_disagreement_fails_receipt():
    vm = vm_for(exec_cost=40)
    seed_tile(vm, 46769, TREE)
    before = handle(vm, request("inspect", 46769))
    intent = admit_clearing(
        before, prelaunch_digest=SEAL, source_save_digest=SAVE, max_cost=MAX_COST
    )
    built = handle(vm, request("clear", 46769))
    assert built.status == "CLEARED" and built.cost == 40
    # Without a retry, the readback must agree with the tested quote or fail.
    with pytest.raises(ValueError, match="disagreement"):
        verify_clearing(
            intent, before, built, handle(vm, request("read", 46769, plan=intent.digest))
        )


def test_post_clear_geometry_change_is_refused():
    vm = vm_for(slope_shift=1)
    seed_tile(vm, 47537, ROUGH, elevation=1, slope=13)
    before = handle(vm, request("inspect", 47537))
    intent = admit_clearing(
        before, prelaunch_digest=SEAL, source_save_digest=SAVE, max_cost=MAX_COST
    )
    built = handle(vm, request("clear", 47537))
    assert built.status == "READBACK_MISMATCH" and built.slope == 14
    with pytest.raises(ValueError):
        verify_clearing(intent, before, built, handle(vm, request("read", 47537)))
    # Python-side independent re-check even if the handler verdict were clean.
    shifted_clear = ClearingReadback(
        op="clear",
        request_id="clear-47537",
        plan=SEAL,
        company=0,
        tile=47537,
        status="CLEARED",
        flags=CLEAR,
        industry=None,
        owner=-1,
        elevation=1,
        slope=14,
        eligible=False,
        funds=before.funds - 20,
        cost=20,
    )
    after_shifted = ClearingReadback(
        op="read",
        request_id="read-47537",
        plan=intent.digest,
        company=0,
        tile=47537,
        status="READ",
        flags=CLEAR,
        industry=None,
        owner=-1,
        elevation=1,
        slope=14,
        eligible=False,
        funds=before.funds - 20,
        cost=20,
    )
    with pytest.raises(ValueError, match="geometry mismatch"):
        verify_clearing(intent, before, shifted_clear, after_shifted)


def test_neighbor_reads_reveal_no_unexpected_side_effect():
    vm = vm_for()
    seed_tile(vm, 46769, TREE, elevation=2)
    seed_tile(vm, 46770, TREE, elevation=2)
    neighbor_before = handle(vm, request("read", 46770))
    assert neighbor_before.status == "READ"
    _, _, _, _, receipt = cycle(vm, 46769)
    neighbor_after = handle(vm, request("read", 46770, request_id="read-2"))
    for field in ("flags", "owner", "elevation", "slope", "eligible"):
        assert getattr(neighbor_after, field) == getattr(neighbor_before, field)
    quotes, real, _ = counters(vm)
    # Exactly one quote pair and one real command: the neighbor saw no commands.
    assert quotes == 2 and real == 1


def test_response_correlation_and_transport_bounds():
    vm = vm_for()
    seed_tile(vm, 650, TREE)
    before = handle(vm, request("inspect", 650))
    assert before.status == "READY"
    mutated = {
        "protocol": 2,
        "op": "read",
        "request_id": "inspect-650",
        "plan": SEAL,
        "company": 0,
        "tile": 650,
        "status": "READY",
        "flags": TREE,
        "industry": None,
        "owner": -1,
        "elevation": 2,
        "slope": 0,
        "eligible": True,
        "funds": 100000,
        "cost": 20,
    }
    with pytest.raises(ValueError, match="correlation mismatch"):
        ClearingReadback.parse_for(
            request("inspect", 650),
            json.dumps(mutated, separators=(",", ":")).encode(),
        )
    with pytest.raises(ValueError, match="duplicate response key"):
        inspect_reply = dict(mutated)
        inspect_reply["op"] = "inspect"
        well_formed = json.dumps(inspect_reply, separators=(",", ":"))
        ClearingReadback.parse_for(
            request("inspect", 650),
            well_formed[:-1].encode() + b',"status":"READ"}',
        )
    with pytest.raises(ValueError, match="exceeds 512"):
        ClearingReadback.parse_for(request("inspect", 650), b"x" * 600)
    worst_request = ClearingRequest(
        op="clear",
        request_id="x" * 32,
        plan="f" * 64,
        company=14,
        tile=65535,
        max_cost=2147483647,
    )
    assert len(worst_request.to_bytes()) <= 512
    worst_readback = ClearingReadback(
        op="read",
        request_id="x" * 32,
        plan="f" * 64,
        company=14,
        tile=65535,
        status="UNSUPPORTED_NATIVE_FACT",
        flags=32767,
        industry=63999,
        owner=14,
        elevation=255,
        slope=31,
        eligible=False,
        funds=-2147483648,
        cost=2147483647,
    )
    assert len(json.dumps(json.loads(_canonical(worst_readback)), sort_keys=True).encode()) <= 512


def _canonical(model):
    from app.planning.canonical import canonical_bytes

    return canonical_bytes(model).decode()


def test_phase_outcome_is_fail_closed_and_preserves_verified_receipts():
    vm_ok = vm_for()
    seed_tile(vm_ok, 46769, TREE, elevation=2)
    intent1, before1, built1, after1, receipt1 = cycle(vm_ok, 46769)
    vm_bad = vm_for(rejected=True)
    seed_tile(vm_bad, 46770, TREE, elevation=2)
    before2 = handle(vm_bad, request("inspect", 46770))
    intent2 = admit_clearing(
        before2, prelaunch_digest=SEAL, source_save_digest=SAVE, max_cost=MAX_COST
    )
    built2 = handle(vm_bad, request("clear", 46770))
    assert built2.status == "REJECTED"
    outcome = phase_outcome(
        [
            (
                "cleared-46769",
                dict(intent=intent1, before=before1, built=built1, after=after1),
            ),
            ("failing-46770", dict(intent=intent2, before=before2, built=built2)),
            ("pending-46771", dict()),
        ]
    )
    assert outcome["schema"] == "clearing-phase-outcome-v1"
    assert outcome["completed"] == [receipt1]  # verified prior receipt preserved
    assert outcome["failed"]["label"] == "failing-46770"
    assert "disagreement" in outcome["failed"]["error"]
    assert outcome["pending"] == ["pending-46771"]  # halted: no retry, no compensation
    assert outcome["verification"] == "PARTIAL_EXECUTION_EVIDENCE"
    whole = phase_outcome(
        [("only", dict(intent=intent1, before=before1, built=built1, after=after1))]
    )
    assert whole["verification"] == "PHASE_COMPLETE" and len(whole["completed"]) == 1
    assert whole["failed"] is None and whole["pending"] == []


def test_small_disposable_world_compatibility():
    vm = vm_for(dims=64)
    seed_tile(vm, 650, TREE, elevation=2)
    intent, before, built, after, receipt = cycle(vm, 650)
    assert built.status == "CLEARED" and after.classification.value == "CLEAR"
    assert receipt["tile"] == 650 and receipt["verification"] == "NATIVE_STATE_CHANGED"


@pytest.mark.skipif(not (CENSUS.exists() and RETAINED.exists()), reason="retained evidence absent")
def test_retained_seed17_clearing_candidates_match_census():
    from app.planning.p08_v2_snapshot import _load_census

    _, census, _, _ = _load_census(RETAINED, CENSUS)
    facts = {
        tile: SimpleNamespace(
            classification=fact.classification,
            owner=fact.owner,
            elevation=fact.elevation,
            slope=fact.slope,
            industry_id=fact.industry_id,
        )
        for tile, fact in census.items()
    }
    levelling = candidates_for_proposal(
        SimpleNamespace(cleared_tiles=(45999, 49326)),
        facts=facts,
        provenance="docs/p08-v2-snapshot-p08-readiness.md levelling.cleared_tiles",
    )
    required = candidates_for_clear_requirement(
        (46769, 47537),
        facts=facts,
        provenance="docs/p08-v2-snapshot-p08-readiness.md assessment_primary.required_ops",
    )
    for candidates in (levelling, required):
        for candidate in candidates:
            assert candidate.execution_status == "PLANNING_ONLY"
            assert candidate.expected_owner == -1
            assert candidate.expected_classification in ALLOWED_CLEARING_CLASSES
            assert candidate.x == candidate.tile % CENSUS_MAP_DIMS[0]
            assert candidate.y == candidate.tile // CENSUS_MAP_DIMS[0]
    assert [
        (c.tile, c.expected_classification, c.expected_elevation, c.expected_slope)
        for c in levelling
    ] == [(45999, "TREES", 2, 0), (49326, "TREES", 1, 0)]
    assert [
        (c.tile, c.expected_classification, c.expected_elevation, c.expected_slope)
        for c in required
    ] == [(46769, "TREES", 2, 0), (47537, "ROUGH", 1, 13)]
    assert levelling[0].provenance.startswith("docs/p08-v2-snapshot-p08-readiness.md")


def test_candidate_binding_fails_closed_on_nonclearing_or_missing_evidence():
    from app.simulation.openttd.tile_classification import TileClass

    facts = {
        51378: SimpleNamespace(
            classification=TileClass.CLEAR.value,
            owner=-1,
            elevation=2,
            slope=0,
            industry_id=None,
        )
    }
    with pytest.raises(ValueError, match="not a bounded clearing class"):
        clearing_candidates(
            (51378,),
            facts=facts,
            source="proposal_cleared_tiles",
            provenance="x",
            map_dims=CENSUS_MAP_DIMS,
        )
    with pytest.raises(ValueError, match="no census classification"):
        clearing_candidates(
            (46769,),
            facts=facts,
            source="proposal_cleared_tiles",
            provenance="x",
            map_dims=CENSUS_MAP_DIMS,
        )
    facts[46769] = facts[51378]
    facts[46769] = SimpleNamespace(
        classification=TileClass.TREES.value, owner=-1, elevation=2, slope=0, industry_id=None
    )
    with pytest.raises(ValueError, match="never cleared twice"):
        clearing_candidates(
            (46769, 46769),
            facts=facts,
            source="proposal_cleared_tiles",
            provenance="x",
            map_dims=CENSUS_MAP_DIMS,
        )
    owned = SimpleNamespace(
        classification=TileClass.TREES.value, owner=0, elevation=2, slope=0, industry_id=None
    )
    with pytest.raises(ValueError, match="not unowned"):
        clearing_candidates(
            (46770,),
            facts={46770: owned},
            source="proposal_cleared_tiles",
            provenance="x",
            map_dims=CENSUS_MAP_DIMS,
        )
    with pytest.raises(ValueError, match="outside the declared map dimensions"):
        clearing_candidates(
            (46769,),
            facts=facts,
            source="proposal_cleared_tiles",
            provenance="x",
            map_dims=(64, 64),
        )


def test_handler_is_a_single_interpreter_for_demolition_only():
    package = Path("app/simulation/openttd/terrain_clearing_package")
    assert {p.name for p in package.iterdir()} == {"info.nut", "main.nut"}
    handler = (package / "main.nut").read_text()
    # GSTile.DemolishTile is the only mutation: once for the test-mode quote,
    # once for the real command. No terraform or construction commands exist.
    assert handler.count("GSTile.DemolishTile(q.tile)") == 2
    for forbidden in (
        "RaiseTile",
        "LowerTile",
        "LevelTiles",
        "GSTerraform",
        "BuildRoad",
        "BuildDock",
        "BuildObject",
        "BuildBridge",
        "BuildTunnel",
    ):
        assert forbidden not in handler
    assert "TERRAIN_CLEARING_READY" in handler
    assert handler.count("requests >= 24") == 1  # the mirrored request budget
