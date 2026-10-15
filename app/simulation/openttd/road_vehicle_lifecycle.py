"""Native default-cargo road vehicle admission and lifecycle receipt semantics."""

import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictInt

from app.planning.canonical import canonical_bytes
from app.planning.domain import Contract, Digest
from app.simulation.openttd.road_mutation import CompanyID, Money, TileID

Identifier = Annotated[StrictInt, Field(ge=-1, le=65535)]
Operation = Literal[
    "engine", "purchase", "vread", "order-check", "order", "start-check", "start", "motion"
]


class VehicleRequest(Contract):
    protocol: Literal[1] = 1
    op: Operation
    request_id: Annotated[str, Field(pattern=r"^[a-z0-9-]{1,32}$")]
    plan: Digest
    company: CompanyID
    depot: TileID
    stop: TileID
    engine: Identifier = -1
    cargo: Identifier = -1
    vehicle: Identifier = -1
    max_cost: Money
    expected_cost: Money = 0

    def to_bytes(self) -> bytes:
        raw = canonical_bytes(self)
        if len(raw) > 512 or self.depot != self.stop + 3 or self.stop // 64 != self.depot // 64:
            raise ValueError("bounded four-tile infrastructure required")
        return raw


class VehicleReadback(Contract):
    protocol: Literal[1]
    op: Operation
    request_id: str
    plan: Digest
    company: CompanyID
    depot: TileID
    stop: TileID
    status: Literal[
        "READY",
        "PURCHASED",
        "READ",
        "ORDERED",
        "STARTED",
        "MOVED",
        "INVALID_COMPANY",
        "INVALID_SITE",
        "NO_ENGINE",
        "ENGINE_LIMIT",
        "UNAVAILABLE_ENGINE",
        "INSUFFICIENT_FUNDS",
        "COST_LIMIT",
        "COST_CHANGED",
        "REJECTED",
        "OUT_OF_ORDER",
        "READBACK_MISMATCH",
        "NO_MOVEMENT",
        "PAUSED",
        "CLOCK_STALLED",
        "INVALID_ROUTE",
        "WINDOW_EXHAUSTED",
    ]
    engine: Identifier
    cargo: Identifier
    vehicle: Identifier
    available: StrictBool
    compatible: StrictBool
    capacity: StrictInt
    price: StrictInt
    cost: StrictInt
    funds: StrictInt
    owner: StrictInt
    location: StrictInt
    state: Literal["INVALID", "IN_DEPOT", "RUNNING", "STOPPED", "AT_STATION", "BROKEN", "CRASHED"]
    indepot: StrictBool
    speed: StrictInt
    order: tuple[StrictInt, StrictInt, StrictInt, StrictBool]

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()

    @classmethod
    def parse_for(cls, q: VehicleRequest, raw: bytes):
        if len(raw) > 512:
            raise ValueError("application response exceeds 512 bytes")

        def unique(pairs):
            d = {}
            for k, v in pairs:
                if k in d:
                    raise ValueError("duplicate response key")
                d[k] = v
            return d

        json.loads(raw, object_pairs_hook=unique)
        if q.op == "motion" and "v" in json.loads(raw):
            return VehicleMotionReadback.parse_for(q, raw)
        r = cls.model_validate_json(raw)
        cls.validate_correlation(q, r)
        return r

    @staticmethod
    def validate_correlation(q, r):
        if any(
            getattr(q, k) != getattr(r, k)
            for k in ("protocol", "op", "request_id", "plan", "company", "depot", "stop")
        ):
            raise ValueError("vehicle response correlation mismatch")
        if any(
            getattr(q, k) >= 0 and getattr(q, k) != getattr(r, k)
            for k in ("engine", "cargo", "vehicle")
        ):
            raise ValueError("vehicle identity mismatch")


MOTION_TICKS = 256
MOTION_POLLS = MOTION_TICKS + 1
MOTION_SECONDS = 60
MOTION_FIELDS = (
    "engine",
    "cargo",
    "vehicle",
    "available",
    "compatible",
    "capacity",
    "price",
    "cost",
    "funds",
    "owner",
    "location",
    "state",
    "indepot",
    "speed",
    "order",
)


class VehicleMotionReadback(VehicleReadback):
    """Compact native snapshot plus script-clock and pause evidence; not game ticks."""

    op: Literal["motion"]
    clock: tuple[StrictInt, StrictInt, StrictInt, StrictBool]

    def to_bytes(self):
        data = self.model_dump(mode="json")
        data["v"] = [data.pop(k) for k in MOTION_FIELDS]
        raw = json.dumps(data, separators=(",", ":")).encode()
        if len(raw) > 512:
            raise ValueError("application response exceeds 512 bytes")
        return raw

    @classmethod
    def parse_for(cls, q, raw):
        if len(raw) > 512:
            raise ValueError("application response exceeds 512 bytes")

        def unique(pairs):
            data = {}
            for key, value in pairs:
                if key in data:
                    raise ValueError("duplicate response key")
                data[key] = value
            return data

        data = json.loads(raw, object_pairs_hook=unique)
        values = data.pop("v")
        if not isinstance(values, list) or len(values) != len(MOTION_FIELDS):
            raise ValueError("invalid compact motion snapshot")
        if set(data) != {
            "protocol",
            "op",
            "request_id",
            "plan",
            "company",
            "depot",
            "stop",
            "status",
            "clock",
        }:
            raise ValueError("invalid compact motion envelope")
        data.update(zip(MOTION_FIELDS, values, strict=True))
        r = cls.model_validate_json(json.dumps(data))
        cls.validate_correlation(q, r)
        return r


class VehicleLifecyclePlan(Contract):
    schema_version: Literal[1] = 1
    prelaunch_digest: Digest
    infrastructure_receipt_digest: Digest
    source_save_digest: Digest
    site_digest: Digest
    engine_digest: Digest
    company: CompanyID
    depot: TileID
    stop: TileID
    engine: Identifier
    cargo: Identifier
    capacity: Annotated[StrictInt, Field(gt=0)]
    purchase_cost: Annotated[StrictInt, Field(gt=0)]
    max_cost: Money

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()


def admit_engine(
    r: VehicleReadback,
    *,
    prelaunch_digest: str,
    infrastructure_receipt_digest: str,
    source_save_digest: str,
    site_digest: str,
    max_cost: int,
) -> VehicleLifecyclePlan:
    if (
        r.op != "engine"
        or r.status != "READY"
        or r.plan != prelaunch_digest
        or r.engine < 0
        or r.cargo < 0
        or r.vehicle != -1
        or not r.available
        or not r.compatible
        or r.capacity <= 0
        or not 0 < r.price == r.cost <= min(max_cost, r.funds)
        or r.state != "INVALID"
        or r.owner != -1
        or r.order != (0, -1, 0, False)
    ):
        raise ValueError("native available compatible engine, capacity, price and funds required")
    return VehicleLifecyclePlan(
        prelaunch_digest=prelaunch_digest,
        infrastructure_receipt_digest=infrastructure_receipt_digest,
        source_save_digest=source_save_digest,
        site_digest=site_digest,
        engine_digest=r.digest,
        company=r.company,
        depot=r.depot,
        stop=r.stop,
        engine=r.engine,
        cargo=r.cargo,
        capacity=r.capacity,
        purchase_cost=r.cost,
        max_cost=max_cost,
    )


def verify_vehicle(
    plan: VehicleLifecyclePlan, r: VehicleReadback, vehicle: int, orders: int, *, stopped: bool
):
    if (
        (r.plan, r.company, r.depot, r.stop, r.engine, r.cargo, r.vehicle, r.owner, r.capacity)
        != (
            plan.digest,
            plan.company,
            plan.depot,
            plan.stop,
            plan.engine,
            plan.cargo,
            vehicle,
            plan.company,
            plan.capacity,
        )
        or vehicle < 0
        or not r.compatible
        or r.order != ((0, -1, 0, False) if orders == 0 else (1, plan.stop, 0, True))
    ):
        raise ValueError("native vehicle ownership, capacity or orders mismatch")
    if stopped and (
        r.state != "IN_DEPOT" or not r.indepot or r.location != plan.depot or r.speed != 0
    ):
        raise ValueError("vehicle is not stopped in the proven depot")
    if not stopped and r.state not in ("RUNNING", "AT_STATION"):
        raise ValueError("vehicle is not natively running or at station")


def verify_purchase(plan, engine, built, read):
    for r in (built, read):
        verify_vehicle(plan, r, built.vehicle, 0, stopped=True)
    if (
        built.op != "purchase"
        or built.status != "PURCHASED"
        or read.op != "vread"
        or read.status != "READ"
        or built.cost != plan.purchase_cost
        or engine.funds - built.funds != built.cost
        or read.funds != built.funds
        or read.cost != 0
    ):
        raise ValueError("purchase result, spending or independent readback mismatch")


def verify_order(plan, before, check, built, read):
    for r in (check, built, read):
        verify_vehicle(plan, r, before.vehicle, 0 if r is check else 1, stopped=True)
    if (
        check.op != "order-check"
        or check.status != "READY"
        or check.cost != 0
        or built.op != "order"
        or built.status != "ORDERED"
        or built.cost != 0
        or read.op != "vread"
        or read.status != "READ"
        or read.cost != 0
        or any(r.funds != before.funds for r in (check, built, read))
    ):
        raise ValueError("order admission, result or native readback mismatch")


def verify_start(plan, before, check, built, read, motion):
    verify_vehicle(plan, check, before.vehicle, 1, stopped=True)
    for r in (built, read, motion):
        verify_vehicle(plan, r, before.vehicle, 1, stopped=False)
    if (
        check.op != "start-check"
        or check.status != "READY"
        or check.cost != 0
        or built.op != "start"
        or built.status != "STARTED"
        or built.cost != 0
        or read.op != "vread"
        or read.status != "READ"
        or read.cost != 0
        or motion.op != "motion"
        or motion.status != "MOVED"
        or motion.cost != 0
        or motion.location == plan.depot
        or motion.indepot
        or motion.location not in range(plan.stop, plan.depot + 1)
        or not isinstance(motion, VehicleMotionReadback)
    ):
        raise ValueError("start transition or independent native movement mismatch")
    first, last, polls, paused = motion.clock
    if (
        not 0 <= first <= last <= 2147483647
        or last - first > MOTION_TICKS
        or not 1 <= polls <= MOTION_POLLS
        or (polls > 1 and last - first < polls - 1)
        or paused
    ):
        raise ValueError("movement clock, pause or polling evidence mismatch")


def verify_lifecycle(
    plan: VehicleLifecyclePlan, engine: VehicleReadback, records: dict[str, VehicleReadback]
) -> dict:
    if (
        admit_engine(
            engine,
            prelaunch_digest=plan.prelaunch_digest,
            infrastructure_receipt_digest=plan.infrastructure_receipt_digest,
            source_save_digest=plan.source_save_digest,
            site_digest=plan.site_digest,
            max_cost=plan.max_cost,
        )
        != plan
    ):
        raise ValueError("plan differs from admitted engine facts")
    verify_purchase(plan, engine, records["purchase-1"], records["read-purchase"])
    verify_order(
        plan,
        records["read-purchase"],
        records["order-check-1"],
        records["order-1"],
        records["read-order"],
    )
    verify_start(
        plan,
        records["read-order"],
        records["start-check-1"],
        records["start-1"],
        records["read-start"],
        records["motion-1"],
    )
    return dict(
        schema="road-vehicle-lifecycle-receipt-v1",
        plan_digest=plan.digest,
        prelaunch_digest=plan.prelaunch_digest,
        infrastructure_receipt_digest=plan.infrastructure_receipt_digest,
        source_save_digest=plan.source_save_digest,
        site_digest=plan.site_digest,
        engine=plan.engine,
        cargo=plan.cargo,
        capacity=plan.capacity,
        vehicle=records["purchase-1"].vehicle,
        company=plan.company,
        depot=plan.depot,
        stop=plan.stop,
        purchase_cost=plan.purchase_cost,
        order=dict(count=1, destination=plan.stop, flags=0),
        state_transitions=[
            records[k].state for k in ("read-purchase", "read-order", "read-start", "motion-1")
        ],
        locations=[records[k].location for k in ("read-purchase", "read-start", "motion-1")],
        funds=dict(
            before_purchase=engine.funds,
            after_purchase=records["read-purchase"].funds,
            before_start=records["read-order"].funds,
            after_motion=records["motion-1"].funds,
        ),
        movement=dict(
            clock_kind="SCRIPT_TICKS",
            observed_clock=records["motion-1"].model_dump(mode="json")["clock"],
            maximum_ticks=MOTION_TICKS,
            maximum_polls=MOTION_POLLS,
            wall_deadline_seconds=MOTION_SECONDS,
            proof="NATIVE_TILE_TRANSITION_FROM_PURCHASE_DEPOT",
        ),
        result_digests={k: r.digest for k, r in records.items()},
        verification="NATIVE_VEHICLE_LIFECYCLE_CHANGED",
        freight_delivery_proven=False,
    )
