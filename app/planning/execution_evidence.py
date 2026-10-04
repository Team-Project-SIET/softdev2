"""Independently check P06 terminal execution receipts against P02/P03 identities."""

from __future__ import annotations

import json
import re
from enum import StrEnum
from typing import Literal

from pydantic import ValidationError

from app.planning.domain import (
    Contract,
    Digest,
    ExecutionPlan,
    Identifier,
    Mode,
    NonNegativeInt,
    PlanningScenario,
    RailComposition,
    RoadComposition,
)
from app.planning.execution import ExecutionBindings, execution_payload
from app.planning.runtime_world import (
    parse_runtime_world_evidence,
    runtime_projection_from_manifest,
)
from app.planning.serialization import _reject_constant, _reject_duplicate_pairs, plan_hash
from app.planning.setup_evidence import SetupEvidenceError, parse_setup_evidence


class ExecutionStage(StrEnum):
    PLAN_ACCEPTED = "PLAN_ACCEPTED"
    WORLD_VALIDATED = "WORLD_VALIDATED"
    INFRASTRUCTURE_STARTED = "INFRASTRUCTURE_STARTED"
    INFRASTRUCTURE_COMPLETED = "INFRASTRUCTURE_COMPLETED"
    FLEET_STARTED = "FLEET_STARTED"
    FLEET_COMPLETED = "FLEET_COMPLETED"
    ORDERS_STARTED = "ORDERS_STARTED"
    ORDERS_COMPLETED = "ORDERS_COMPLETED"
    SETUP_VERIFIED = "SETUP_VERIFIED"
    EXECUTION_RECEIPT_EMITTED = "EXECUTION_RECEIPT_EMITTED"


class ActionExecution(Contract):
    construction_id: Identifier
    candidate_id: Identifier
    mode: Mode
    kind: Literal["station", "depot", "segment"]
    tiles: tuple[NonNegativeInt, ...]
    station_id: NonNegativeInt | None
    depot_tile: NonNegativeInt | None


class CreatedVehicle(Contract):
    vehicle_id: NonNegativeInt
    group_id: Identifier
    route_id: Identifier
    engine_id: NonNegativeInt
    role: Literal["road", "locomotive", "wagon"]


class ExecutedFleet(Contract):
    group_id: Identifier
    vehicle_id: NonNegativeInt
    engine_ids: tuple[NonNegativeInt, ...]
    capacity: NonNegativeInt
    length_16ths: NonNegativeInt


class ExecutedOrders(Contract):
    group_id: Identifier
    route_id: Identifier
    vehicle_id: NonNegativeInt
    targets: tuple[NonNegativeInt, ...]
    flags: tuple[NonNegativeInt, ...]
    assigned: bool


class NativeGroupExecution(Contract):
    group_id: Identifier
    runtime_id: NonNegativeInt
    mode: Mode
    vehicle_count: NonNegativeInt
    verified: bool


class ExecutionReceipt(Contract):
    schema_version: Literal[1]
    executor_version: Literal["1"]
    plan_hash: Digest
    world_fingerprint: Digest
    runtime_world_hash: Digest | None
    result: Literal["success", "failed"]
    code: Literal["NONE", "PRE_EXECUTION_FAILURE", "PARTIAL_EXECUTION"]
    failure_reason: Identifier | None
    failed_stage: ExecutionStage | None
    failed_entity: Identifier | None
    stages: tuple[ExecutionStage, ...]
    actions: tuple[ActionExecution, ...]
    created_vehicles: tuple[CreatedVehicle, ...]
    fleet: tuple[ExecutedFleet, ...]
    orders: tuple[ExecutedOrders, ...]
    native_groups: tuple[NativeGroupExecution, ...]


class ExecutionEvidenceError(ValueError):
    pass


_INFO = re.compile(r"^dbg: \[script\] \[(\d+)\] \[I\] (.*)$")
_PREFIX = "P03_EXECUTOR_AI|P06_"
_TERMINAL = _PREFIX + "EXECUTION_V1|"
_STAGE = _PREFIX + "STAGE_V1|"
_EVENT = _PREFIX + "EVENT_V1|"
_MAX_LOG = 1024 * 1024
_MAX_RECORD = 65536


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise ExecutionEvidenceError(message)


def _json(text: str) -> dict:
    _require(len(text.encode()) <= _MAX_RECORD, "execution record too large")
    try:
        result = json.loads(
            text, object_pairs_hook=_reject_duplicate_pairs, parse_constant=_reject_constant
        )
    except ValueError as error:
        raise ExecutionEvidenceError("malformed execution JSON") from error
    _require(isinstance(result, dict), "execution record must be object")
    return result


def parse_execution_evidence(
    log: str, plan: ExecutionPlan, scenario: PlanningScenario, bindings: ExecutionBindings
) -> ExecutionReceipt:
    """Require one correlated terminal and exact expected decisions, including partial prefixes.

    Runtime identity is recomputed from P03 observed facts, never copied into Python
    from an expected/echoed hash. Receipts describe setup, not delivery performance.
    """
    _require(len(log.encode()) <= _MAX_LOG, "execution log too large")
    payload = execution_payload(plan, scenario, bindings)
    rows = [
        (i, int(m[1]), m[2])
        for i, line in enumerate(log.splitlines())
        if (m := _INFO.fullmatch(line))
    ]
    terminals = [r for r in rows if r[2].startswith(_TERMINAL)]
    _require(len(terminals) == 1, "expected exactly one terminal execution receipt")
    terminal = terminals[0]
    raw = _json(terminal[2].removeprefix(_TERMINAL))
    try:
        receipt = ExecutionReceipt.model_validate_json(json.dumps(raw))
        setup = parse_setup_evidence(log, plan, scenario)
    except (ValueError, ValidationError) as error:
        raise ExecutionEvidenceError("invalid execution/setup receipt") from error
    _require(
        receipt.plan_hash == plan_hash(plan)
        and receipt.world_fingerprint == scenario.world_fingerprint,
        "execution identity mismatch",
    )
    p06 = [r for r in rows if r[2].startswith(_PREFIX)]
    _require(
        all(r[1] == terminal[1] and r[0] <= terminal[0] for r in p06),
        "execution instance/order mismatch",
    )
    stages = [r[2].removeprefix(_STAGE).split("|") for r in p06 if r[2].startswith(_STAGE)]
    _require(
        all(len(r) == 2 and r[0] == receipt.plan_hash for r in stages), "stage identity mismatch"
    )
    _require(tuple(r[1] for r in stages) == tuple(receipt.stages), "stage receipt mismatch")
    sequence = tuple(ExecutionStage)
    _require(receipt.stages == sequence[: len(receipt.stages)], "execution stages out of order")
    success = receipt.result == "success"
    if success:
        _require(
            receipt.code == "NONE"
            and receipt.failure_reason is None
            and receipt.failed_stage is None
            and receipt.failed_entity is None
            and receipt.stages == sequence,
            "success lacks verified stages",
        )
    else:
        _require(
            receipt.code != "NONE"
            and receipt.failure_reason is not None
            and receipt.failed_stage is not None
            and receipt.failed_entity is not None
            and ExecutionStage.EXECUTION_RECEIPT_EMITTED not in receipt.stages,
            "invalid failure semantics",
        )
    if setup.status == "accepted":
        try:
            world = parse_runtime_world_evidence(
                log, runtime_projection_from_manifest(scenario.world_manifest), receipt.plan_hash
            )
        except SetupEvidenceError as error:
            raise ExecutionEvidenceError("P03 runtime world evidence rejected") from error
        _require(
            world["runtime_instance_id"] == terminal[1]
            and receipt.runtime_world_hash == world["observed_runtime_world_hash"],
            "runtime hash/instance mismatch",
        )
        setup_rows = [r for r in rows if r[2].startswith("P03_EXECUTOR_AI|P03_SETUP_V1|")]
        _require(setup_rows[0][0] < p06[0][0], "execution preceded P03 acceptance")
    else:
        _require(
            not success
            and receipt.code == "PRE_EXECUTION_FAILURE"
            and receipt.runtime_world_hash is None
            and not receipt.stages
            and not receipt.actions
            and not receipt.created_vehicles
            and not receipt.fleet
            and not receipt.orders
            and not receipt.native_groups,
            "rejected world cannot claim execution",
        )
        return receipt
    expected_actions = payload["actions"]
    _require(len(receipt.actions) <= len(expected_actions), "unexpected action count")
    for actual, row in zip(receipt.actions, expected_actions):
        action, candidate = row["action"], row["candidate"]
        if candidate["kind"] == "segment":
            tiles = tuple(t["x"] + scenario.width_tiles * t["y"] for t in candidate["tiles"])
        else:
            site = row["site"]["tile"]
            tiles = tuple(
                site["x"] + x + scenario.width_tiles * (site["y"] + y)
                for y in range(row["height"])
                for x in range(row["width"])
            )
        _require(
            (actual.construction_id, actual.candidate_id, actual.mode, actual.kind, actual.tiles)
            == (
                action["construction_id"],
                candidate["candidate_id"],
                candidate["mode"],
                candidate["kind"],
                tiles,
            ),
            "action or exact geometry mismatch",
        )
        _require(
            (actual.station_id is not None) == (actual.kind == "station")
            and actual.depot_tile == (tiles[0] if actual.kind == "depot" else None),
            "facility entity mismatch",
        )
    station_ids = [a.station_id for a in receipt.actions if a.station_id is not None]
    _require(len(station_ids) == len(set(station_ids)), "duplicate created station")
    groups = sorted(plan.fleet.groups, key=lambda g: g.fleet_group_id)
    _require(len(receipt.native_groups) <= len(groups), "unexpected native group count")
    native_ids = []
    for actual, expected in zip(receipt.native_groups, groups):
        _require(
            actual.group_id == expected.fleet_group_id
            and actual.mode == expected.mode
            and actual.vehicle_count <= expected.count,
            "native group entity mismatch",
        )
        native_ids.append(actual.runtime_id)
        if success:
            _require(
                actual.verified and actual.vehicle_count == expected.count,
                "native group not verified",
            )
    _require(len(native_ids) == len(set(native_ids)), "duplicate native group ID")
    if success:
        _require(len(receipt.native_groups) == len(groups), "missing native group")
    expected_purchases = []
    expected_fleet = []
    for g in groups:
        comp = g.composition
        if g.mode is Mode.ROAD:
            assert isinstance(comp, RoadComposition)
            components = [(comp.vehicle_type, "road")]
        else:
            assert isinstance(comp, RailComposition)
            components = [(comp.locomotive_type, "locomotive")] + [
                (w.wagon_type, "wagon") for w in comp.wagons for _ in range(w.count)
            ]
        for _ in range(g.count):
            expected_fleet.append((g, components))
            expected_purchases.extend(
                (g.fleet_group_id, g.route_ids[0], payload["engines"][name]["engine_id"], role)
                for name, role in components
            )
    _require(
        len(receipt.created_vehicles) <= len(expected_purchases), "unexpected purchased vehicle"
    )
    for actual, expected in zip(receipt.created_vehicles, expected_purchases):
        _require(
            (actual.group_id, actual.route_id, actual.engine_id, actual.role) == expected,
            "purchase entity/type mismatch",
        )
    vehicle_ids = [v.vehicle_id for v in receipt.created_vehicles]
    _require(len(vehicle_ids) == len(set(vehicle_ids)), "duplicate vehicle ID")
    main_ids = [v.vehicle_id for v in receipt.created_vehicles if v.role != "wagon"]
    _require(
        len(receipt.fleet) <= len(expected_fleet) and len(receipt.fleet) <= len(main_ids),
        "unexpected fleet count",
    )
    for i, (actual, (g, components)) in enumerate(zip(receipt.fleet, expected_fleet)):
        b = payload["groups"][g.fleet_group_id]
        _require(
            actual.group_id == g.fleet_group_id
            and actual.vehicle_id == main_ids[i]
            and actual.engine_ids
            == tuple(payload["engines"][name]["engine_id"] for name, _ in components)
            and actual.capacity == b["expected_capacity"],
            "fleet composition/capacity mismatch",
        )
        if g.mode is Mode.RAIL:
            _require(0 < actual.length_16ths <= b["max_length_16ths"], "train length mismatch")
    routes = {r.route_id: r for r in plan.routes}
    _require(len(receipt.orders) <= len(receipt.fleet), "unexpected orders")
    for actual, fleet in zip(receipt.orders, receipt.fleet):
        route_id = next(g.route_ids[0] for g in groups if g.fleet_group_id == fleet.group_id)
        route = routes[route_id]
        targets = tuple(
            payload["locations"][s.location_id]["tile"]["x"]
            + scenario.width_tiles * payload["locations"][s.location_id]["tile"]["y"]
            for s in route.stops
        )
        _require(
            (actual.group_id, actual.route_id, actual.vehicle_id)
            == (fleet.group_id, route_id, fleet.vehicle_id),
            "order entity mismatch",
        )
        _require(
            len(actual.targets) <= 3
            and actual.targets == targets[: len(actual.targets)]
            and actual.flags == (16, 132, 0)[: len(actual.targets)]
            and actual.assigned == (len(actual.targets) == 3),
            "order assignment mismatch",
        )
    if success:
        _require(
            len(receipt.actions) == len(expected_actions)
            and len(receipt.created_vehicles) == len(expected_purchases)
            and len(receipt.fleet) == len(expected_fleet)
            and len(receipt.orders) == len(expected_fleet)
            and all(o.assigned for o in receipt.orders),
            "required execution skipped",
        )
    for native in receipt.native_groups:
        _require(
            native.vehicle_count == sum(v.group_id == native.group_id for v in receipt.fleet),
            "native group membership count mismatch",
        )
    if not success:
        known_entities = (
            {"plan"}
            | {r.route_id for r in plan.routes}
            | {a.construction_id for a in plan.infrastructure.actions}
            | {g.fleet_group_id for g in groups}
            | set(payload["engines"])
            | {str(v) for v in main_ids}
        )
        _require(receipt.failed_entity in known_entities, "unknown failed entity")
        _require(
            bool(receipt.stages)
            and (
                receipt.failed_stage == receipt.stages[-1]
                or (
                    receipt.failed_stage == ExecutionStage.SETUP_VERIFIED
                    and receipt.stages[-1] == ExecutionStage.ORDERS_COMPLETED
                )
            ),
            "failed stage inconsistent with execution prefix",
        )
        if receipt.failed_stage == ExecutionStage.ORDERS_STARTED:
            _require(
                bool(receipt.orders)
                and receipt.failed_entity == str(receipt.orders[-1].vehicle_id),
                "failed order vehicle mismatch",
            )
    events = [_json(r[2].removeprefix(_EVENT)) for r in p06 if r[2].startswith(_EVENT)]
    _require(
        all(e.get("plan_hash") == receipt.plan_hash for e in events), "event identity mismatch"
    )
    purchases = [e for e in events if e.get("kind") == "purchase"]
    _require(
        [
            (e.get("entity"), e.get("vehicle_id"), e.get("engine_id"), e.get("role"))
            for e in purchases
        ]
        == [(v.group_id, v.vehicle_id, v.engine_id, v.role) for v in receipt.created_vehicles],
        "purchase event mismatch",
    )
    order_events = [e for e in events if e.get("kind") == "order"]
    _require(
        [
            (e.get("entity"), e.get("position"), e.get("target"), e.get("flags"))
            for e in order_events
        ]
        == [
            (str(o.vehicle_id), i, t, o.flags[i])
            for o in receipt.orders
            for i, t in enumerate(o.targets)
        ],
        "order event mismatch",
    )
    action_rows = {r["action"]["construction_id"]: r for r in expected_actions}
    segment_progress = {}
    active_action = None
    current_stage = None
    for _, _, message in p06:
        if message.startswith(_STAGE):
            current_stage = message.removeprefix(_STAGE).split("|")[1]
        elif message.startswith(_EVENT):
            event = _json(message.removeprefix(_EVENT))
            kind = event.get("kind")
            if kind in (
                "action_start",
                "action_success",
                "action_failure",
                "segment_step",
                "facility_connector",
            ):
                _require(current_stage == "INFRASTRUCTURE_STARTED", "action in wrong stage")
                if kind == "action_start":
                    _require(active_action is None, "action started before prior success")
                    active_action = event.get("entity")
                    _require(active_action in action_rows, "unknown action event entity")
                else:
                    _require(
                        active_action == event.get("entity"), "action event order/entity mismatch"
                    )
                    row = action_rows[active_action]
                    if kind == "facility_connector":
                        _require(
                            row["candidate"]["kind"] == "depot"
                            and row["candidate"]["mode"] == "road"
                            and event.get("from_tile")
                            == row["site"]["tile"]["x"]
                            + scenario.width_tiles * row["site"]["tile"]["y"]
                            and event.get("to_tile")
                            == row["front"]["x"] + scenario.width_tiles * row["front"]["y"],
                            "depot connector geometry mismatch",
                        )
                    if kind == "segment_step":
                        _require(
                            row["candidate"]["kind"] == "segment", "step on non-segment action"
                        )
                        tiles = [
                            t["x"] + scenario.width_tiles * t["y"]
                            for t in row["candidate"]["tiles"]
                        ]
                        steps = (
                            list(zip(tiles, tiles[1:]))
                            if row["candidate"]["mode"] == "road"
                            else tiles
                        )
                        progress = segment_progress.get(active_action, 0)
                        actual_step = (
                            (event.get("from_tile"), event.get("to_tile"))
                            if row["candidate"]["mode"] == "road"
                            else event.get("tile")
                        )
                        _require(
                            progress < len(steps) and actual_step == steps[progress],
                            "segment sequence mismatch",
                        )
                        segment_progress[active_action] = progress + 1
                    if kind == "action_success":
                        if row["candidate"]["kind"] == "segment":
                            expected_count = len(row["candidate"]["tiles"]) - (
                                1 if row["candidate"]["mode"] == "road" else 0
                            )
                            _require(
                                segment_progress.get(active_action, 0) == expected_count,
                                "required segment step skipped",
                            )
                        active_action = None
            elif kind == "purchase":
                _require(current_stage == "FLEET_STARTED", "purchase in wrong stage")
            elif kind == "order":
                _require(current_stage == "ORDERS_STARTED", "orders in wrong stage")
            elif kind not in ("failure", "command_start"):
                raise ExecutionEvidenceError("unknown execution event")
    starts = [e for e in events if e.get("kind") == "action_start"]
    completed = [e for e in events if e.get("kind") == "action_success"]
    _require(
        [(e.get("entity"), e.get("candidate_id")) for e in completed]
        == [(a.construction_id, a.candidate_id) for a in receipt.actions],
        "action event mismatch",
    )
    expected_starts = [
        (r["action"]["construction_id"], r["candidate"]["candidate_id"]) for r in expected_actions
    ]
    _require(
        [(e.get("entity"), e.get("candidate_id")) for e in starts]
        == expected_starts[: len(starts)],
        "action start mismatch",
    )
    _require(
        len(starts)
        == len(completed)
        + (0 if success or receipt.failed_stage != ExecutionStage.INFRASTRUCTURE_STARTED else 1),
        "action evidence incomplete",
    )
    failures = [e for e in events if e.get("kind") == "failure"]
    action_failures = [e for e in events if e.get("kind") == "action_failure"]
    mutation_attempted = any(e.get("kind") == "command_start" for e in events)
    if not success:
        _require(
            (receipt.code == "PARTIAL_EXECUTION") == mutation_attempted,
            "failure classification contradicts mutation evidence",
        )
    if success:
        _require(not failures and not action_failures, "success after failure")
    else:
        _require(
            len(failures) == 1
            and (failures[0].get("entity"), failures[0].get("stage"), failures[0].get("reason"))
            == (receipt.failed_entity, receipt.failed_stage, receipt.failure_reason),
            "failure entity mismatch",
        )
    return receipt
