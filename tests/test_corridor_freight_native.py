"""Controlled offline tests for the D5 native corridor-freight staging contract.

No OpenTTD launch, no AdminPort connection, no native mutation, and no claim on
any retained artifact: staging, the pinned D4 prerequisite binding, the sealed
freight pins, the fifteen-exchange schedule, budgets, authorization payload
reuse, preflight gates, freeze drift and the never-consumed fail-closed
verdicts are exercised against explicitly controlled evidence directories
only.

The pinned retained D4 prerequisite (whose receipt-bound ``after.sav`` is the
authoritative corridor world) is read, never written. Its distinct diagnostic
save is never an acceptable substitute. The prerequisite replay re-verifies
the retained authorization under the real pinned operator anchor, so these
tests substitute no synthetic identity anywhere.
"""

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.simulation.openttd.proof.corridor_freight_native as d5
from app.simulation.openttd.admin_protocol import encode_admin_frame
from app.simulation.openttd.corridor_freight import (
    FREIGHT_EXCHANGE_IDS,
    FREIGHT_MAX_COST,
    FREIGHT_REQUEST_BUDGET,
    FUNDS_AT_D4_CLOSE,
    LOAD_WATCH_MAX_DAYS,
    MAX_FREIGHT_REQUEST_BYTES,
    MAX_FREIGHT_RESPONSE_BYTES,
    MAX_FREIGHT_SEND_BYTES,
    PLANNED_FREIGHT_EXCHANGES,
    WATCH_MAX_TICKS,
    FreightReadback,
    FreightRequest,
)
from app.simulation.openttd.gamescript_transport import (
    MAX_GAMESCRIPT_PAYLOAD_BYTES,
    decode_gamescript,
    encode_gamescript,
)
from app.simulation.openttd.observation_protocol import MAX_PAYLOAD_BYTES
from app.simulation.openttd.proof.harness import sha256
from app.simulation.openttd.proof.operator_authorization import (
    authorization_payload,
    canonical_authorization_bytes,
)
from app.simulation.openttd.proof.terrain_clearing import (
    ClearingNativeBackend,
    claim_status,
    retained_welcome,
)
from app.simulation.openttd.proof.world_correspondence import SOURCE_SAVE_GS_NAME


@pytest.fixture(scope="module")
def staged(tmp_path_factory):
    prepared = d5.prepare_candidate(tmp_path_factory.mktemp("d5-staging") / "candidate")
    yield prepared
    prepared.spec.workspace.close()


def metadata_of(prepared) -> dict:
    return json.loads((prepared.directory / "PRELAUNCH.json").read_text())


def _restamp_prelaunch(directory: Path) -> None:
    (directory / "PRELAUNCH.sha256").write_text(sha256(directory / "PRELAUNCH.json") + "\n")


def _add_freeze_probe(directory: Path, source: Path) -> Path:
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
    (directory / "PRELAUNCH.json").write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n")
    _restamp_prelaunch(directory)
    return probe


def _snapshot(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# --- staging correctness and the pinned prerequisite lineage -----------------


def test_prerequisite_binding_is_pinned_and_read_only():
    """The D4 candidate-5 prerequisite re-verifies without being touched."""
    before = _snapshot(d5.PINNED_PREREQUISITE)
    binding = d5.prerequisite_binding()
    after = _snapshot(d5.PINNED_PREREQUISITE)
    assert before == after
    assert sha256(d5.PINNED_PREREQUISITE / "after.sav") == d5.PINNED_PREREQUISITE_AFTER_SAVE
    assert binding == {
        "schema": d5.D5_FREIGHT_PREREQUISITE_SCHEMA,
        "role": "PREREQUISITE_ATTEMPT",
        "retained_directory": str(d5.PINNED_PREREQUISITE),
        "save": "after.sav",
        "save_sha256": d5.PINNED_PREREQUISITE_AFTER_SAVE,
        "qualified_save_sha256": None,
        "prelaunch_digest": sha256(d5.PINNED_PREREQUISITE / "PRELAUNCH.json"),
        "attempt": "D4-CORRIDOR-5",
        "milestone": "D4-CONSTRUCTION",
        "expected_welcome": retained_welcome(),
        "verification": (
            "full replay verification of the consumed prerequisite attempt "
            "receipt plus the pinned authoritative after-save digest"
        ),
        "provenance": binding["provenance"],
    }
    assert binding["provenance"]["after_save_sha256"] == d5.PINNED_PREREQUISITE_AFTER_SAVE
    assert binding["provenance"]["attempt"] == "D4-CORRIDOR-5"


def test_staged_candidate_binds_the_pinned_d4_prerequisite(staged):
    metadata = metadata_of(staged)
    assert metadata["schema"] == d5.D5_FREIGHT_PRELAUNCH_SCHEMA
    assert metadata["milestone"] == d5.MILESTONE_FREIGHT
    assert metadata["kind"] == d5.KIND
    assert metadata["attempt"] == d5.FREIGHT_ATTEMPT
    save_digest = sha256(d5.PINNED_PREREQUISITE / "after.sav")
    assert save_digest == d5.PINNED_PREREQUISITE_AFTER_SAVE
    prerequisite = metadata["prerequisite"]
    assert prerequisite == {
        "schema": d5.D5_FREIGHT_PREREQUISITE_SCHEMA,
        "attempt": "D4-CORRIDOR-5",
        "milestone": "D4-CONSTRUCTION",
        "directory": str(d5.PINNED_PREREQUISITE),
        "prelaunch_sha256": sha256(d5.PINNED_PREREQUISITE / "PRELAUNCH.json"),
        "after_save_sha256": save_digest,
        "verification": (
            "full replay verification of the consumed prerequisite attempt "
            "receipt plus the pinned authoritative after-save digest"
        ),
    }
    assert (
        metadata["prerequisite_provenance"]["prelaunch_sha256"] == prerequisite["prelaunch_sha256"]
    )
    assert metadata["authorization"].startswith("PENDING")
    assert "no authorization file exists" in metadata["authorization"]
    assert claim_status(staged.directory) == "ABSENT"
    assert not (staged.directory / "CLAIM.json").exists()


def test_staging_refuses_any_unpinned_prerequisite(tmp_path):
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    with pytest.raises(d5.FreightStagingError, match="pinned D4"):
        d5.prepare_candidate(tmp_path / "candidate", prerequisite=unrelated)
    with pytest.raises(d5.FreightStagingError, match="pinned D4"):
        d5.prerequisite_binding(unrelated)
    assert not (tmp_path / "candidate").exists()


def test_staged_composition_carries_the_retained_save_identity(staged):
    composition, bridge, version = d5.staged_composition()
    gs = staged.spec.workspace.root / "game" / SOURCE_SAVE_GS_NAME
    assert gs.joinpath("info.nut").read_bytes() == composition["info.nut"]
    assert gs.joinpath("main.nut").read_bytes() == composition["main.nut"]
    assert bridge == "NetworkFreightProof" and version == 1
    main_text = gs.joinpath("main.nut").read_text()
    assert "class NetworkFreightProof extends D5FreightProof" in main_text
    ai = staged.spec.workspace.root / "ai" / d5.STAGED_AI_DIRECTORY
    for name in ("info.nut", "main.nut"):
        assert sha256(ai / name) == sha256(d5.AI_PACKAGE / name)
    assert metadata_of(staged)["game_script_identity"]["create_instance"] == bridge


def test_staged_source_save_is_the_pinned_verified_after_world(staged):
    root = staged.spec.workspace.root
    assert sha256(root / "source.sav") == d5.PINNED_PREREQUISITE_AFTER_SAVE
    assert sha256(root / "source.sav") == sha256(d5.PINNED_PREREQUISITE / "after.sav")
    diagnostic = sha256(d5.PINNED_PREREQUISITE / "after-diagnostic.sav")
    assert diagnostic != d5.PINNED_PREREQUISITE_AFTER_SAVE
    world = metadata_of(staged)["world"]
    assert world["mode"] == "PREREQUISITE_ATTEMPT_SOURCE_SAVE_LOAD"
    assert world["retained_directory"] == str(d5.PINNED_PREREQUISITE)
    assert world["source_save"] == "after.sav"
    assert world["save_sha256"] == d5.PINNED_PREREQUISITE_AFTER_SAVE
    assert world["qualified_save_sha256"] is None
    assert world["expected_welcome"] == retained_welcome()
    config = root.joinpath("openttd.cfg").read_text()
    assert "[game_creation]" not in config
    assert f"[game_scripts]\n{SOURCE_SAVE_GS_NAME} = \n" in config
    assert "ai_in_multiplayer = true" in config


def test_preflight_rehearsal_conserves_the_sealed_candidate(staged):
    prior = sha256(staged.directory / "PRELAUNCH.json")
    metadata = d5.preflight(staged)
    assert sha256(staged.directory / "PRELAUNCH.json") == prior
    assert metadata["attempt"] == d5.FREIGHT_ATTEMPT
    assert not (staged.directory / "CLAIM.json").exists()
    assert claim_status(staged.directory) == "ABSENT"


# --- preflight refusal gates --------------------------------------------------


def test_tampered_workspace_config_refuses_d5_preflight(tmp_path):
    prepared = d5.prepare_candidate(tmp_path / "candidate")
    try:
        config = prepared.spec.workspace.config
        config.write_text(config.read_text() + "# tampered\n")
        with pytest.raises(ValueError):
            d5.preflight(prepared)
    finally:
        prepared.spec.workspace.close()


def test_drifted_source_save_refuses_d5_preflight(tmp_path):
    prepared = d5.prepare_candidate(tmp_path / "candidate")
    try:
        (prepared.spec.workspace.root / "source.sav").write_bytes(b"tampered world bytes")
        with pytest.raises(ValueError):
            d5.preflight(prepared)
    finally:
        prepared.spec.workspace.close()


def test_frozen_source_drift_refuses_d5_preflight(tmp_path):
    """Post-preparation frozen drift of the D5 module itself refuses preflight."""
    prepared = d5.prepare_candidate(tmp_path / "candidate")
    try:
        probe = _add_freeze_probe(prepared.directory, Path(d5.__file__))
        probe.write_bytes(probe.read_bytes() + b"\n# modified after preparation\n")
        with pytest.raises(ValueError, match="Frozen source"):
            d5.preflight(prepared)
        assert not (prepared.directory / "CLAIM.json").exists()
    finally:
        prepared.spec.workspace.close()


def test_removed_closure_entry_refuses_d5_preflight(tmp_path):
    prepared = d5.prepare_candidate(tmp_path / "candidate")
    try:
        target = str(Path(d5.__file__).resolve())
        metadata = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
        assert target in metadata["frozen"]
        del metadata["frozen"][target]
        (prepared.directory / "PRELAUNCH.json").write_text(
            json.dumps(metadata, sort_keys=True, indent=2) + "\n"
        )
        _restamp_prelaunch(prepared.directory)
        with pytest.raises(ValueError, match="closure is not frozen"):
            d5.preflight(prepared)
        assert not (prepared.directory / "CLAIM.json").exists()
    finally:
        prepared.spec.workspace.close()


def test_drifted_schedule_pin_refuses_d5_preflight(tmp_path):
    prepared = d5.prepare_candidate(tmp_path / "candidate")
    try:
        metadata = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
        metadata["plan_policy"]["schedule"][-1]["exchange"] = "finish-99"
        (prepared.directory / "PRELAUNCH.json").write_text(
            json.dumps(metadata, sort_keys=True, indent=2) + "\n"
        )
        _restamp_prelaunch(prepared.directory)
        with pytest.raises(ValueError, match="schedule drifted"):
            d5.preflight(prepared)
        assert not (prepared.directory / "CLAIM.json").exists()
    finally:
        prepared.spec.workspace.close()


def test_seal_and_claim_gates_refuse_drifted_or_drafted_launch_boundaries(tmp_path):
    """The outermost preflight gates: a drifted seal and any existing claim."""
    prepared = d5.prepare_candidate(tmp_path / "candidate")
    try:
        directory = prepared.directory
        prelaunch = directory / "PRELAUNCH.json"
        original = prelaunch.read_bytes()
        prelaunch.write_bytes(original + b"\n# drifted after staging\n")
        with pytest.raises(ValueError, match="prelaunch seal mismatch"):
            d5.preflight(prepared)
        prelaunch.write_bytes(original)
        (directory / "CLAIM.json").write_text("{}\n")
        with pytest.raises(ValueError, match="one native attempt already consumed"):
            d5.preflight(prepared)
        (directory / "CLAIM.json").unlink()
        # The restored candidate returns to the passing gate, boundary intact.
        d5.preflight(prepared)
    finally:
        prepared.spec.workspace.close()


def test_preflight_rejects_resealed_execution_pin_drift(tmp_path):
    """Every execution-relevant pin is bound, even after a valid re-seal.

    A re-sealed PRELAUNCH record must not be able to swap the world geometry,
    the optimizer provenance, the plan model identity, funds or schedule
    binding. Each mutation below is individually restored before the next.
    """
    prepared = d5.prepare_candidate(tmp_path / "candidate")
    directory = prepared.directory
    prelaunch = directory / "PRELAUNCH.json"
    original = prelaunch.read_bytes()

    def swap(section, key, value):
        def mutate(metadata):
            metadata[section][key] = value

        return mutate

    def swap_world(key, value):
        def mutate(metadata):
            metadata["plan_policy"]["world"][key] = value

        return mutate

    def swap_world_witness(metadata):
        metadata["plan_policy"]["world"]["witness"][4] = 12345

    def swap_optimizer(key, value):
        def mutate(metadata):
            metadata["plan_policy"]["optimizer"][key] = value

        return mutate

    mutations = (
        ("world pickup", swap_world("pickup", 45749), "world pin pickup"),
        (
            "world delivery front",
            swap_world("delivery_front", 50094),
            "world pin delivery_front",
        ),
        ("world depot", swap_world("depot", 45488), "world pin depot"),
        ("world witness", swap_world_witness, "world pin witness"),
        ("optimizer depot", swap_optimizer("depot", 45488), "optimizer pin depot"),
        (
            "optimizer depot front",
            swap_optimizer("depot_front", 45744),
            "optimizer pin depot_front",
        ),
        (
            "optimizer route digest",
            swap_optimizer("route_digest", "b" * 64),
            "optimizer pin route_digest",
        ),
        (
            "optimizer candidate",
            swap_optimizer("candidate_id", "corridor-stale"),
            "optimizer pin candidate_id",
        ),
        (
            "plan model digest",
            swap("plan_policy", "plan_model_digest", "c" * 64),
            "plan pin plan_model_digest",
        ),
        ("plan target tile", swap("plan_policy", "target_tile", 45749), "plan pin target_tile"),
        ("plan max cost", swap("plan_policy", "max_cost", 1999), "plan pin max_cost"),
        (
            "budget funds",
            swap("budgets", "expected_funds", 1),
            "budget pins drifted",
        ),
    )
    try:
        for label, mutate, message in mutations:
            metadata = json.loads(original)
            mutate(metadata)
            prelaunch.write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n")
            _restamp_prelaunch(directory)
            try:
                d5.preflight(prepared)
            except ValueError as error:
                assert message in str(error), (label, str(error))
            else:
                raise AssertionError(f"{label} did not refuse preflight")
        prelaunch.write_bytes(original)
        _restamp_prelaunch(directory)
        assert d5.preflight(prepared)["attempt"] == d5.FREIGHT_ATTEMPT
    finally:
        prepared.spec.workspace.close()


# --- sealed freight facts, schedule, budgets and route scope -----------------


def test_freight_facts_bind_the_sealed_corridor_world():
    facts = d5.freight_facts()
    assert facts["witness"] == [
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
    ]
    witness = facts["witness"]
    assert len(set(witness)) == len(witness) == 24
    assert min(witness) >= 0 and max(witness) <= 0xFFFF
    assert facts["depot"] == dict(tile_id=45487, front_tile_id=45743, orientation="south")
    assert facts["stops"] == [45748, 50351]
    assert facts["fronts"] == [45747, 50095]
    pickup, delivery = facts["coverage"]
    assert (pickup["tile"], pickup["role"], pickup["industry_id"]) == (
        45748,
        "pickup",
        0,
    )
    assert pickup["cargo_id"] == 1 and pickup["industry_covered"] is True
    assert pickup["producer_count"] == 1
    assert (delivery["tile"], delivery["role"], delivery["industry_id"]) == (
        50351,
        "delivery",
        1,
    )
    assert delivery["cargo_id"] == 1 and delivery["industry_covered"] is True


def test_freight_schedule_is_the_fixed_fifteen_exchange_cycle():
    schedule = d5.freight_schedule()
    assert [entry["exchange"] for entry in schedule] == list(FREIGHT_EXCHANGE_IDS)
    assert len(schedule) == PLANNED_FREIGHT_EXCHANGES == 15
    assert len({entry["exchange"] for entry in schedule}) == 15
    assert [(entry["exchange"], entry["op"]) for entry in schedule] == [
        ("site-00", "site"),
        ("engine-00", "engine"),
        ("purchase-00", "purchase"),
        ("vread-00", "vread"),
        ("order-00", "order"),
        ("order-01", "order"),
        ("order-read-00", "order-read"),
        ("monitor-00", "monitor"),
        ("start-00", "start"),
        ("vread-01", "vread"),
        ("load-00", "load-watch"),
        ("transit-00", "transit-watch"),
        ("deliver-00", "deliver-watch"),
        ("finance-00", "finance"),
        ("finish-00", "finish"),
    ]
    # Thirteen distinct logical operations: the vehicle readback runs twice.
    assert len({entry["op"] for entry in schedule}) == 13
    vreads = [entry["exchange"] for entry in schedule if entry["op"] == "vread"]
    assert vreads == ["vread-00", "vread-01"]
    assert schedule[4]["order_index"] == 0 and schedule[5]["order_index"] == 1
    assert schedule[10]["watch_ticks"] == WATCH_MAX_TICKS
    assert schedule[10]["watch_days"] == LOAD_WATCH_MAX_DAYS
    assert "watch_days" not in schedule[11] and "watch_days" not in schedule[12]
    assert d5._scheduled_exchange_ids(schedule) == set(FREIGHT_EXCHANGE_IDS)


def test_freight_plan_rebinds_the_compiled_corridor_pins():
    facts = d5.freight_facts()
    plan = d5.freight_plan()
    assert plan.company == 0
    assert plan.cargo == 1
    assert (plan.pickup, plan.pickup_front) == (45748, 45747)
    assert (plan.delivery, plan.delivery_front) == (50351, 50095)
    assert (plan.depot, plan.depot_front) == (45487, 45743)
    assert (plan.pickup_industry, plan.delivery_industry) == (0, 1)
    assert plan.expected_funds == FUNDS_AT_D4_CLOSE == 492149
    assert plan.max_cost == FREIGHT_MAX_COST == 2000
    assert plan.witness == tuple(facts["witness"])
    assert plan.schedule == FREIGHT_EXCHANGE_IDS


def test_plan_policy_binds_schedule_world_and_wire_identity():
    plan = d5.plan_policy()
    schedule = d5.freight_schedule()
    assert plan["company"] == 0
    assert plan["target_tile"] == 45748
    assert plan["max_cost"] == FREIGHT_MAX_COST
    assert plan["command"] == (
        "GSVehicle.BuildVehicle + GSOrder.AppendOrder + GSVehicle.StartStopVehicle"
    )
    assert "re-observe every pin" in plan["stale_rule"]
    assert "wire contract v5" in plan["identity"]
    assert plan["schedule"] == schedule
    assert plan["plan_digest"] == d5.plan_digest_of(schedule)
    assert plan["plan_model_digest"] == d5.freight_plan().digest
    assert plan["optimizer"]["route_digest"] == d5.freight_plan().route_digest
    assert plan["schedule_version"] == d5.SCHEDULE_VERSION == 1
    world = plan["world"]
    assert world["witness"] == d5.freight_facts()["witness"]
    assert world["expected_funds"] == FUNDS_AT_D4_CLOSE
    assert world["expected_fleet"] == 0
    assert world["max_watch_requests"] == FREIGHT_REQUEST_BUDGET == 32
    assert plan["prerequisite_world"]["schema"] == d5.D5_FREIGHT_PREREQUISITE_SCHEMA
    assert "truck stops" in plan["prerequisite_world"]["statement"]


def test_budgets_match_the_staged_contract():
    assert d5.budgets() == {
        "launches": 1,
        "connection_attempts": 1,
        "requests": 32,
        "planned_exchanges": 15,
        "gsadmin_bytes": 1450,
        "response_bytes": 640,
        "retries": 0,
        "reconnects": 0,
        "readiness_seconds": 45,
        "request_seconds": 10,
        "total_seconds": 900,
        "watch_ticks": 2048,
        "watch_days": 30,
        "max_cost": 2000,
        "expected_funds": 492149,
    }
    assert d5.PLANNED_FREIGHT_REQUESTS == len(d5.freight_schedule()) == 15
    assert d5.FREIGHT_STAGED_REQUESTS_BUDGET == FREIGHT_REQUEST_BUDGET == 32
    assert d5.MAX_FREIGHT_SEND_BYTES == MAX_FREIGHT_SEND_BYTES == 1450
    assert d5.MAX_FREIGHT_RESPONSE_BYTES == MAX_FREIGHT_RESPONSE_BYTES == 640
    assert "no aggregate phase-spending budget" in d5.budgets.__doc__


def test_expected_readback_policy_covers_every_phase():
    policy = d5.expected_readback_policy()
    assert set(policy) == {
        "admission",
        "engine",
        "purchase",
        "vehicle",
        "orders",
        "drive",
        "finance",
        "finish",
        "receipt",
    }
    assert "zero vehicles" in policy["admission"]
    assert "positive quote" in policy["engine"]
    assert "funds moving by exactly" in policy["purchase"]
    assert "zero cost" in policy["vehicle"]
    assert "two-order set" in policy["orders"]
    assert "bounded tick/day budgets" in policy["drive"]
    assert "same-quarter income" in policy["finance"]
    assert "never sold" in policy["finish"]
    assert "cycle-bound only" in policy["receipt"]


# --- authorization payload, planned exchanges and wire identities -------------


def test_authorization_payload_adds_the_ordered_exchange_scope(staged):
    metadata = metadata_of(staged)
    seal = sha256(staged.directory / "PRELAUNCH.json")
    payload = authorization_payload(metadata, seal)
    schedule = d5.freight_schedule()
    assert payload["milestone"] == d5.MILESTONE_FREIGHT
    assert payload["attempt"] == d5.FREIGHT_ATTEMPT
    assert payload["schema"] == d5.D5_FREIGHT_PRELAUNCH_SCHEMA
    assert payload["target_tile"] == 45748
    assert payload["company"] == 0
    assert payload["max_cost"] == FREIGHT_MAX_COST
    assert payload["source_world"]["source_save"] == "after.sav"
    assert payload["source_world"]["save_sha256"] == d5.PINNED_PREREQUISITE_AFTER_SAVE
    assert payload["source_world"]["qualified_save_sha256"] is None
    assert payload["budgets"] == d5.budgets()
    assert payload["operation_schedule"] == schedule
    assert payload["plan_digest"] == d5.plan_digest_of(schedule)
    digest = hashlib.sha256(canonical_authorization_bytes(payload)).hexdigest()
    assert digest == d5.staged_authorization_payload_digest(staged.directory)


def test_wire_requests_map_every_planned_exchange():
    """Every planned request is produced by the production wire builder."""
    plan = d5.freight_plan()
    schedule = d5.freight_schedule()
    seal = "a" * 64
    engine = SimpleNamespace(engine=73, quote=785)
    state = dict(site=None, engine=engine, vehicle=7)
    requests = [d5._freight_exchange_request(entry, seal, plan, state) for entry in schedule]
    assert len(requests) == PLANNED_FREIGHT_EXCHANGES == 15
    assert [request.request_id for request in requests] == list(FREIGHT_EXCHANGE_IDS)
    assert len({request.request_id for request in requests}) == 15
    downstream = {
        "vread",
        "order",
        "order-read",
        "monitor",
        "start",
        "load-watch",
        "transit-watch",
        "deliver-watch",
        "finance",
        "finish",
    }
    for entry, request in zip(schedule, requests, strict=True):
        op = entry["op"]
        assert request.op == op
        assert request.plan == seal
        assert request.company == plan.company
        assert request.max_cost == plan.max_cost
        assert request.route_digest == plan.route_digest
        if op == "site":
            assert request.route == plan.witness
        assert (request.pickup, request.delivery, request.depot) == (
            plan.pickup,
            plan.delivery,
            plan.depot,
        )
        assert (
            request.to_bytes()
            == FreightRequest.model_validate_json(request.to_bytes().decode()).to_bytes()
        )
        assert len(request.to_bytes()) <= MAX_FREIGHT_SEND_BYTES
        if op == "purchase":
            assert (request.engine, request.expected_cost) == (73, 785)
            assert (request.vehicle, request.order_index) == (-1, -1)
            assert (request.watch_ticks, request.watch_days) == (-1, -1)
        elif op in downstream:
            assert (request.engine, request.vehicle) == (73, 7)
        else:
            assert (request.engine, request.vehicle) == (-1, -1)
        if op == "order":
            assert request.order_index == entry["order_index"]
        else:
            assert request.order_index == -1
        if op == "load-watch":
            assert (request.watch_ticks, request.watch_days) == (
                entry["watch_ticks"],
                entry["watch_days"],
            )
        elif op in ("transit-watch", "deliver-watch"):
            assert request.watch_ticks == entry["watch_ticks"]
            assert request.watch_days == -1
        else:
            assert (request.watch_ticks, request.watch_days) == (-1, -1)


# --- protocol-5 request transport: live and replay share the 640 bound --------


def _production_site_request() -> FreightRequest:
    return d5._freight_exchange_request(
        d5.freight_schedule()[0],
        "a" * 64,
        d5.freight_plan(),
        dict(site=None, engine=None, vehicle=-1),
    )


def _site_readback(request: FreightRequest) -> FreightReadback:
    return FreightReadback(
        protocol=5,
        op="site",
        request_id=request.request_id,
        plan=request.plan,
        company=request.company,
        max_cost=request.max_cost,
        pickup=request.pickup,
        delivery=request.delivery,
        depot=request.depot,
        route_digest=request.route_digest,
        status="READY",
        funds=FUNDS_AT_D4_CLOSE,
        cost=0,
        paused=False,
        truck0=True,
        sid0=100,
        truck1=True,
        sid1=101,
        depot_ok=True,
        owner=0,
        pairs_ok=23,
        pair_total=23,
        accept=8,
        prod=100,
        wait=5,
        vehicles=0,
    )


def _readback_bytes(readback: FreightReadback) -> bytes:
    return json.dumps(
        readback.model_dump(mode="json", exclude_none=True),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


class _FakeFreightSession:
    """Records the live wire frame and yields one retained-shaped reply."""

    def __init__(self, reply: bytes) -> None:
        self.sent: list[bytes] = []
        self._reply = reply
        self._read = False

    async def send(self, frame: bytes) -> None:
        self.sent.append(frame)

    async def receive(self) -> bytes:
        if self._read:
            return b""
        self._read = True
        return self._reply


def test_production_site_request_is_526_bytes_and_passes_outbound_validation():
    """The real D5 site-00 request is accepted by the live protocol-5 path.

    The pre-fix default 512-byte encode/decode bound refused this exact
    request deterministically, before any frame reached OpenTTD.
    """
    request = _production_site_request()
    raw = request.to_bytes()
    assert request.request_id == "site-00"
    assert len(raw) == 526
    frame = d5.encode_freight_request(raw)
    assert frame[2] == d5.ADMIN_GAMESCRIPT
    assert len(frame) == len(raw) + 4  # 3-byte Admin header + terminating NUL
    assert len(frame) <= MAX_FREIGHT_SEND_BYTES
    assert len(frame) - 4 <= MAX_GAMESCRIPT_PAYLOAD_BYTES

    session = object.__new__(d5.FreightSecureSession)
    session._state = d5.AuthState.ACTIVE
    session.validate_outbound(frame)
    assert d5.decode_freight_request(frame[3:]) == raw
    assert FreightRequest.model_validate_json(frame[3:-1]).to_bytes() == raw


def test_live_exchange_sends_the_526_byte_site_request_under_the_640_bound(tmp_path):
    """The production exchange() sends the site request and parses its reply."""
    request = _production_site_request()
    raw = request.to_bytes()
    readback = _site_readback(request)
    reply = encode_admin_frame(d5.SERVER_GAMESCRIPT, _readback_bytes(readback) + b"\0")
    session = _FakeFreightSession(reply)
    parsed = asyncio.run(d5.exchange(session, request, tmp_path))
    assert session.sent == [d5.encode_freight_request(raw)]
    assert (tmp_path / "site-00-request.json").read_bytes() == raw
    assert parsed.request_id == "site-00" and parsed.status == "READY"
    assert parsed.funds == FUNDS_AT_D4_CLOSE


def test_replay_parses_and_reencodes_the_526_byte_site_request(tmp_path):
    """Retained-frame replay uses the same named protocol-5 request bound."""
    request = _production_site_request()
    raw = request.to_bytes()
    frame = d5.encode_freight_request(raw)
    (tmp_path / "frames.json").write_text(json.dumps([["outbound", frame.hex()]]))

    outbound, requests, replies, positions, _ = d5._parse_phase_frames(tmp_path)
    assert outbound == [frame]
    assert requests == [request]
    assert replies == []
    assert positions[raw] == 0
    # The replay verifier's unique-frame rule re-encodes the same payload.
    assert outbound.count(d5.encode_freight_request(raw)) == 1
    # Replayed requests run through the production plan verifier, and stale
    # evidence still fails closed.
    d5.verify_request_against_plan(requests[0], plan=d5.freight_plan(), seal="a" * 64)
    with pytest.raises(ValueError, match="prelaunch seal"):
        d5.verify_request_against_plan(requests[0], plan=d5.freight_plan(), seal="b" * 64)

    over = d5.encode_gamescript(raw + b" " * (641 - len(raw)), max_payload_bytes=1000)
    (tmp_path / "frames.json").write_text(json.dumps([["outbound", over.hex()]]))
    with pytest.raises(ValueError):
        d5._parse_phase_frames(tmp_path)


def test_d5_request_transport_accepts_exactly_640_and_refuses_641():
    """The shared request transport is inclusive at 640 and closed at 641."""
    assert MAX_FREIGHT_REQUEST_BYTES == 640
    raw = _production_site_request().to_bytes()
    at_limit = raw + b" " * (640 - len(raw))
    assert len(at_limit) == 640
    frame = d5.encode_freight_request(at_limit)
    assert len(frame) == 644
    assert frame == encode_gamescript(at_limit, max_payload_bytes=MAX_FREIGHT_REQUEST_BYTES)
    assert d5.decode_freight_request(frame[3:]) == at_limit
    assert d5.decode_freight_request(frame[3:]) == decode_gamescript(
        frame[3:], max_payload_bytes=MAX_FREIGHT_REQUEST_BYTES
    )
    session = object.__new__(d5.FreightSecureSession)
    session._state = d5.AuthState.ACTIVE
    session.validate_outbound(frame)
    with pytest.raises(ValueError):
        d5.encode_freight_request(at_limit + b" ")
    with pytest.raises(ValueError):
        d5.decode_freight_request(at_limit + b" \0")
    for malformed in (b"\xff\0", b"x\0\0", b"x", b"\0"):
        with pytest.raises(ValueError):
            d5.decode_freight_request(malformed)


def test_generic_transport_default_stays_at_512_bytes():
    """Only protocol 5 opts into 640; the generic transport default is 512."""
    assert MAX_PAYLOAD_BYTES == 512
    raw = _production_site_request().to_bytes()
    with pytest.raises(ValueError):
        encode_gamescript(raw)
    assert len(encode_gamescript(raw[:512])) == 516


# --- launch lineage and never-consumed behavior -------------------------------


def test_launch_marker_schema_continues_the_shared_d2_lineage():
    """The staged launch marker is the shared D2 schema re-scoped additively."""
    assert ClearingNativeBackend.launch_marker_schema == "d2-clearing-native-launch-consumed"
    assert d5.FreightNativeBackend.launch_marker_schema == (d5.D5_FREIGHT_LAUNCH_CONSUMED_SCHEMA)
    assert d5.D5_FREIGHT_LAUNCH_CONSUMED_SCHEMA == "d5-native-launch-consumed"


def test_unconsumed_candidate_verifies_fail_closed(staged):
    """No candidate may claim a receipt before its one-shot consumption."""
    assert not (staged.directory / "CLAIM.json").exists()
    verdict = d5.verify_freight_attempt(staged.directory)
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
    assert d5.exit_status(dict(verified=True, status="NATIVE_FREIGHT_VERIFIED")) == 0
    for status in (
        "FAILED",
        "FAILED_CLEANUP",
        "PHASE_HALTED_PREFIX_PRESERVED",
        "NOT_DISPATCHED",
    ):
        assert d5.exit_status(dict(verified=False, status=status)) == 1
