"""Native corridor freight cycle wire contract (protocol 5, additive).

Milestone D5: the proven D4 corridor (route-receipt-bound truck stops and
company depot at the candidate-5 close-out geometry) must be driven by
exactly one road vehicle that picks cargo 1 up at the pickup stop, carries
it along the ordered witness path to the delivery stop, unloads, and is
then stopped. This module is the protocol-5 wire contract for that
fifteen-exchange cycle: typed requests, fail-closed response parsing,
typed admission latches, per-op verification receipts, and the ordered
cycle verifier over the fixed exchange schedule.

Protocol 5 stays additive. It reuses D4's proven wire types and helpers by
import and adds nothing that executes. Named constants (E33's lesson
applied on day one; no hard-coded bound literals return):

- Request and response bodies are canonical UTF-8 JSON bounded by
  MAX_FREIGHT_REQUEST_BYTES / MAX_FREIGHT_RESPONSE_BYTES (640 each). The
  64-character route digest that binds every exchange to the planner-selected
  route pushed the 24-tile site request past the historical 512-byte limit;
  640 is the same named-constant precedent protocol 4 used for its witness
  response. Any future growth gets another named constant first.
- Tile bounds are 256x256-safe (``TileID <= 65535``), imported from
  corridor_construction. The design text points at road_mutation.py types,
  whose historical 64x64 TileID bound cannot address this corridor's tiles
  (~45k) — recorded as the TileID range discrepancy in the D5 preparation
  docs.
- Outbound GameScript strings stay below MAX_FREIGHT_SEND_BYTES (1450, the
  GSAdmin.Send ceiling) and the Admin frame ceiling stays
  MAX_GAMESCRIPT_PAYLOAD_BYTES (32763).
- Wire identity: every D5 exchange carries one uniform prelaunch plan
  digest; per-op admission intents are receipt records, not new plan
  identities (one attempt, one company, one vehicle).
- Funds-reconciliation honesty (A9): the purchase exchange's funds delta
  is compared exactly against the positive tested quote; every other
  exchange's funds level is recorded in the receipt ledger ("no invented
  cash deltas"). Native running-cost accrual during the drive windows
  produces recorded, not invented, movements, so zero-delta equality is
  never demanded outside the purchase.
- 15.3 API pins carried by the order/monitor semantics: GSOrder.OF_FULL_LOAD
  (OF_FULL_LOAD == 4) for the pickup stop append, GSOrder.OF_NO_LOAD
  (OF_NO_LOAD == 0) for the delivery stop, GSStation.GetCargoAcceptance
  reported in eighths (0..8), and GSCargoMonitor armed with
  keep_monitoring=true before the first start and consumed with
  keep=false during the deliver-watch exchange.
- The design's ops table lists 13 op kinds (one ``vread`` row) for 15
  planned exchanges: the independent vehicle readbacks are the same
  ``vread`` op exercised twice (``vread-00``/``vread-01``), so 13 kinds
  arithmetize to the 15 planned exchanges. Recorded as the exchange-count
  discrepancy note in the D5 preparation docs.
"""

import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictInt, model_validator

from app.planning.canonical import canonical_bytes
from app.planning.domain import Contract, Digest
from app.simulation.openttd.corridor_construction import (
    CompanyID,
    Money,
    OwnerID,
    SignedMoney,
    StationID,
    TileID,
)

FREIGHT_PROTOCOL = 5
# The 24-tile site route plus its 64-character route digest measures ~526
# canonical bytes, so protocol 5's named application bound moves to 640 (the
# same additive precedent protocol 4 used for its witness response).  The
# GameScript send ceiling below is unchanged.
MAX_FREIGHT_REQUEST_BYTES = 640
MAX_FREIGHT_RESPONSE_BYTES = 640
# A site request may carry the optimizer-selected ordered witness.  The bound
# is the same 24 tiles the D4 route receipt pins.
MAX_FREIGHT_ROUTE_TILES = 24
MAX_FREIGHT_SEND_BYTES = 1450
MAX_GAMESCRIPT_PAYLOAD_BYTES = 32763
# The corridor world the wire contract was derived from is a 256x256 Seed-17
# map.  Geometry helpers use these named dimensions instead of a bare 256.
FREIGHT_MAP_WIDTH = 256
FREIGHT_MAP_HEIGHT = 256
FREIGHT_MAX_TILE_ID = FREIGHT_MAP_WIDTH * FREIGHT_MAP_HEIGHT - 1
PLANNED_FREIGHT_EXCHANGES = 15
FREIGHT_REQUEST_BUDGET = 32
FREIGHT_COMPANY = 0
FREIGHT_CARGO_ID = 1
FREIGHT_PICKUP_INDUSTRY = 0
FREIGHT_DELIVERY_INDUSTRY = 1
FUNDS_AT_D4_CLOSE = 492149
FREIGHT_MAX_COST = 2000
# Per-phase window caps (§8): caps, never promises. Wall-clock deadlines
# stay in the ceremony module alongside its 900 s runtime budget.
WATCH_MAX_TICKS = 2048
LOAD_WATCH_MAX_DAYS = 30
# Order-flag pins read from the proven delivery contract (15.3 API).
OF_FULL_LOAD = 4
OF_NO_LOAD = 0

FREIGHT_OPS = (
    "site",
    "engine",
    "purchase",
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
)

FreightOp = Literal[
    "site",
    "engine",
    "purchase",
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
]

FreightStatus = Literal[
    "READY",
    "BUILT",
    "READ",
    "ORDERED",
    "ORDER_SET_VERIFIED",
    "ARMED",
    "STARTED",
    "LOADED",
    "AT_DELIVERY",
    "DELIVERED",
    "FINANCE_VERIFIED",
    "PHASE_STOPPED",
    "INVALID_COMPANY",
    "INVALID_SITE",
    "INVALID_LOCATION",
    "INVALID_ROUTE",
    "NO_ENGINE",
    "UNAVAILABLE_ENGINE",
    "ENGINE_LIMIT",
    "INSUFFICIENT_FUNDS",
    "COST_LIMIT",
    "COST_CHANGED",
    "PAUSED",
    "ALREADY_ATTEMPTED",
    "STALE_ADMISSION",
    "UNSUPPORTED_NATIVE_FACT",
    "READBACK_MISMATCH",
    "OUT_OF_ORDER",
    "CLOCK_STALLED",
    "WINDOW_EXHAUSTED",
]

_FREIGHT_SEQUENCE: tuple[tuple[str, FreightOp], ...] = (
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
)
FREIGHT_EXCHANGE_IDS: tuple[str, ...] = tuple(i for i, _ in _FREIGHT_SEQUENCE)
_FREIGHT_OP_BY_ID: dict[str, FreightOp] = dict(_FREIGHT_SEQUENCE)
if (
    len(FREIGHT_EXCHANGE_IDS) != PLANNED_FREIGHT_EXCHANGES
    or len(set(FREIGHT_EXCHANGE_IDS)) != PLANNED_FREIGHT_EXCHANGES
    or set(_FREIGHT_OP_BY_ID.values()) != set(FREIGHT_OPS)
):
    raise RuntimeError("freight exchange schedule drifted from the planned ops")

_FREIGHT_SUCCESS_STATUS: dict[FreightOp, str] = {
    "site": "READY",
    "engine": "READY",
    "purchase": "BUILT",
    "vread": "READ",
    "order": "ORDERED",
    "order-read": "ORDER_SET_VERIFIED",
    "monitor": "ARMED",
    "start": "STARTED",
    "load-watch": "LOADED",
    "transit-watch": "AT_DELIVERY",
    "deliver-watch": "DELIVERED",
    "finance": "FINANCE_VERIFIED",
    "finish": "PHASE_STOPPED",
}
_FREIGHT_INCONCLUSIVE_STATUS = frozenset({"WINDOW_EXHAUSTED", "CLOCK_STALLED"})
_FREIGHT_REFUSAL_STATUS = frozenset(
    {
        "INVALID_SITE",
        "INVALID_COMPANY",
        "INVALID_LOCATION",
        "INVALID_ROUTE",
        "NO_ENGINE",
        "UNAVAILABLE_ENGINE",
        "ENGINE_LIMIT",
        "INSUFFICIENT_FUNDS",
        "COST_LIMIT",
        "COST_CHANGED",
        "PAUSED",
        "ALREADY_ATTEMPTED",
        "STALE_ADMISSION",
        "UNSUPPORTED_NATIVE_FACT",
        "READBACK_MISMATCH",
        "OUT_OF_ORDER",
    }
)
_FREIGHT_REPORTED_STATUS = (
    _FREIGHT_INCONCLUSIVE_STATUS
    | _FREIGHT_REFUSAL_STATUS
    | frozenset(_FREIGHT_SUCCESS_STATUS.values())
)
# Refusal statuses that the native handler can emit only after its one
# mutation command for the op has (or may have) been executed. A refusal in
# one of these sets is labelled ``UNCERTAIN_AFTER_FAILED_COMMAND`` by the
# phase outcome: the world may not be unchanged, so it is never reported as
# untouched. Statuses outside the op's set are still pre-mutation refusals.
# Sets are deliberately conservative (see main.nut): e.g. a purchase
# ``COST_CHANGED`` fires both on a pre-build quote drift and on a
# post-build realized-cost mismatch, and the honest label is the stronger.
_FREIGHT_POST_MUTATION_STATUS = {
    "purchase": frozenset({"COST_CHANGED", "READBACK_MISMATCH", "UNSUPPORTED_NATIVE_FACT"}),
    "order": frozenset({"READBACK_MISMATCH", "UNSUPPORTED_NATIVE_FACT"}),
    "start": frozenset({"READBACK_MISMATCH", "UNSUPPORTED_NATIVE_FACT"}),
    "finish": frozenset({"READBACK_MISMATCH", "UNSUPPORTED_NATIVE_FACT"}),
}

FreightCompany = CompanyID
FreightActorId = Annotated[StrictInt, Field(ge=-1, le=65535)]
FreightPod = Annotated[StrictInt, Field(ge=0, le=65535)]
FreightCargo = Annotated[StrictInt, Field(ge=0, le=63)]
FreightIndustry = Annotated[StrictInt, Field(ge=0, le=65535)]
FreightEighths = Annotated[StrictInt, Field(ge=0, le=8)]
FreightCount = Annotated[StrictInt, Field(ge=0, le=2147483647)]
FreightDate = Annotated[StrictInt, Field(ge=-1, le=2147483647)]
FreightFlags = Annotated[StrictInt, Field(ge=0, le=15)]
FreightWatchTicks = Annotated[StrictInt, Field(ge=-1, le=WATCH_MAX_TICKS)]
FreightWatchDays = Annotated[StrictInt, Field(ge=-1, le=LOAD_WATCH_MAX_DAYS)]
FreightOrderIndex = Annotated[StrictInt, Field(ge=-1, le=1)]
FreightAmount = Annotated[StrictInt, Field(ge=0, le=2147483647)]
FreightPairCount = Annotated[StrictInt, Field(ge=0, le=48)]
FreightProgress = Annotated[StrictInt, Field(ge=0, le=47)]
FreightVehicleState = Literal[
    "INVALID",
    "IN_DEPOT",
    "RUNNING",
    "STOPPED",
    "AT_STATION",
    "BROKEN",
    "CRASHED",
]


def freight_route_digest(route: tuple[int, ...]) -> str:
    """The canonical digest binding one ordered route to a wire exchange.

    Python is the trust anchor: it derives this digest from the planner's
    ``FreightPlan.witness`` and verifies every signed request against it.
    The GameScript cannot re-hash in Squirrel, so it only latches the first
    site exchange's digest and refuses later drift — an intra-attempt
    consistency check, never independent authentication of the plan.
    """
    return hashlib.sha256(",".join(map(str, route)).encode()).hexdigest()


def _cardinal_neighbours(a: int, b: int) -> bool:
    return (
        abs(a % FREIGHT_MAP_WIDTH - b % FREIGHT_MAP_WIDTH)
        + abs(a // FREIGHT_MAP_WIDTH - b // FREIGHT_MAP_WIDTH)
        == 1
    )


def _validate_freight_route(route: tuple[int, ...], pickup: int, delivery: int, depot: int) -> None:
    """Validate one bounded D5 route against the request's own pins.

    The GameScript re-checks the same invariants natively before it latches
    the geometry, so a malformed or stale route is refused on both sides of
    the wire rather than silently replaced by the baked D4 defaults.
    """
    if not 3 <= len(route) <= MAX_FREIGHT_ROUTE_TILES:
        raise ValueError(f"route must carry 3..{MAX_FREIGHT_ROUTE_TILES} ordered tiles")
    if len(set(route)) != len(route):
        raise ValueError("route repeats a tile")
    if any(not 0 <= tile <= FREIGHT_MAX_TILE_ID for tile in route):
        raise ValueError("route tile exceeds the 256x256 map bound")
    if any(not _cardinal_neighbours(a, b) for a, b in zip(route, route[1:], strict=False)):
        raise ValueError("route tiles are not cardinally adjacent")
    if route[0] != pickup or route[-1] != delivery:
        raise ValueError("route endpoints must be the pickup and delivery stops")
    if depot in route:
        raise ValueError("depot must not lie on the route")
    fronts = [tile for tile in route[1:-1] if _cardinal_neighbours(tile, depot)]
    if len(fronts) != 1:
        raise ValueError("depot must touch exactly one route interior tile")


class FreightRequest(Contract):
    """One protocol-5 freight exchange request (fixed correlation stride).

    Every request carries the full correlation stride — the D5 world pins,
    the uniform ``plan`` digest, and its op's echo fields (sentinel -1 or 0
    when the op does not use them) — so every readback is self-contained.
    Op-conditional validators keep each echo set exact: a purchase presents
    its positive tested quote, watch ops present their phase-budget echoes,
    and everything downstream of the purchase carries the vehicle identity.
    """

    protocol: Literal[5] = 5
    op: FreightOp
    request_id: Annotated[str, Field(pattern=r"^[a-z0-9-]{1,32}$")]
    plan: Digest
    company: CompanyID
    max_cost: Money
    pickup: TileID
    delivery: TileID
    depot: TileID
    route: tuple[TileID, ...] | None = None
    # Present on every exchange.  The site request's digest must match its
    # route; later exchanges carry the same digest so the GameScript can
    # reject a stale route before the purchase stage is reached.
    route_digest: Digest
    engine: FreightActorId = -1
    vehicle: FreightActorId = -1
    expected_cost: Money = 0
    order_index: FreightOrderIndex = -1
    watch_ticks: FreightWatchTicks = -1
    watch_days: FreightWatchDays = -1

    @model_validator(mode="after")
    def coherent(self) -> FreightRequest:
        quiet = (
            self.expected_cost == 0
            and self.order_index == -1
            and self.watch_ticks == -1
            and self.watch_days == -1
        )
        pitched = self.engine >= 0 and self.vehicle >= 0
        if self.op in ("site", "engine"):
            if self.engine != -1 or self.vehicle != -1 or not quiet:
                raise ValueError("site/engine requests carry no engine, vehicle or phase echoes")
        if self.op == "site":
            if self.route is None:
                raise ValueError("site request must carry the optimizer-selected route")
            _validate_freight_route(self.route, self.pickup, self.delivery, self.depot)
            if self.route_digest != freight_route_digest(self.route):
                raise ValueError("site request route digest does not bind its route")
        elif self.route is not None:
            raise ValueError("only the site request may carry a route")
        if self.op in ("site", "engine"):
            return self
        if self.op == "purchase":
            if self.engine < 0 or self.vehicle != -1:
                raise ValueError("purchase request must present exactly one admitted engine")
            if self.order_index != -1 or self.watch_ticks != -1 or self.watch_days != -1:
                raise ValueError("purchase request must present no phase echoes")
            if not 0 < self.expected_cost <= self.max_cost:
                raise ValueError(
                    "purchase request needs its positive tested quote within the ceiling"
                )
        elif self.op == "vread":
            if not pitched or not quiet:
                raise ValueError("vehicle readback echoes the admitted engine and live vehicle")
        elif self.op == "order":
            if (
                not pitched
                or self.order_index not in (0, 1)
                or self.expected_cost != 0
                or self.watch_ticks != -1
                or self.watch_days != -1
            ):
                raise ValueError("order requests pin one stop index with no phase echoes")
        elif self.op in ("order-read", "monitor", "start", "finance", "finish"):
            if not pitched or not quiet:
                raise ValueError(f"{self.op} echoes the vehicle identity only")
        elif self.op == "load-watch":
            if not pitched or self.order_index != -1 or self.expected_cost != 0:
                raise ValueError("load-watch echoes the vehicle identity only")
            if self.watch_ticks < 1 or self.watch_days < 1:
                raise ValueError("load-watch presents its tick and day budget echoes")
        elif self.op in ("transit-watch", "deliver-watch"):
            if not pitched or self.order_index != -1 or self.expected_cost != 0:
                raise ValueError("window echoes the vehicle identity only")
            if self.watch_ticks < 1 or self.watch_days != -1:
                raise ValueError("window presents its tick budget and no day budget")
        else:  # pragma: no cover - FreightOp excludes unknown ops
            raise ValueError("unknown freight op")
        return self

    def to_bytes(self) -> bytes:
        raw = canonical_bytes(self)
        if len(raw) > MAX_FREIGHT_REQUEST_BYTES:
            raise ValueError(f"freight request exceeds {MAX_FREIGHT_REQUEST_BYTES} bytes")
        return raw


_FREIGHT_FIELDS = (
    "paused",
    "truck0",
    "sid0",
    "truck1",
    "sid1",
    "depot_ok",
    "owner",
    "pairs_ok",
    "pair_total",
    "accept",
    "prod",
    "wait",
    "vehicles",
    "available",
    "compatible",
    "capacity",
    "cargo",
    "location",
    "state",
    "in_depot",
    "speed",
    "dest",
    "flags",
    "goto",
    "order_len",
    "dest0",
    "flags0",
    "goto0",
    "dest1",
    "flags1",
    "goto1",
    "pickup_amount",
    "delivery_amount",
    "income",
    "delivered",
    "load",
    "position",
    "progress",
    "tick",
    "day",
    "last_accepted",
    "stop_issued",
)

_FREIGHT_SUBSETS: dict[FreightOp, frozenset[str]] = {
    "site": frozenset(
        (
            "paused",
            "truck0",
            "sid0",
            "truck1",
            "sid1",
            "depot_ok",
            "owner",
            "pairs_ok",
            "pair_total",
            "accept",
            "prod",
            "wait",
            "vehicles",
        )
    ),
    "engine": frozenset(("available", "compatible", "capacity", "cargo")),
    "purchase": frozenset(),
    "vread": frozenset(("owner", "location", "capacity", "cargo", "state", "in_depot", "speed")),
    "order": frozenset(("dest", "flags", "goto")),
    "order-read": frozenset(("order_len", "dest0", "flags0", "goto0", "dest1", "flags1", "goto1")),
    "monitor": frozenset(("pickup_amount", "delivery_amount", "income", "delivered")),
    "start": frozenset(("state", "speed")),
    "load-watch": frozenset(("load", "capacity", "wait", "tick", "day", "paused")),
    "transit-watch": frozenset(("position", "progress", "load", "tick", "day", "paused")),
    "deliver-watch": frozenset(
        ("load", "pickup_amount", "delivery_amount", "tick", "day", "paused")
    ),
    "finance": frozenset(("income", "delivered", "last_accepted")),
    "finish": frozenset(("state", "speed", "in_depot", "stop_issued")),
}
_FREIGHT_WATCH_OPS = ("load-watch", "transit-watch", "deliver-watch")
_FREIGHT_POST_PURCHASE_OPS = (
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
)


class FreightReadback(Contract):
    """One protocol-5 freight exchange response (strict per-op field subsets).

    The handler echoes the request correlation keys, ``funds`` and a status
    literal, and reports only the observation set of its op: success frames
    carry the complete op subset, inconclusive frames may carry any subset,
    and refusal frames carry none (a spoofed hybrid is refused on the wire).
    """

    protocol: Literal[5] = 5
    op: FreightOp
    request_id: str
    plan: Digest
    company: CompanyID
    max_cost: Money
    pickup: TileID
    delivery: TileID
    depot: TileID
    route_digest: Digest
    engine: FreightActorId = -1
    vehicle: FreightActorId = -1
    expected_cost: Money = 0
    order_index: FreightOrderIndex = -1
    watch_ticks: FreightWatchTicks = -1
    watch_days: FreightWatchDays = -1
    status: FreightStatus
    funds: SignedMoney
    cost: Money

    paused: StrictBool | None = None
    # Site admission observations (slot 0 = pickup stop, slot 1 = delivery).
    truck0: StrictBool | None = None
    sid0: StationID | None = None
    truck1: StrictBool | None = None
    sid1: StationID | None = None
    depot_ok: StrictBool | None = None
    owner: OwnerID | None = None
    pairs_ok: FreightPairCount | None = None
    pair_total: FreightPairCount | None = None
    accept: FreightEighths | None = None
    prod: FreightAmount | None = None
    wait: FreightAmount | None = None
    vehicles: FreightAmount | None = None
    # Engine admission observations.
    available: StrictBool | None = None
    compatible: StrictBool | None = None
    capacity: FreightAmount | None = None
    cargo: FreightCargo | None = None
    # Vehicle readback observations.
    location: TileID | None = None
    state: FreightVehicleState | None = None
    in_depot: StrictBool | None = None
    speed: FreightCount | None = None
    # Order observations.
    dest: StationID | None = None
    flags: FreightFlags | None = None
    goto: StrictBool | None = None
    order_len: FreightPod | None = None
    dest0: StationID | None = None
    flags0: FreightFlags | None = None
    goto0: StrictBool | None = None
    dest1: StationID | None = None
    flags1: FreightFlags | None = None
    goto1: StrictBool | None = None
    # Monitor observations.
    pickup_amount: FreightAmount | None = None
    delivery_amount: FreightAmount | None = None
    income: SignedMoney | None = None
    delivered: FreightAmount | None = None
    # Window observations.
    load: FreightAmount | None = None
    position: TileID | None = None
    progress: FreightProgress | None = None
    tick: FreightCount | None = None
    day: FreightCount | None = None
    last_accepted: FreightDate | None = None
    # Finish facts.
    stop_issued: StrictBool | None = None

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()

    @model_validator(mode="after")
    def coherent(self) -> FreightReadback:
        if self.op not in _FREIGHT_SUCCESS_STATUS:
            raise ValueError("unknown freight op")
        subset = _FREIGHT_SUBSETS[self.op]
        present = set()
        for field in _FREIGHT_FIELDS:
            if getattr(self, field) is not None:
                present.add(field)
        outside = present - subset
        if outside:
            raise ValueError(
                f"{self.op} readback carries fields outside its subset: {sorted(outside)}"
            )
        success = self.status == _FREIGHT_SUCCESS_STATUS[self.op]
        if success:
            missing = subset - present
            if missing:
                raise ValueError(f"{self.op} success readback lacks {sorted(missing)}")
        elif self.status not in _FREIGHT_REPORTED_STATUS:  # pragma: no cover - literal exhausts
            raise ValueError("unknown freight status")
        elif self.status not in _FREIGHT_INCONCLUSIVE_STATUS and present:
            raise ValueError("refusal readback carries an unclaimed observation set")
        # Echo coherence by op position in the attempt:
        if self.op == "site":
            if self.engine != -1 or self.vehicle != -1:
                raise ValueError("site readback must not name an engine or vehicle")
        elif self.op == "engine":
            if self.vehicle != -1:
                raise ValueError("engine readback must not name a vehicle")
            if success and self.engine < 0:
                raise ValueError("engine readback must name its enumerated engine")
        elif self.op == "purchase":
            if self.order_index != -1 or self.watch_ticks != -1 or self.watch_days != -1:
                raise ValueError("purchase readback must not carry phase echoes")
            if success and (self.engine < 0 or self.vehicle < 0):
                raise ValueError("built purchase must name engine and vehicle")
            if not success and self.status in _FREIGHT_REFUSAL_STATUS and self.vehicle != -1:
                raise ValueError("refused purchase must not name a vehicle")
        elif self.op in _FREIGHT_POST_PURCHASE_OPS:
            if self.engine < 0 or self.vehicle < 0:
                raise ValueError("post-purchase readbacks echo the live engine and vehicle")
        if self.op != "order" and self.order_index != -1:
            raise ValueError("order echoes carry stop indexes")
        if self.op not in _FREIGHT_WATCH_OPS and self.watch_ticks != -1:
            raise ValueError("watch echoes belong to window exchanges")
        if self.op != "load-watch" and self.watch_days != -1:
            raise ValueError("day budgets belong to load-watch alone")
        if success and self.op in _FREIGHT_WATCH_OPS:
            if self.watch_ticks < 1:
                raise ValueError("window success must echo its tick budget")
            if self.op == "load-watch" and self.watch_days < 1:
                raise ValueError("load-watch success must echo its day budget")
        return self

    @classmethod
    def parse_for(cls, request: FreightRequest, raw: bytes):
        if len(raw) > MAX_FREIGHT_RESPONSE_BYTES:
            raise ValueError(f"application response exceeds {MAX_FREIGHT_RESPONSE_BYTES} bytes")

        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate response key")
                result[key] = value
            return result

        value = json.loads(raw, object_pairs_hook=unique)
        criteria = cls.model_validate(value)
        correlated = ("protocol", "op", "request_id", "plan", "company", "max_cost")
        if any(getattr(criteria, k) != getattr(request, k) for k in correlated):
            raise ValueError("freight response correlation mismatch")
        for key in ("pickup", "delivery", "depot", "route_digest"):
            if getattr(criteria, key) != getattr(request, key):
                raise ValueError("freight response pin mismatch")
        for key in ("engine", "vehicle", "order_index", "watch_ticks", "watch_days"):
            expected = getattr(request, key)
            if expected >= 0 and getattr(criteria, key) != expected:
                raise ValueError("freight response echo mismatch")
        if request.expected_cost > 0 and criteria.expected_cost != request.expected_cost:
            raise ValueError("freight response quote-echo mismatch")
        return criteria


PICKUP_STOP_TILE = 45748
PICKUP_FRONT_TILE = 45747
DELIVERY_STOP_TILE = 50351
DELIVERY_FRONT_TILE = 50095
DEPOT_TILE = 45487
DEPOT_FRONT_TILE = 45743
# The D4 corridor route policy's ordered witness tile count (23 road pairs).
CORRIDOR_WITNESS_LENGTH = 24


def _adjacent(a: int, b: int) -> bool:
    return _cardinal_neighbours(a, b)


class FreightPlan(Contract):
    """The geometry, identities and schedule of one D5 attempt.

    Schema 1 is the D4 close-out geometry baked exactly (candidate-5): the
    corridor truck stops and depot at their receipt-bound tiles and the
    ordered 24-tile witness. Schema 2 is the optimizer-derived form: the
    selected route is validated as bounded, contiguous, unique and
    stop/depot-consistent, while cargo, industries, funds, ceiling and the
    fifteen-exchange schedule remain the D5-fixed parameters. In both
    schemas ``digest`` binds the witness, so any route-tile change changes
    the plan identity.
    """

    schema_version: Literal[1, 2] = 1
    company: CompanyID
    cargo: FreightCargo
    pickup: TileID
    pickup_front: TileID
    delivery: TileID
    delivery_front: TileID
    depot: TileID
    depot_front: TileID
    pickup_industry: FreightIndustry
    delivery_industry: FreightIndustry
    expected_funds: Money
    max_cost: Money
    witness: tuple[TileID, ...]
    schedule: tuple[str, ...]
    request_budget: Annotated[StrictInt, Field(gt=0, le=FREIGHT_REQUEST_BUDGET)] = (
        FREIGHT_REQUEST_BUDGET
    )

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()

    @property
    def route_digest(self) -> str:
        """The wire binding every exchange must present for this plan."""
        return freight_route_digest(self.witness)

    @model_validator(mode="after")
    def coherent(self) -> FreightPlan:
        if self.company != FREIGHT_COMPANY or self.cargo != FREIGHT_CARGO_ID:
            raise ValueError("the freight plan drives company 0 with cargo 1")
        if self.schema_version == 1:
            if (self.pickup, self.pickup_front) != (PICKUP_STOP_TILE, PICKUP_FRONT_TILE):
                raise ValueError("pickup pins drifted from the D4 corridor stops")
            if (self.delivery, self.delivery_front) != (
                DELIVERY_STOP_TILE,
                DELIVERY_FRONT_TILE,
            ):
                raise ValueError("delivery pins drifted from the D4 corridor stops")
            if (self.depot, self.depot_front) != (DEPOT_TILE, DEPOT_FRONT_TILE):
                raise ValueError("depot pins drifted from the D4 corridor depot")
            if len(self.witness) != CORRIDOR_WITNESS_LENGTH or self.witness[0] == self.witness[-1]:
                raise ValueError("the plan binds the D4 corridor's 24-tile witness")
        else:
            _validate_freight_route(self.witness, self.pickup, self.delivery, self.depot)
            if self.pickup_front != self.witness[1]:
                raise ValueError("optimizer plan's pickup front is not route tile 1")
            if self.delivery_front != self.witness[-2]:
                raise ValueError("optimizer plan's delivery front is not route tile -2")
            if self.depot_front not in self.witness[1:-1]:
                raise ValueError("optimizer plan's depot front is not on the route")
            if not _adjacent(self.depot, self.depot_front):
                raise ValueError("optimizer plan's depot front is not adjacent")
        for pin, front in (
            (self.pickup, self.pickup_front),
            (self.delivery, self.delivery_front),
            (self.depot, self.depot_front),
        ):
            if not _adjacent(pin, front):
                raise ValueError("each stop pins a directly adjacent front")
        if (
            self.pickup_industry != FREIGHT_PICKUP_INDUSTRY
            or self.delivery_industry != FREIGHT_DELIVERY_INDUSTRY
        ):
            raise ValueError("industries are pinned to the retained census identities")
        if self.expected_funds != FUNDS_AT_D4_CLOSE:
            raise ValueError("the plan binds the candidate-5 close-out funds exactly")
        if self.max_cost != FREIGHT_MAX_COST:
            raise ValueError("the plan binds the per-op cost ceiling exactly")
        if self.schedule != FREIGHT_EXCHANGE_IDS:
            raise ValueError("schedule drifted from the planned fifteen exchanges")
        return self


class FreightSiteIntent(Contract):
    """Latched site admission facts from one fresh native READY readback."""

    schema_version: Literal[1] = 1
    prelaunch_digest: Digest
    plan_digest: Digest
    company: CompanyID
    cargo: FreightCargo
    pickup: TileID
    pickup_sid: StationID
    delivery: TileID
    delivery_sid: StationID
    depot: TileID
    accept: FreightEighths
    production: FreightAmount
    waiting: FreightAmount
    funds: Money
    before_digest: Digest

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()


class FreightEngineIntent(Contract):
    """Latched engine admission: one buildable truck at a tested quote."""

    schema_version: Literal[1] = 1
    prelaunch_digest: Digest
    site_digest: Digest
    company: CompanyID
    cargo: FreightCargo
    engine: Annotated[StrictInt, Field(ge=0, le=65535)]
    capacity: FreightAmount
    quote: Money
    before_digest: Digest

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()


def admit_freight_site(
    readback: FreightReadback, *, prelaunch_digest: str, plan: FreightPlan
) -> FreightSiteIntent:
    """Latch the site admission facts from a fresh native READY readback (A4).

    Requires: both stops valid truck-stop-typed stations with station ids,
    the depot company-owned at its pinned tile, the witness path fully
    re-connected on the company's road, delivery acceptance at least 1/8,
    the D4 close-out funds exactly, zero vehicles, and an unpaused world.
    The production and waiting levels are recorded as facts; any mismatch
    is a typed refusal before any mutation.
    """
    if (
        readback.op != "site"
        or readback.status != "READY"
        or readback.plan != prelaunch_digest
        or readback.company != plan.company
        or readback.cost != 0
    ):
        raise ValueError("site admission requires a correlated READY observation at zero cost")
    if (readback.pickup, readback.delivery, readback.depot) != (
        plan.pickup,
        plan.delivery,
        plan.depot,
    ):
        raise ValueError("site pins drifted from the planned corridor")
    if readback.paused is not False:
        raise ValueError("site admission requires an unpaused world")
    if readback.funds != plan.expected_funds:
        raise ValueError("site funds must equal the D4 close-out level exactly")
    if readback.vehicles is None or readback.vehicles != 0:
        raise ValueError("site admission requires a company with zero vehicles")
    if (
        readback.truck0 is not True
        or readback.truck1 is not True
        or readback.sid0 is None
        or readback.sid0 < 0
        or readback.sid1 is None
        or readback.sid1 < 0
    ):
        raise ValueError("both corridor stops must be valid truck-stop-typed stations")
    if readback.depot_ok is not True or readback.owner != plan.company:
        raise ValueError("the corridor depot must be company-owned")
    if (
        readback.pairs_ok is None
        or readback.pair_total is None
        or readback.pairs_ok != readback.pair_total
        or readback.pairs_ok != len(plan.witness) - 1
    ):
        raise ValueError("the witness path must re-check fully connected on native road")
    if readback.accept is None or readback.accept < 1:
        raise ValueError("delivery acceptance below 1/8 refuses the site admission")
    return FreightSiteIntent(
        prelaunch_digest=prelaunch_digest,
        plan_digest=plan.digest,
        company=readback.company,
        cargo=plan.cargo,
        pickup=readback.pickup,
        pickup_sid=readback.sid0,
        delivery=readback.delivery,
        delivery_sid=readback.sid1,
        depot=readback.depot,
        accept=readback.accept,
        production=readback.prod,
        waiting=readback.wait,
        funds=readback.funds,
        before_digest=readback.digest,
    )


def admit_freight_engine(
    readback: FreightReadback,
    *,
    prelaunch_digest: str,
    plan: FreightPlan,
    site: FreightSiteIntent,
) -> FreightEngineIntent:
    """Latch one admitted engine/pair under the buildable truck policy (§4)."""
    if (
        readback.op != "engine"
        or readback.status != "READY"
        or readback.plan != prelaunch_digest
        or readback.company != plan.company
        or readback.vehicle != -1
        or readback.engine < 0
    ):
        raise ValueError("engine admission requires a correlated READY enumeration")
    if (
        readback.available is not True
        or readback.compatible is not True
        or readback.capacity is None
        or readback.capacity <= 0
    ):
        raise ValueError("engine admission requires a buildable road truck with capacity")
    if readback.cargo is None or readback.cargo != plan.cargo:
        raise ValueError("the admitted engine must run the corridor cargo")
    if not 0 < readback.cost <= min(plan.max_cost, readback.funds):
        raise ValueError("engine admission requires a positive affordable tested quote")
    if readback.funds != site.funds:
        raise ValueError("engine exchange funds drifted from the admitted site")
    return FreightEngineIntent(
        prelaunch_digest=prelaunch_digest,
        site_digest=site.digest,
        company=readback.company,
        cargo=readback.cargo,
        engine=readback.engine,
        capacity=readback.capacity,
        quote=readback.cost,
        before_digest=readback.digest,
    )


def verify_freight_purchase_built(
    intent: FreightEngineIntent, before: FreightReadback, built: FreightReadback
) -> dict:
    """Verify the purchase execution result and emit its basis receipt."""
    if (
        built.op != "purchase"
        or built.status != "BUILT"
        or (
            built.plan,
            built.company,
        )
        != (intent.prelaunch_digest, intent.company)
    ):
        raise ValueError("purchase execution result correlation mismatch")
    if built.engine != intent.engine or built.vehicle < 0:
        raise ValueError("purchase result must name the admitted engine and one new vehicle")
    if built.cost != intent.quote:
        raise ValueError("purchase realized cost changed from the tested quote")
    if before.funds - built.funds != built.cost:
        raise ValueError("purchase funds must move by exactly the recorded quote")
    return dict(
        schema="company-freight-purchase-basis-receipt-v1",
        request_id=built.request_id,
        prelaunch_digest=intent.prelaunch_digest,
        before_digest=intent.before_digest,
        built_digest=built.digest,
        company=intent.company,
        engine=intent.engine,
        vehicle=built.vehicle,
        quote=intent.quote,
        cost=built.cost,
        funds=dict(before=before.funds, after=built.funds),
        verification="NATIVE_STATE_CHANGED",
    )


def verify_freight_purchase(
    intent: FreightEngineIntent,
    before: FreightReadback,
    built: FreightReadback,
    independent: FreightReadback,
    *,
    plan: FreightPlan,
) -> dict:
    """Verify the purchase group: quote, purchase and independent read.

    The independent readback re-observes the vehicle identity, capacity and
    cargo type natively (owner company, stopped in the pinned depot), and
    binds the recorded funds after the quote-exact spend.
    """
    verify_freight_purchase_built(intent, before, built)
    if (
        independent.op != "vread"
        or independent.status != "READ"
        or (
            independent.plan,
            independent.company,
        )
        != (intent.prelaunch_digest, intent.company)
    ):
        raise ValueError("independent vehicle readback correlation mismatch")
    if (independent.engine, independent.vehicle) != (intent.engine, built.vehicle):
        raise ValueError("independent readback identity mismatch")
    if (independent.owner, independent.capacity, independent.cargo) != (
        plan.company,
        intent.capacity,
        intent.cargo,
    ):
        raise ValueError("independent readback capacity or cargo mismatch")
    if (
        independent.state != "IN_DEPOT"
        or independent.in_depot is not True
        or independent.location != plan.depot
        or independent.speed != 0
    ):
        raise ValueError("purchased vehicle must be stopped in the pinned depot")
    if independent.cost != 0 or independent.funds != built.funds:
        raise ValueError("independent readback spending or funds mismatch")
    return dict(
        schema="company-freight-purchase-receipt-v1",
        execution_request_id=built.request_id,
        readback_request_id=independent.request_id,
        plan_digest=plan.digest,
        before_digest=intent.before_digest,
        built_digest=built.digest,
        after_digest=independent.digest,
        company=plan.company,
        engine=intent.engine,
        vehicle=built.vehicle,
        cargo=intent.cargo,
        capacity=intent.capacity,
        quote=intent.quote,
        cost=built.cost,
        error_code=None,
        funds=dict(before=before.funds, after=built.funds),
        verification="NATIVE_STATE_CHANGED",
    )


def verify_freight_order(
    site: FreightSiteIntent, read: FreightReadback, *, index: int, vehicle: int
) -> dict:
    """Verify one appended stop order (A6: pickup full load / delivery none).

    Destination ids are the station ids read from the site readback; the
    flags are the pinned order-flag pin values; both orders goto-station.
    """
    if read.op != "order" or read.status != "ORDERED" or read.cost != 0:
        raise ValueError("order append result mismatch")
    if read.order_index != index or read.vehicle != vehicle:
        raise ValueError("order append echo mismatch")
    expected_dest = site.pickup_sid if index == 0 else site.delivery_sid
    if read.dest is None or read.dest != expected_dest:
        raise ValueError("order destination must be the stop id from the site readback")
    if read.flags != (OF_FULL_LOAD if index == 0 else OF_NO_LOAD):
        raise ValueError("order flags drifted from the pinned load policy")
    if read.goto is not True:
        raise ValueError("orders must goto-station")
    return dict(
        schema="company-freight-order-receipt-v1",
        request_id=read.request_id,
        stop="pickup" if index == 0 else "delivery",
        order_index=index,
        dest=read.dest,
        flags=read.flags,
        goto=True,
        funds=read.funds,
        verification="NATIVE_STATE_CHANGED",
    )


def verify_freight_order_set(
    site: FreightSiteIntent,
    appends: tuple[FreightReadback, FreightReadback],
    inventory: FreightReadback,
    *,
    vehicle: int,
) -> dict:
    """Verify the exact two-order inventory over both recorded appends (A6)."""
    for index, append in enumerate(appends):
        verify_freight_order(site, append, index=index, vehicle=vehicle)
    if (
        inventory.op != "order-read"
        or inventory.status != "ORDER_SET_VERIFIED"
        or inventory.cost != 0
    ):
        raise ValueError("order inventory mismatch")
    if inventory.vehicle != vehicle or inventory.order_len != 2:
        raise ValueError("the proven order set carries exactly two orders")
    triples = (
        (inventory.dest0, inventory.flags0, inventory.goto0),
        (inventory.dest1, inventory.flags1, inventory.goto1),
    )
    if triples != ((site.pickup_sid, OF_FULL_LOAD, True), (site.delivery_sid, OF_NO_LOAD, True)):
        raise ValueError("order set drifted from the planned pickup/delivery inventory")
    return dict(
        schema="company-freight-order-set-receipt-v1",
        request_id=inventory.request_id,
        append_request_ids=(appends[0].request_id, appends[1].request_id),
        orders=(
            dict(stop="pickup", dest=site.pickup_sid, flags=OF_FULL_LOAD, goto=True),
            dict(stop="delivery", dest=site.delivery_sid, flags=OF_NO_LOAD, goto=True),
        ),
        funds=inventory.funds,
        verification="NATIVE_ORDER_SET_VERIFIED",
    )


def verify_freight_monitors(armed: FreightReadback, *, vehicle: int) -> dict:
    """Verify the pre-start monitor arming; both baselines must be zero."""
    if armed.op != "monitor" or armed.status != "ARMED" or armed.cost != 0:
        raise ValueError("monitor arming result mismatch")
    if armed.vehicle != vehicle:
        raise ValueError("monitor arming echo mismatch")
    if armed.pickup_amount != 0 or armed.delivery_amount != 0:
        raise ValueError("NONZERO_MONITOR_BASELINE")
    return dict(
        schema="company-freight-monitor-receipt-v1",
        request_id=armed.request_id,
        pickup_baseline=armed.pickup_amount,
        delivery_baseline=armed.delivery_amount,
        income_baseline=armed.income,
        delivered_baseline=armed.delivered,
        funds=armed.funds,
        verification="NATIVE_MONITOR_ARMED",
    )


def verify_freight_start(started: FreightReadback, *, vehicle: int) -> dict:
    """Verify the started vehicle readback."""
    if started.op != "start" or started.status != "STARTED" or started.cost != 0:
        raise ValueError("start result mismatch")
    if started.vehicle != vehicle or started.state != "RUNNING":
        raise ValueError("started vehicle must be natively running")
    return dict(
        schema="company-freight-start-receipt-v1",
        request_id=started.request_id,
        funds=started.funds,
        verification="NATIVE_STATE_CHANGED",
    )


def verify_freight_started(
    started: FreightReadback,
    independent: FreightReadback,
    *,
    engine: FreightEngineIntent,
    vehicle: int,
) -> dict:
    """Verify the started group including its independent post-start read."""
    verify_freight_start(started, vehicle=vehicle)
    if independent.op != "vread" or independent.status != "READ" or independent.cost != 0:
        raise ValueError("independent started readback mismatch")
    if (independent.engine, independent.vehicle) != (engine.engine, vehicle):
        raise ValueError("independent started readback identity mismatch")
    if (
        independent.owner != engine.company
        or independent.state not in ("RUNNING", "AT_STATION")
        or independent.in_depot is not False
    ):
        raise ValueError("the started vehicle must be away from the depot")
    if independent.capacity != engine.capacity or independent.cargo != engine.cargo:
        raise ValueError("independent started readback capacity or cargo mismatch")
    return dict(
        schema="company-freight-started-receipt-v1",
        execution_request_id=started.request_id,
        readback_request_id=independent.request_id,
        built_digest=started.digest,
        after_digest=independent.digest,
        funds=dict(before=started.funds, after=independent.funds),
        location=independent.location,
        verification="NATIVE_STATE_CHANGED",
    )


def verify_freight_loaded(
    loaded: FreightReadback,
    *,
    vehicle: int,
    engine: FreightEngineIntent,
    waiting_baseline: int,
) -> dict:
    """Verify the load-watch window result (A7): one positive full load.

    The waiting delta against the admitted site baseline is recorded as an
    observational corroboration only: station waiting is fed by unbounded
    industry arrivals during the window, so it can legitimately stay level
    or even rise while the vehicle loads, and it cannot fall below zero.
    No ``waiting decrement`` is therefore enforceable without inventing an
    arrival bound; the honest receipt records the delta and states why it
    is not enforced.
    """
    if loaded.op != "load-watch" or loaded.status != "LOADED" or loaded.cost != 0:
        raise ValueError("load window result mismatch")
    if loaded.vehicle != vehicle or loaded.capacity != engine.capacity:
        raise ValueError("load echo or capacity mismatch")
    if loaded.load is None or loaded.load <= 0 or loaded.load != loaded.capacity:
        raise ValueError("the observed load must be one positive full cargo load")
    if loaded.wait is None:
        raise ValueError("the loaded readback must record its station waiting level")
    waiting_delta = loaded.wait - waiting_baseline
    return dict(
        schema="company-freight-loaded-receipt-v1",
        request_id=loaded.request_id,
        load=loaded.load,
        capacity=loaded.capacity,
        waiting=loaded.wait,
        waiting_delta=waiting_delta,
        # A7 corroboration note: unbounded industry arrivals can mask the
        # decrement, so the delta is recorded evidence, not an enforced gate.
        waiting_note="station arrivals unbounded; waiting delta recorded, not enforced",
        watch_ticks=loaded.watch_ticks,
        watch_days=loaded.watch_days,
        tick=loaded.tick,
        day=loaded.day,
        funds=loaded.funds,
        verification="NATIVE_LOAD_VERIFIED",
    )


def verify_freight_arrival(
    arrived: FreightReadback,
    *,
    vehicle: int,
    load: int,
    delivery: int,
    witness_len: int,
) -> dict:
    """Verify the transit-watch window result: first full witness progress."""
    if arrived.op != "transit-watch" or arrived.status != "AT_DELIVERY" or arrived.cost != 0:
        raise ValueError("transit window result mismatch")
    if arrived.vehicle != vehicle:
        raise ValueError("transit readback echo mismatch")
    if load <= 0 or arrived.load != load:
        raise ValueError("the vehicle must read at delivery with its full load")
    if arrived.position != delivery:
        raise ValueError("the vehicle must read at the pinned delivery stop")
    if arrived.progress != witness_len - 1:
        raise ValueError("arrival must complete the witness progress")
    return dict(
        schema="company-freight-arrival-receipt-v1",
        request_id=arrived.request_id,
        position=arrived.position,
        progress=arrived.progress,
        load=arrived.load,
        watch_ticks=arrived.watch_ticks,
        tick=arrived.tick,
        day=arrived.day,
        funds=arrived.funds,
        verification="NATIVE_TRANSIT_VERIFIED",
    )


def verify_freight_delivered(unloaded: FreightReadback, *, vehicle: int, load: int) -> dict:
    """Verify the deliver-watch window result: unload plus monitor arithmetic (A8)."""
    if unloaded.op != "deliver-watch" or unloaded.status != "DELIVERED" or unloaded.cost != 0:
        raise ValueError("delivery window result mismatch")
    if unloaded.vehicle != vehicle:
        raise ValueError("delivery readback echo mismatch")
    if unloaded.load != 0:
        raise ValueError("the vehicle must read empty after its unload")
    if unloaded.pickup_amount != load or unloaded.delivery_amount != load:
        raise ValueError("monitor arithmetic must reconcile the observed load exactly")
    return dict(
        schema="company-freight-delivered-receipt-v1",
        request_id=unloaded.request_id,
        load=unloaded.load,
        pickup_amount=unloaded.pickup_amount,
        delivery_amount=unloaded.delivery_amount,
        watch_ticks=unloaded.watch_ticks,
        tick=unloaded.tick,
        day=unloaded.day,
        funds=unloaded.funds,
        verification="NATIVE_DELIVERY_VERIFIED",
    )


def verify_freight_finance(
    read: FreightReadback,
    *,
    vehicle: int,
    income0: int,
    delivered0: int,
    deliver_day: int,
) -> dict:
    """Verify the finance corroboration (A8/A9): same-quarter increase.

    The quarterly income and delivered-cargo deltas are recorded from the
    company monitors; the delivery revenue is the recorded income delta, so
    no cargo payment rate is invented. The last accepted date must sit
    within the delivery window (corroborating day - 1 tolerance).
    """
    if read.op != "finance" or read.status != "FINANCE_VERIFIED" or read.cost != 0:
        raise ValueError("finance result mismatch")
    if read.vehicle != vehicle:
        raise ValueError("finance readback echo mismatch")
    income_delta = (read.income or 0) - income0
    delivered_delta = (read.delivered or 0) - delivered0
    if income_delta <= 0:
        raise ValueError("quarter income did not increase across the deliver window")
    if delivered_delta <= 0:
        raise ValueError("quarterly delivered cargo did not increase")
    if read.last_accepted is None or read.last_accepted < deliver_day - 1:
        raise ValueError("cargo acceptance date does not corroborate the delivery window")
    return dict(
        schema="company-freight-finance-receipt-v1",
        request_id=read.request_id,
        income=read.income,
        income_baseline=income0,
        delivered=read.delivered,
        delivered_baseline=delivered0,
        deliver_day=deliver_day,
        last_accepted=read.last_accepted,
        revenue=income_delta,
        funds=read.funds,
        verification="NATIVE_FINANCE_VERIFIED",
    )


def verify_freight_finish(stopped: FreightReadback, *, vehicle: int) -> dict:
    """Verify the finish exchange: its stop command issued with final facts.

    ``PHASE_STOPPED`` records the issued stop and the vehicle's final state;
    the owned vehicle is never sold and no further authority is implied —
    the enumerable state facts are recorded exactly as read. The readback
    must prove the stop, not merely claim the command: the final state must
    read stopped (``STOPPED`` or ``IN_DEPOT``) at zero speed, and
    ``stop_issued`` is true only when the toggle was actually issued (the
    handler never re-toggles an already-stopped vehicle).
    """
    if stopped.op != "finish" or stopped.status != "PHASE_STOPPED" or stopped.cost != 0:
        raise ValueError("finish result mismatch")
    if stopped.vehicle != vehicle:
        raise ValueError("finish readback echo mismatch")
    if stopped.stop_issued is not True:
        raise ValueError("the finish exchange must report its stop command issued")
    if stopped.state not in ("STOPPED", "IN_DEPOT") or stopped.speed is None or stopped.speed != 0:
        raise ValueError("the finished vehicle must be proven stopped at zero speed")
    return dict(
        schema="company-freight-finish-receipt-v1",
        request_id=stopped.request_id,
        state=stopped.state,
        speed=stopped.speed,
        in_depot=stopped.in_depot,
        funds=stopped.funds,
        verification="NATIVE_PHASE_STOPPED",
    )


def _freight_state() -> dict:
    return dict(
        index=0,
        site=None,
        engine=None,
        vehicle=-1,
        load=0,
        reads={},
        ledger=[],
        funds=None,
    )


def _freight_success_step(
    state: dict, request: FreightRequest, readback: FreightReadback, *, plan: FreightPlan
) -> dict:
    """Run one exchange's verification against the accumulated attempt state."""
    op = request.op
    if op == "site":
        site = admit_freight_site(readback, prelaunch_digest=readback.plan, plan=plan)
        state["site"] = site
        return dict(
            schema="company-freight-site-receipt-v1",
            request_id=readback.request_id,
            prelaunch_digest=readback.plan,
            plan_digest=plan.digest,
            before_digest=readback.digest,
            site_digest=site.digest,
            company=site.company,
            pickup_sid=site.pickup_sid,
            delivery_sid=site.delivery_sid,
            depot=site.depot,
            accept=site.accept,
            production=site.production,
            waiting=site.waiting,
            vehicles=readback.vehicles,
            funds=site.funds,
            verification="SITE_ADMITTED",
        )
    if op == "engine":
        engine = admit_freight_engine(
            readback, prelaunch_digest=readback.plan, plan=plan, site=state["site"]
        )
        state["engine"] = engine
        return dict(
            schema="company-freight-engine-receipt-v1",
            request_id=readback.request_id,
            prelaunch_digest=readback.plan,
            plan_digest=plan.digest,
            before_digest=readback.digest,
            engine_digest=engine.digest,
            site_digest=engine.site_digest,
            company=engine.company,
            engine=engine.engine,
            cargo=engine.cargo,
            capacity=engine.capacity,
            quote=engine.quote,
            funds=readback.funds,
            verification="ENGINE_ADMITTED",
        )
    if op == "purchase":
        receipt = verify_freight_purchase_built(
            state["engine"], state["reads"]["engine-00"], readback
        )
        state["vehicle"] = readback.vehicle
        return receipt
    if op == "vread" and request.request_id == "vread-00":
        return verify_freight_purchase(
            state["engine"],
            state["reads"]["engine-00"],
            state["reads"]["purchase-00"],
            readback,
            plan=plan,
        )
    if op == "order":
        return verify_freight_order(
            state["site"], readback, index=request.order_index, vehicle=state["vehicle"]
        )
    if op == "order-read":
        return verify_freight_order_set(
            state["site"],
            (state["reads"]["order-00"], state["reads"]["order-01"]),
            readback,
            vehicle=state["vehicle"],
        )
    if op == "monitor":
        state["monitor"] = readback
        return verify_freight_monitors(readback, vehicle=state["vehicle"])
    if op == "start":
        return verify_freight_start(readback, vehicle=state["vehicle"])
    if op == "vread" and request.request_id == "vread-01":
        return verify_freight_started(
            state["reads"]["start-00"], readback, engine=state["engine"], vehicle=state["vehicle"]
        )
    if op == "load-watch":
        receipt = verify_freight_loaded(
            readback,
            vehicle=state["vehicle"],
            engine=state["engine"],
            waiting_baseline=state["site"].waiting,
        )
        state["load"] = receipt["load"]
        return receipt
    if op == "transit-watch":
        return verify_freight_arrival(
            readback,
            vehicle=state["vehicle"],
            load=state["load"],
            delivery=plan.delivery,
            witness_len=len(plan.witness),
        )
    if op == "deliver-watch":
        return verify_freight_delivered(readback, vehicle=state["vehicle"], load=state["load"])
    if op == "finance":
        monitor = state["reads"]["monitor-00"]
        deliver = state["reads"]["deliver-00"]
        return verify_freight_finance(
            readback,
            vehicle=state["vehicle"],
            income0=monitor.income,
            delivered0=monitor.delivered,
            deliver_day=deliver.day,
        )
    if op == "finish":
        return verify_freight_finish(readback, vehicle=state["vehicle"])
    raise ValueError(f"unhandled freight op {op}")  # pragma: no cover


def _freight_verify_step(
    state: dict,
    request: FreightRequest,
    readback: FreightReadback,
    *,
    prelaunch_digest: str,
    plan: FreightPlan,
) -> dict:
    """Verify one ordered exchange as the fixed schedule prescribes."""
    expected = FREIGHT_EXCHANGE_IDS[state["index"]]
    if request.request_id != expected or readback.request_id != expected:
        raise ValueError(f"freight exchange out of order: expected {expected}")
    if request.op != _FREIGHT_OP_BY_ID[expected]:
        raise ValueError("freight request op disagrees with its planned exchange")
    if (readback.plan, readback.company) != (prelaunch_digest, plan.company):
        raise ValueError("freight readback is not plan-scoped")
    if (readback.pickup, readback.delivery, readback.depot) != (
        plan.pickup,
        plan.delivery,
        plan.depot,
    ):
        raise ValueError("freight readback pins drifted from the planned corridor")
    expected_route = plan.witness if request.op == "site" else None
    if request.route != expected_route:
        raise ValueError("freight request route drifted from the planned witness")
    if request.route_digest != plan.route_digest:
        raise ValueError("freight request route digest drifted from the planned witness")
    if readback.route_digest != plan.route_digest:
        raise ValueError("freight readback route digest drifted from the planned witness")
    if request.max_cost != plan.max_cost:
        raise ValueError("request ceiling drifted from the planned ceiling")
    if request.expected_cost != readback.expected_cost:
        raise ValueError("request and readback quote echoes disagree")
    op = request.op
    if readback.status != _FREIGHT_SUCCESS_STATUS[op]:
        raise ValueError(f"freight exchange {expected} ended {readback.status}")
    try:
        receipt = _freight_success_step(state, request, readback, plan=plan)
    finally:
        state["reads"][request.request_id] = readback
    delta = None if state["funds"] is None else readback.funds - state["funds"]
    state["ledger"].append(
        dict(
            exchange=request.request_id,
            op=op,
            status=readback.status,
            funds=readback.funds,
            delta=delta,
        )
    )
    state["funds"] = readback.funds
    state["index"] += 1
    return receipt


def verify_freight_cycle(
    exchanges: list[tuple[FreightRequest, FreightReadback]],
    *,
    prelaunch_digest: str,
    plan: FreightPlan,
) -> dict:
    """Verify the fixed fifteen-exchange freight cycle and emit the receipts.

    Ordered-unique: exchange ``k`` must be the schedule's planned exchange
    ``k``; any refusal, inconclusive window or verification defect halts the
    cycle with a raised error and the prefix evidence already latched. This
    verifies evidence; it never issues requests.
    """
    if len(exchanges) != PLANNED_FREIGHT_EXCHANGES:
        raise ValueError("the freight cycle verifies only its fixed fifteen exchanges")
    state = _freight_state()
    receipts: list[dict] = []
    for request, readback in exchanges:
        receipts.append(
            _freight_verify_step(
                state, request, readback, prelaunch_digest=prelaunch_digest, plan=plan
            )
        )
    return dict(
        schema="company-freight-cycle-receipt-v1",
        prelaunch_digest=prelaunch_digest,
        plan_digest=plan.digest,
        company=plan.company,
        engine=state["engine"].engine,
        vehicle=state["vehicle"],
        load=state["load"],
        receipts=receipts,
        funds_ledger=state["ledger"],
        funds=state["reads"]["finish-00"].funds,
        verification="FREIGHT_CYCLE_VERIFIED",
    )


def freight_phase_outcome(
    exchanges: list[tuple[FreightRequest, FreightReadback]],
    *,
    prelaunch_digest: str,
    plan: FreightPlan,
) -> dict:
    """Fail-closed freight-cycle verification over preserved evidence only.

    Each exchange is ``(request, readback)``. The first halted exchange ends
    verification: earlier receipts are preserved, later exchanges are
    pending, and no retry or compensating mutation is represented or
    implied. Inconclusive window halts keep the world state honest
    (inconclusive, never a success); refusals that can only fire after an
    op's mutation command are labelled UNCERTAIN_AFTER_FAILED_COMMAND, never
    as leaving the world unchanged; other admission refusals halt before any
    mutation; a successful status that fails verification leaves the world
    explicitly uncertain. This verifies evidence; it never issues requests.
    """
    receipts: list[dict] = []
    failed = None
    pending: list[str] = []
    state = _freight_state()
    for request, readback in exchanges:
        if failed is not None:
            pending.append(request.request_id)
            continue
        try:
            receipts.append(
                _freight_verify_step(
                    state, request, readback, prelaunch_digest=prelaunch_digest, plan=plan
                )
            )
        except Exception as error:  # noqa: BLE001 - fail closed on any defect
            status = getattr(readback, "status", "")
            if status in _FREIGHT_INCONCLUSIVE_STATUS:
                world = "INCONCLUSIVE_WINDOW"
            elif status in _FREIGHT_SUCCESS_STATUS.values():
                world = "UNCERTAIN_AFTER_FAILED_COMMAND"
            elif status in _FREIGHT_POST_MUTATION_STATUS.get(
                getattr(request, "op", None), frozenset()
            ):
                world = "UNCERTAIN_AFTER_FAILED_COMMAND"
            else:
                world = "HALTED_BEFORE_MUTATION"
            failed = dict(
                label=request.request_id,
                status=str(status),
                error=str(error),
                world_state=world,
            )
    complete = failed is None and len(exchanges) == PLANNED_FREIGHT_EXCHANGES
    return dict(
        schema="freight-phase-outcome-v1",
        completed=receipts,
        failed=failed,
        pending=pending,
        verification="PHASE_COMPLETE" if complete else "PARTIAL_EXECUTION_EVIDENCE",
    )
