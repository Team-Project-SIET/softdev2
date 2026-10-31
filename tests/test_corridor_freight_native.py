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
import contextlib
import hashlib
import json
import shutil
import sys
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
    OF_FULL_LOAD,
    OF_NO_LOAD,
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


def test_preflight_rejects_a_staged_world_that_is_not_the_pinned_after_save(tmp_path):
    """M1: a re-sealed world digest must equal the independent prerequisite binding."""
    prepared = d5.prepare_candidate(tmp_path / "candidate")
    directory = prepared.directory
    try:
        prelaunch = directory / "PRELAUNCH.json"
        original = prelaunch.read_bytes()
        metadata = json.loads(original)
        metadata["world"]["save_sha256"] = "0" * 64
        prelaunch.write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n")
        _restamp_prelaunch(directory)
        with pytest.raises(ValueError, match="pinned prerequisite after-save"):
            d5.preflight(prepared)
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
        "watch_seconds": 60,
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
    assert (
        d5.exit_status(
            dict(
                verified=True,
                status="NATIVE_FREIGHT_VERIFIED",
                cleanup_complete=True,
            )
        )
        == 0
    )
    for status in (
        "FAILED",
        "FAILED_CLEANUP",
        "PHASE_HALTED_PREFIX_PRESERVED",
        "NOT_DISPATCHED",
    ):
        assert d5.exit_status(dict(verified=False, status=status, cleanup_complete=True)) == 1
    # A stale success flag, an uncertified cleanup, or a mismatched terminal
    # status can never make the runner exit zero.
    assert (
        d5.exit_status(
            dict(
                verified=True,
                status="NATIVE_FREIGHT_VERIFIED",
                cleanup_complete=False,
            )
        )
        == 1
    )
    assert d5.exit_status(dict(verified=True, status="FAILED_CLEANUP", cleanup_complete=True)) == 1
    assert d5.exit_status(dict(verified=True, status="NATIVE_FREIGHT_VERIFIED")) == 1


def test_cleanup_failure_after_success_denies_the_verified_result():
    result = dict(verified=True, status="NATIVE_FREIGHT_VERIFIED", cleanup_complete=True)
    d5.apply_cleanup_outcome(result, complete=False)
    assert result["verified"] is False
    assert result["status"] == "FAILED_CLEANUP"
    assert result["prior_status"] == "NATIVE_FREIGHT_VERIFIED"
    assert result["cleanup_complete"] is False
    assert result["cleanup_failure"] is True
    assert "no verified receipt is possible" in result["error"]
    assert d5.exit_status(result) == 1
    # Repeating the terminal transition is idempotent.
    d5.apply_cleanup_outcome(result, complete=False)
    assert result["status"] == "FAILED_CLEANUP"
    assert result["prior_status"] == "NATIVE_FREIGHT_VERIFIED"


def test_cleanup_failure_after_an_unsuccessful_attempt_preserves_its_status():
    result = dict(
        verified=False,
        status="PHASE_HALTED_PREFIX_PRESERVED",
        cleanup_complete=True,
        error="ValueError: halted exchange",
    )
    d5.apply_cleanup_outcome(result, complete=False)
    assert result["verified"] is False
    assert result["status"] == "PHASE_HALTED_PREFIX_PRESERVED"
    assert result["cleanup_complete"] is False
    assert result["cleanup_failure"] is True
    assert result["error"] == "ValueError: halted exchange"
    assert d5.exit_status(result) == 1
    # A clean cleanup never resurrects an unsuccessful attempt.
    d5.apply_cleanup_outcome(result, complete=True)
    assert result["cleanup_failure"] is True  # sticky diagnostic from the earlier call
    assert d5.exit_status(result) == 1


def test_deny_verification_preserves_the_original_error():
    result = dict(verified=True, status="NATIVE_FREIGHT_VERIFIED")
    result["error"] = "RuntimeError: original failure"
    d5.deny_verification(result, status="FAILED", message="post-check denied success")
    assert result["verified"] is False
    assert result["status"] == "FAILED"
    assert result["prior_status"] == "NATIVE_FREIGHT_VERIFIED"
    assert result["error"] == "RuntimeError: original failure"
    assert result["denial_errors"] == ["post-check denied success"]


# --- H2: exchange timing is derived from the phase and overall budgets -------


def _watch_request() -> tuple[FreightRequest, FreightReadback]:
    entry = d5.freight_schedule()[10]
    state = dict(site=None, engine=SimpleNamespace(engine=73, quote=785), vehicle=7)
    request = d5._freight_exchange_request(entry, "a" * 64, d5.freight_plan(), state)
    readback = FreightReadback(
        protocol=5,
        op="load-watch",
        request_id=request.request_id,
        plan=request.plan,
        company=request.company,
        max_cost=request.max_cost,
        pickup=request.pickup,
        delivery=request.delivery,
        depot=request.depot,
        route_digest=request.route_digest,
        engine=request.engine,
        vehicle=request.vehicle,
        watch_ticks=request.watch_ticks,
        watch_days=request.watch_days,
        status="LOADED",
        funds=FUNDS_AT_D4_CLOSE,
        cost=0,
        load=20,
        capacity=20,
        wait=3,
        tick=100,
        day=3,
        paused=False,
    )
    return request, readback


def _reply_frame(readback: FreightReadback) -> bytes:
    return encode_admin_frame(d5.SERVER_GAMESCRIPT, _readback_bytes(readback) + b"\0")


def test_exchange_timeout_is_derived_from_the_phase_budget():
    table = d5.budgets()
    site = _production_site_request()
    watch, _ = _watch_request()
    assert d5.exchange_timeout_seconds(site, budget_table=table) == table["request_seconds"]
    assert d5.exchange_timeout_seconds(watch, budget_table=table) == (
        table["watch_seconds"] + d5.FREIGHT_EXCHANGE_MARGIN_SECONDS
    )
    assert d5.exchange_timeout_seconds(watch, budget_table=table) > 10


class _RecordingTimeout:
    def __init__(self) -> None:
        self.seen: list[float] = []

    def __call__(self, seconds: float):
        self.seen.append(seconds)
        return contextlib.nullcontext()


class _Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_watch_exchange_inside_its_budget_is_not_killed_at_ten_seconds(tmp_path):
    """A valid watch exchange gets its full window budget, not the old 10 s."""
    request, readback = _watch_request()
    session = _FakeFreightSession(_reply_frame(readback))
    timeout = _RecordingTimeout()
    clock = _Clock()
    # The logical exchange consumes 11 s, still inside the permitted window.
    clock.now += 11
    parsed = asyncio.run(
        d5.exchange(
            session,
            request,
            tmp_path,
            budget_table=d5.budgets(),
            overall_deadline=clock.now + 100,
            clock=clock,
            timeout_factory=timeout,
        )
    )
    assert parsed.request_id == "load-00" and parsed.status == "LOADED"
    assert timeout.seen == [d5.budgets()["watch_seconds"] + d5.FREIGHT_EXCHANGE_MARGIN_SECONDS]


class _ExpiringTimeout:
    def __call__(self, seconds: float):
        outer = self

        class _Expire:
            async def __aenter__(self):
                raise TimeoutError("simulated expiry")

            async def __aexit__(self, *exc):
                return False

        assert seconds > 0 and outer is not None
        return _Expire()


def test_exchange_exceeding_its_permitted_budget_fails_closed(tmp_path):
    request, _ = _watch_request()
    session = _FakeFreightSession(b"")
    with pytest.raises(TimeoutError, match="exceeded its"):
        asyncio.run(
            d5.exchange(
                session,
                request,
                tmp_path,
                budget_table=d5.budgets(),
                timeout_factory=_ExpiringTimeout(),
            )
        )
    assert (tmp_path / "load-00-request.json").is_file()
    assert not (tmp_path / "load-00-response.json").exists()


def test_exchange_is_clamped_to_the_remaining_overall_budget(tmp_path):
    request, readback = _watch_request()
    clock = _Clock()
    timeout = _RecordingTimeout()
    session = _FakeFreightSession(_reply_frame(readback))
    asyncio.run(
        d5.exchange(
            session,
            request,
            tmp_path,
            budget_table=d5.budgets(),
            overall_deadline=clock.now + 3,
            clock=clock,
            timeout_factory=timeout,
        )
    )
    assert timeout.seen == [3.0]


def test_exhausted_overall_watch_window_refuses_before_sending(tmp_path):
    request, _ = _watch_request()
    clock = _Clock()
    session = _FakeFreightSession(b"")
    with pytest.raises(TimeoutError, match="overall watch window exhausted"):
        asyncio.run(
            d5.exchange(
                session,
                request,
                tmp_path,
                budget_table=d5.budgets(),
                overall_deadline=clock.now - 1,
                clock=clock,
            )
        )
    assert session.sent == []


class _CancellingSession:
    async def send(self, frame: bytes) -> None:
        return None

    async def receive(self) -> bytes:
        raise asyncio.CancelledError


def test_exchange_cancellation_propagates_without_a_success(tmp_path):
    request, _ = _watch_request()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(d5.exchange(_CancellingSession(), request, tmp_path))
    assert not (tmp_path / "load-00-response.json").exists()


class _LateResponseSession:
    def __init__(self, reply: bytes) -> None:
        self._reply = reply

    async def send(self, frame: bytes) -> None:
        return None

    async def receive(self) -> bytes:
        return self._reply


def test_exchange_refuses_a_stale_late_response_for_another_request(tmp_path):
    request, _ = _watch_request()
    stale = _production_site_request()
    stale_readback = _site_readback(stale)
    with pytest.raises(ValueError, match="correlation mismatch"):
        asyncio.run(
            d5.exchange(_LateResponseSession(_reply_frame(stale_readback)), request, tmp_path)
        )


class _DuplicateFrameSession:
    def __init__(self, reply: bytes) -> None:
        self._reply = reply

    async def send(self, frame: bytes) -> None:
        return None

    async def receive(self) -> bytes:
        return self._reply + self._reply


def test_exchange_refuses_duplicate_response_frames(tmp_path):
    request, readback = _watch_request()
    with pytest.raises(ValueError, match="duplicate freight-proof response frame"):
        asyncio.run(d5.exchange(_DuplicateFrameSession(_reply_frame(readback)), request, tmp_path))


class _PartialThenExpiredSession:
    def __init__(self) -> None:
        self._calls = 0

    async def send(self, frame: bytes) -> None:
        return None

    async def receive(self) -> bytes:
        self._calls += 1
        if self._calls == 1:
            return b"\x01\x02"
        raise TimeoutError("expired after partial read")


def test_exchange_refuses_partial_reads_and_late_timeouts(tmp_path):
    request, _ = _watch_request()
    with pytest.raises(TimeoutError, match="exceeded its"):
        asyncio.run(d5.exchange(_PartialThenExpiredSession(), request, tmp_path))
    assert not (tmp_path / "load-00-response.json").exists()


# --- C1/H1/H3 + consumed-frame replay: synthetic packed attempt fixtures ----
#
# These fixtures are explicitly synthetic. They copy a freshly staged candidate
# (whose prerequisite is the real pinned D4 attempt) and fabricate only the
# missing post-launch artifacts: fifteen correlated protocol-5 frames, the
# runtime welcome, cleanup certification and a receipt. No native process,
# AdminPort session, candidate claim, signature or Gate C authorization is
# created. Because no authorized D5 attempt exists in the repository, the
# operator-authorization gate is the one seam monkeypatched in the success
# tests; every prerequisite, identity, digest, phase, frame and cleanup fact is
# otherwise verified by the production replay path.


def _synthetic_readback(
    request: FreightRequest,
    status: str,
    funds: int,
    *,
    cost: int = 0,
    engine: int | None = None,
    vehicle: int | None = None,
    **observations,
) -> FreightReadback:
    return FreightReadback(
        protocol=5,
        op=request.op,
        request_id=request.request_id,
        plan=request.plan,
        company=request.company,
        max_cost=request.max_cost,
        pickup=request.pickup,
        delivery=request.delivery,
        depot=request.depot,
        route_digest=request.route_digest,
        engine=request.engine if engine is None else engine,
        vehicle=request.vehicle if vehicle is None else vehicle,
        expected_cost=request.expected_cost,
        order_index=request.order_index,
        watch_ticks=request.watch_ticks,
        watch_days=request.watch_days,
        status=status,
        funds=funds,
        cost=cost,
        **observations,
    )


def _consumed_freight_exchanges(
    seal: str,
) -> tuple[list[tuple[FreightRequest, FreightReadback]], dict]:
    plan = d5.freight_plan()
    schedule = d5.freight_schedule()
    state = dict(site=None, engine=SimpleNamespace(engine=73, quote=785), vehicle=7)
    requests = [d5._freight_exchange_request(entry, seal, plan, state) for entry in schedule]
    funds = FUNDS_AT_D4_CLOSE
    after_purchase = funds - 785
    exchanges = []
    for request in requests:
        op = request.op
        if op == "site":
            readback = _synthetic_readback(
                request,
                "READY",
                funds,
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
        elif op == "engine":
            readback = _synthetic_readback(
                request,
                "READY",
                funds,
                cost=785,
                engine=73,
                available=True,
                compatible=True,
                capacity=20,
                cargo=1,
            )
        elif op == "purchase":
            readback = _synthetic_readback(
                request, "BUILT", after_purchase, cost=785, engine=73, vehicle=7
            )
        elif op == "vread" and request.request_id == "vread-00":
            readback = _synthetic_readback(
                request,
                "READ",
                after_purchase,
                owner=0,
                location=d5.DEPOT_TILE,
                capacity=20,
                cargo=1,
                state="IN_DEPOT",
                in_depot=True,
                speed=0,
            )
        elif op == "vread" and request.request_id == "vread-01":
            readback = _synthetic_readback(
                request,
                "READ",
                after_purchase,
                owner=0,
                location=d5.PICKUP_STOP_TILE,
                capacity=20,
                cargo=1,
                state="RUNNING",
                in_depot=False,
                speed=80,
            )
        elif op == "order":
            index = request.order_index
            readback = _synthetic_readback(
                request,
                "ORDERED",
                after_purchase,
                dest=100 if index == 0 else 101,
                flags=OF_FULL_LOAD if index == 0 else OF_NO_LOAD,
                goto=True,
            )
        elif op == "order-read":
            readback = _synthetic_readback(
                request,
                "ORDER_SET_VERIFIED",
                after_purchase,
                order_len=2,
                dest0=100,
                flags0=OF_FULL_LOAD,
                goto0=True,
                dest1=101,
                flags1=OF_NO_LOAD,
                goto1=True,
            )
        elif op == "monitor":
            readback = _synthetic_readback(
                request,
                "ARMED",
                after_purchase,
                pickup_amount=0,
                delivery_amount=0,
                income=5000,
                delivered=10,
            )
        elif op == "start":
            readback = _synthetic_readback(
                request, "STARTED", after_purchase, state="RUNNING", speed=40
            )
        elif op == "load-watch":
            readback = _synthetic_readback(
                request,
                "LOADED",
                after_purchase,
                load=20,
                capacity=20,
                wait=3,
                tick=100,
                day=3,
                paused=False,
            )
        elif op == "transit-watch":
            readback = _synthetic_readback(
                request,
                "AT_DELIVERY",
                after_purchase,
                position=plan.delivery,
                progress=len(plan.witness) - 1,
                load=20,
                tick=200,
                day=4,
                paused=False,
            )
        elif op == "deliver-watch":
            readback = _synthetic_readback(
                request,
                "DELIVERED",
                after_purchase,
                load=0,
                pickup_amount=20,
                delivery_amount=20,
                tick=300,
                day=5,
                paused=False,
            )
        elif op == "finance":
            readback = _synthetic_readback(
                request,
                "FINANCE_VERIFIED",
                after_purchase,
                income=6000,
                delivered=20,
                last_accepted=5,
            )
        elif op == "finish":
            readback = _synthetic_readback(
                request,
                "PHASE_STOPPED",
                after_purchase,
                state="STOPPED",
                speed=0,
                in_depot=False,
                stop_issued=True,
            )
        else:  # pragma: no cover - the fixed schedule exhausts the ops
            raise AssertionError(op)
        exchanges.append((request, readback))
    return exchanges, plan


def _write_manifest(directory: Path) -> None:
    (directory / "artifact-manifest.sha256").write_text(d5.manifest(directory))


def _reseal(directory: Path) -> None:
    (directory / "PRELAUNCH.sha256").write_text(sha256(directory / "PRELAUNCH.json") + "\n")
    claim_path = directory / "CLAIM.json"
    if claim_path.is_file():
        claim = json.loads(claim_path.read_text())
        claim["prelaunch_digest"] = sha256(directory / "PRELAUNCH.json")
        claim_path.write_text(json.dumps(claim, sort_keys=True, indent=2) + "\n")


@pytest.fixture(scope="module")
def consumed_attempt(tmp_path_factory):
    prepared = d5.prepare_candidate(tmp_path_factory.mktemp("d5-consumed") / "candidate")
    directory = prepared.directory
    seal = sha256(directory / "PRELAUNCH.json")
    exchanges, plan = _consumed_freight_exchanges(seal)
    frames = []
    for request, readback in exchanges:
        response = _readback_bytes(readback)
        (directory / (request.request_id + "-request.json")).write_bytes(request.to_bytes())
        (directory / (request.request_id + "-response.json")).write_bytes(response)
        frames.append(["outbound", d5.encode_freight_request(request.to_bytes()).hex()])
        frames.append(["inbound", _reply_frame(readback).hex()])
    (directory / "frames.json").write_text(json.dumps(frames))
    (directory / "session-before.sav").write_bytes(b"synthetic session-before fixture")
    (directory / "after.sav").write_bytes(b"synthetic after fixture")
    phase = d5.freight_phase_outcome(exchanges, prelaunch_digest=seal, plan=plan)
    cycle = d5.verify_freight_cycle(exchanges, prelaunch_digest=seal, plan=plan)
    (directory / "receipt.json").write_text(
        json.dumps(
            dict(
                phase,
                cycle=cycle,
                before_save_sha256=sha256(directory / "session-before.sav"),
                after_save_sha256=sha256(directory / "after.sav"),
            ),
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    (directory / "runtime-identity.json").write_text(
        json.dumps(
            dict(
                auth="X25519_AuthorizedKey",
                encrypted=True,
                welcome=dict(d5.retained_welcome(), dedicated=True),
                pid=4242,
            ),
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    (directory / "cleanup.json").write_text(
        json.dumps(
            dict(
                reaped=True,
                sockets_closed=True,
                workspace_disposed=True,
                credential_removed=True,
                returncode=0,
            ),
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    (directory / "CLAIM.json").write_text(
        json.dumps(
            dict(
                prelaunch_digest=seal,
                consumed=True,
                launches_allowed=1,
                retries=0,
                authorization_schema=d5.CLAIM_AUTHORIZATION_EVIDENCE_SCHEMA,
                authorization_sha256="f" * 64,
                operator_key_identity="synthetic-test-fixture",
            ),
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    (directory / "result.json").write_text(
        json.dumps(
            dict(
                preflight="PASS",
                native_launches=1,
                connections=1,
                requests=15,
                exchanges=[request.request_id for request, _ in exchanges],
                last_status="PHASE_STOPPED",
                command_accepted=True,
                state_changed=True,
                verified=True,
                status="NATIVE_FREIGHT_VERIFIED",
                halt=None,
                returncode=0,
                cleanup_complete=True,
            ),
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    _write_manifest(directory)
    yield directory, exchanges, seal, plan
    prepared.spec.workspace.close()


def _copy_attempt(source: Path, destination: Path) -> Path:
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns("isolated", "freeze-probe"),
    )
    return destination


def _authorization_passthrough(monkeypatch):
    monkeypatch.setattr(d5, "replay_authorization_state", lambda *args, **kwargs: None)


def test_replay_verifies_a_fully_consumed_valid_frame_sequence(consumed_attempt, monkeypatch):
    directory, exchanges, seal, _ = consumed_attempt
    _authorization_passthrough(monkeypatch)
    verdict = d5.verify_freight_attempt(directory)
    assert verdict["verification"] == "RECEIPT_VERIFIED"
    assert verdict["receipt"]["cycle"]["verification"] == "FREIGHT_CYCLE_VERIFIED"
    assert len(verdict["receipt"]["cycle"]["receipts"]) == PLANNED_FREIGHT_EXCHANGES
    assert d5.verdict_exit_status(verdict) == 0
    outbound, requests, replies, _, _ = d5._parse_phase_frames(directory)
    assert len(outbound) == len(requests) == len(replies) == PLANNED_FREIGHT_EXCHANGES
    assert [request.request_id for request in requests] == list(FREIGHT_EXCHANGE_IDS)
    assert outbound == [d5.encode_freight_request(request.to_bytes()) for request, _ in exchanges]


def test_replay_refuses_missing_duplicated_out_of_order_and_altered_frames(
    consumed_attempt, tmp_path, monkeypatch
):
    source, _, _, _ = consumed_attempt
    _authorization_passthrough(monkeypatch)

    missing = _copy_attempt(source, tmp_path / "missing")
    (missing / "deliver-00-response.json").unlink()
    _write_manifest(missing)
    with pytest.raises(ValueError):
        d5.verify_freight_attempt(missing)

    duplicated = _copy_attempt(source, tmp_path / "duplicated")
    frames = json.loads((duplicated / "frames.json").read_text())
    frames.insert(1, list(frames[0]))
    (duplicated / "frames.json").write_text(json.dumps(frames))
    _write_manifest(duplicated)
    with pytest.raises(ValueError):
        d5.verify_freight_attempt(duplicated)

    out_of_order = _copy_attempt(source, tmp_path / "out-of-order")
    frames = json.loads((out_of_order / "frames.json").read_text())
    frames[0], frames[2] = frames[2], frames[0]
    (out_of_order / "frames.json").write_text(json.dumps(frames))
    _write_manifest(out_of_order)
    with pytest.raises(ValueError, match="precedes its own request"):
        d5.verify_freight_attempt(out_of_order)

    altered = _copy_attempt(source, tmp_path / "altered")
    response_path = altered / "load-00-response.json"
    readback = json.loads(response_path.read_text())
    readback["load"] = 19
    response_path.write_text(json.dumps(readback, sort_keys=True, separators=(",", ":")))
    _write_manifest(altered)
    with pytest.raises(ValueError):
        d5.verify_freight_attempt(altered)


def test_replay_fails_closed_on_wrong_source_save_digest(consumed_attempt, tmp_path, monkeypatch):
    source, _, _, _ = consumed_attempt
    _authorization_passthrough(monkeypatch)
    attempt = _copy_attempt(source, tmp_path / "wrong-source")
    metadata = json.loads((attempt / "PRELAUNCH.json").read_text())
    metadata["world"]["save_sha256"] = "0" * 64
    (attempt / "PRELAUNCH.json").write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n")
    _reseal(attempt)
    _write_manifest(attempt)
    with pytest.raises(ValueError, match="pinned prerequisite|after-save"):
        d5.verify_freight_attempt(attempt)


def test_replay_fails_closed_on_wrong_pinned_d4_digest(consumed_attempt, monkeypatch):
    directory, _, _, _ = consumed_attempt
    _authorization_passthrough(monkeypatch)
    monkeypatch.setattr(d5, "PINNED_PREREQUISITE_AFTER_SAVE", "0" * 64)
    with pytest.raises(ValueError, match="pinned|authoritative"):
        d5.verify_freight_attempt(directory)


def test_replay_fails_closed_on_incomplete_world_welcome(consumed_attempt, tmp_path, monkeypatch):
    source, _, _, _ = consumed_attempt
    _authorization_passthrough(monkeypatch)
    attempt = _copy_attempt(source, tmp_path / "welcome")
    runtime = json.loads((attempt / "runtime-identity.json").read_text())
    del runtime["welcome"]["width"]
    (attempt / "runtime-identity.json").write_text(json.dumps(runtime, sort_keys=True, indent=2))
    _write_manifest(attempt)
    with pytest.raises(ValueError, match="welcome"):
        d5.verify_freight_attempt(attempt)


def test_replay_fails_closed_on_candidate_receipt_identity_mismatch(
    consumed_attempt, tmp_path, monkeypatch
):
    source, _, _, _ = consumed_attempt
    _authorization_passthrough(monkeypatch)
    attempt = _copy_attempt(source, tmp_path / "identity")
    metadata = json.loads((attempt / "PRELAUNCH.json").read_text())
    metadata["attempt"] = "D5-FREIGHT-9"
    (attempt / "PRELAUNCH.json").write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n")
    _reseal(attempt)
    _write_manifest(attempt)
    with pytest.raises(ValueError, match="attempt identity"):
        d5.verify_freight_attempt(attempt)

    tampered_receipt = _copy_attempt(source, tmp_path / "receipt")
    receipt = json.loads((tampered_receipt / "receipt.json").read_text())
    receipt["after_save_sha256"] = "0" * 64
    (tampered_receipt / "receipt.json").write_text(json.dumps(receipt, sort_keys=True, indent=2))
    _write_manifest(tampered_receipt)
    with pytest.raises(ValueError, match="receipt replay mismatch"):
        d5.verify_freight_attempt(tampered_receipt)


def test_verify_cli_exits_nonzero_for_unverified_verdicts(staged, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["prog", "verify", str(staged.directory)])
    with pytest.raises(SystemExit) as exit_info:
        d5.main()
    assert exit_info.value.code == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["verification"] == "AUTHORIZATION_UNVERIFIED"


def test_verify_cli_exits_zero_only_for_a_verified_receipt(consumed_attempt, monkeypatch, capsys):
    directory, _, _, _ = consumed_attempt
    _authorization_passthrough(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["prog", "verify", str(directory)])
    with pytest.raises(SystemExit) as exit_info:
        d5.main()
    assert exit_info.value.code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["verification"] == "RECEIPT_VERIFIED"


def test_verify_cli_cannot_turn_errors_or_malformed_input_into_success(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "verify", str(tmp_path / "missing")])
    with pytest.raises(Exception) as error:
        d5.main()
    assert not isinstance(error.value, SystemExit)

    monkeypatch.setattr(sys, "argv", ["prog", "not-a-command", str(tmp_path)])
    with pytest.raises(SystemExit) as exit_info:
        d5.main()
    assert exit_info.value.code == 2


def test_replay_preserves_a_failed_cleanup_as_failed_evidence(
    consumed_attempt, tmp_path, monkeypatch
):
    source, _, _, _ = consumed_attempt
    _authorization_passthrough(monkeypatch)
    attempt = _copy_attempt(source, tmp_path / "failed-cleanup")
    result = json.loads((attempt / "result.json").read_text())
    result["status"] = "FAILED_CLEANUP"
    result["verified"] = False
    result["cleanup_complete"] = False
    result["cleanup_failure"] = True
    result["error"] = "ValueError: cleanup was not certified; no verified receipt is possible"
    (attempt / "result.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    cleanup = json.loads((attempt / "cleanup.json").read_text())
    cleanup["workspace_disposed"] = False
    cleanup["verification_error"] = "cleanup incomplete"
    (attempt / "cleanup.json").write_text(json.dumps(cleanup, sort_keys=True, indent=2))
    _write_manifest(attempt)
    verdict = d5.verify_freight_attempt(attempt)
    assert verdict["verification"] == "ATTEMPT_FAILED_EVIDENCE_PRESERVED"
    assert verdict["result_status"] == "FAILED_CLEANUP"
    assert verdict["cleanup_complete"] is False
    assert d5.verdict_exit_status(verdict) == 1


def test_replay_refuses_a_manifest_that_omits_a_retained_file(
    consumed_attempt, tmp_path, monkeypatch
):
    """L4: a rewritten manifest that silently drops a file is refused."""
    source, _, _, _ = consumed_attempt
    _authorization_passthrough(monkeypatch)
    attempt = _copy_attempt(source, tmp_path / "non-exhaustive-manifest")
    lines = (attempt / "artifact-manifest.sha256").read_text().splitlines()
    kept = [line for line in lines if not line.endswith("  cleanup.json")]
    assert len(kept) == len(lines) - 1
    (attempt / "artifact-manifest.sha256").write_text("\n".join(kept) + "\n")
    with pytest.raises(ValueError, match="not exhaustive"):
        d5.verify_freight_attempt(attempt)


def test_replay_refuses_a_malformed_orphan_response_file(consumed_attempt, tmp_path, monkeypatch):
    """L8: an unparsable response file with no matching request fails closed."""
    source, _, _, _ = consumed_attempt
    _authorization_passthrough(monkeypatch)
    attempt = _copy_attempt(source, tmp_path / "orphan-response")
    (attempt / "orphan-99-response.json").write_text("{not json")
    _write_manifest(attempt)
    with pytest.raises(ValueError, match="not a parseable readback"):
        d5.verify_freight_attempt(attempt)


def test_replay_fails_closed_on_optimizer_plan_digest_drift(
    consumed_attempt, tmp_path, monkeypatch
):
    source, _, _, _ = consumed_attempt
    _authorization_passthrough(monkeypatch)
    attempt = _copy_attempt(source, tmp_path / "optimizer-drift")
    metadata = json.loads((attempt / "PRELAUNCH.json").read_text())
    metadata["plan_policy"]["optimizer"]["scenario_digest"] = "0" * 64
    (attempt / "PRELAUNCH.json").write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n")
    _reseal(attempt)
    _write_manifest(attempt)
    with pytest.raises(ValueError, match="optimizer pin scenario_digest"):
        d5.verify_freight_attempt(attempt)
