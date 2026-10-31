"""Native corridor terrain-survey wire contract (protocol 7, additive).

Milestone ``D5-TERRAIN-SURVEY-1``: after the halted
``D5-CORRIDOR-EXTENSION-1`` attempt (2026-10-29) proved live slope 9/8 at the
predecessor's delivery-terrace stop, the terrain-aware recovery design
(``docs/handoff/2026-10-29/d5-corridor-recovery-terrain-aware-design.md``)
moved the extension branch to the stop tile 50863 fronting 50864 — with the
stop/front's live slope, vacancy and the whole branch's live terrain declared
UNKNOWN until a native verify. This module is the read-only instrument for
that verify, strictly additive over protocol 6 (the two never share a
session schedule): it observes, per pinned branch tile, the same live facts
the extension's stage-0 gate inspects (``GSTile.GetSlope``/``GetMinHeight``/
``GetMaxHeight``/``IsBuildable``/``GetOwner``, the tree/water/coast/farm/
rock/rough obstruction predicates, and the four ``HasTransportType`` road/
rail/water/air facts), plus the acceptance control pair (the consumed
attempt's delivery stop 50351, expected zero, and the proposed stop 50863)
under the measured native radius, exactly as protocol 6 measures it.

The survey is pure observation with zero cost on every exchange. It never
builds, never proves buildability of a station before its front road exists,
and never proves a freight route. The D3 terraform receipts predict the
stop/front corner points were never raised, but that prediction is
hypothesis-grade: a nonzero live slope here is a FINDING of record, never a
survey failure.

Protocol 7 stays additive over protocols 5 and 6: the GameScript bridge
dispatches protocol-7 tables through a separate guarded terrain handler,
while the freight (protocol 5) and acceptance-survey (protocol 6)
schedules, latches and request budgets stay untouched. Named constants
(E33's lesson): request and response bodies are canonical UTF-8 JSON
bounded by MAX_TERRAIN_REQUEST_BYTES / MAX_TERRAIN_RESPONSE_BYTES (512
each — the largest response is one tile's fact set plus its echoes, far
below the protocol-5 640 precedent).

History: the original survey (``D5-TERRAIN-SURVEY-1``, consumed) observed
six branch tiles (50095, 50096, 50352, 50608, 50864, 50863) plus the
acceptance pair (control 50351, stop 50863). The proposed corrected
terminal design places the bay truck stop on 50862 fronting 50863 — a
tile the consumed survey never observed, with an acceptance hypothesis
taken before the spur decision. This module's pins are the read-only
instrument for the follow-up survey
(``D5-CORRIDOR-EXTENSION-3-SURVEY-1``): the same branch tiles are
re-measured (an old observation is never recycled as fresh evidence),
50862 is added as the proposed station tile, and the acceptance stop is
re-pointed at that same proposed station ground.
"""
import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, StrictInt, model_validator

from app.planning.canonical import canonical_bytes
from app.planning.domain import Contract, Digest
from app.simulation.openttd.corridor_accept_survey import FUNDS_AT_D4_CLOSE
from app.simulation.openttd.corridor_construction import (
    CompanyID,
    Money,
    SignedMoney,
    TileID,
)

TERRAIN_SURVEY_PROTOCOL = 7
MAX_TERRAIN_REQUEST_BYTES = 512
MAX_TERRAIN_RESPONSE_BYTES = 512
# The native slope enum and heights are engine-bounded far below 255; a
# larger value is an out-of-range observation, refused before it can be
# recorded as measured.
MAX_TERRAIN_SLOPE = 255
MAX_TERRAIN_HEIGHT = 255
MAX_TERRAIN_RADIUS = 255
TERRAIN_MAP_WIDTH = 256
TERRAIN_MAP_HEIGHT = 256
TERRAIN_MAX_TILE_ID = TERRAIN_MAP_WIDTH * TERRAIN_MAP_HEIGHT - 1
PLANNED_TERRAIN_EXCHANGES = 10
TERRAIN_REQUEST_BUDGET = 32
TERRAIN_COMPANY = 0
TERRAIN_CARGO_ID = 1

# The pinned corridor world every terrain-survey request echoes (the
# authoritative D4 candidate-5 after-save geometry; stop/depot identity
# defence reuses the protocol-5 pins — the survey never queries un-pinned
# tiles).
TERRAIN_PICKUP_TILE = 45748
TERRAIN_PICKUP_FRONT_TILE = 45747
TERRAIN_DELIVERY_TILE = 50351
TERRAIN_DELIVERY_FRONT_TILE = 50095
TERRAIN_DEPOT_TILE = 45487
TERRAIN_DEPOT_FRONT_TILE = 45743

# The pinned terrain-observation tiles of this survey, in schedule order:
# the built delivery front (its live company-road fact defends the join
# start), the four south-branch full-run tiles, the proposed spur-end road
# tile, and — added by the D5-CORRIDOR-EXTENSION-3 survey — the proposed
# station ground 50862. Every tile is re-measured fresh by this survey;
# the consumed D5-TERRAIN-SURVEY-1 evidence is never recycled as a fresh
# observation.
TERRAIN_TILES: tuple[int, ...] = (50095, 50096, 50352, 50608, 50864, 50863, 50862)
# The acceptance control pair: the consumed attempt's delivery stop
# (expected zero by the E36 finding of record, re-measured, never assumed)
# and the proposed stop tile of this survey.
TERRAIN_ACCEPT_CONTROL_TILE = TERRAIN_DELIVERY_TILE
TERRAIN_ACCEPT_STOP_TILE = 50862
TERRAIN_ACCEPT_TILES: tuple[int, ...] = (
    TERRAIN_ACCEPT_CONTROL_TILE,
    TERRAIN_ACCEPT_STOP_TILE,
)

TERRAIN_OPS = ("radius", "tile", "accept")

TerrainOp = Literal["radius", "tile", "accept"]

TerrainStatus = Literal[
    "READY",
    "UNSUPPORTED_NATIVE_FACT",
    "INVALID_LOCATION",
    "INVALID_COMPANY",
    "PAUSED",
    "STALE_PIN",
    "OUT_OF_ORDER",
]

_TERRAIN_SEQUENCE: tuple[tuple[str, TerrainOp], ...] = (
    ("radius-00", "radius"),
    ("tile-00", "tile"),
    ("tile-01", "tile"),
    ("tile-02", "tile"),
    ("tile-03", "tile"),
    ("tile-04", "tile"),
    ("tile-05", "tile"),
    ("tile-06", "tile"),
    ("accept-00", "accept"),
    ("accept-01", "accept"),
)
TERRAIN_EXCHANGE_IDS: tuple[str, ...] = tuple(i for i, _ in _TERRAIN_SEQUENCE)
_TERRAIN_OP_BY_ID: dict[str, TerrainOp] = dict(_TERRAIN_SEQUENCE)
_TILE_BY_EXCHANGE: dict[str, int] = {
    "tile-00": TERRAIN_TILES[0],
    "tile-01": TERRAIN_TILES[1],
    "tile-02": TERRAIN_TILES[2],
    "tile-03": TERRAIN_TILES[3],
    "tile-04": TERRAIN_TILES[4],
    "tile-05": TERRAIN_TILES[5],
    "tile-06": TERRAIN_TILES[6],
}
_ACCEPT_TILE_BY_EXCHANGE: dict[str, int] = {
    "accept-00": TERRAIN_ACCEPT_CONTROL_TILE,
    "accept-01": TERRAIN_ACCEPT_STOP_TILE,
}
_TERRAIN_SUCCESS_STATUS: dict[TerrainOp, str] = {
    "radius": "READY",
    "tile": "READY",
    "accept": "READY",
}
_TERRAIN_REFUSAL_STATUS = frozenset(
    {
        "UNSUPPORTED_NATIVE_FACT",
        "INVALID_LOCATION",
        "INVALID_COMPANY",
        "PAUSED",
        "STALE_PIN",
        "OUT_OF_ORDER",
    }
)
if (
    len(TERRAIN_EXCHANGE_IDS) != PLANNED_TERRAIN_EXCHANGES
    or len(set(TERRAIN_EXCHANGE_IDS)) != PLANNED_TERRAIN_EXCHANGES
    or set(_TERRAIN_OP_BY_ID.values()) != set(TERRAIN_OPS)
    or _TILE_BY_EXCHANGE
    != {
        "tile-00": 50095,
        "tile-01": 50096,
        "tile-02": 50352,
        "tile-03": 50608,
        "tile-04": 50864,
        "tile-05": 50863,
        "tile-06": 50862,
    }
    or _ACCEPT_TILE_BY_EXCHANGE != {"accept-00": 50351, "accept-01": 50862}
):
    raise RuntimeError("terrain-survey exchange schedule drifted from the pinned observations")


class TerrainSurveyPlan(Contract):
    """The pinned identities and ordered observations of one terrain survey.

    The plan binds the authoritative D4 candidate-5 after-save identity: the
    corridor pins funds and world exactly as protocols 5 and 6 do, and pins
    the ordered terrain-observation tiles plus the two acceptance tiles that
    every exchange must query in order. Staging and sealing remain the
    adopted ceremony's gates; this plan types what those stages must bind.
    """

    schema_version: Literal[1] = 1
    company: CompanyID
    cargo: Annotated[StrictInt, Field(ge=0, le=63)]
    pickup: TileID
    pickup_front: TileID
    delivery: TileID
    delivery_front: TileID
    depot: TileID
    depot_front: TileID
    expected_funds: Money
    terra_tiles: tuple[TileID, ...]
    accept_tiles: tuple[TileID, ...]
    schedule: tuple[str, ...]
    request_budget: Annotated[StrictInt, Field(gt=0, le=TERRAIN_REQUEST_BUDGET)] = (
        TERRAIN_REQUEST_BUDGET
    )

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()

    @model_validator(mode="after")
    def coherent(self) -> TerrainSurveyPlan:
        if self.company != TERRAIN_COMPANY or self.cargo != TERRAIN_CARGO_ID:
            raise ValueError("the terrain survey drives company 0 with cargo 1")
        if (self.pickup, self.pickup_front) != (TERRAIN_PICKUP_TILE, TERRAIN_PICKUP_FRONT_TILE):
            raise ValueError("pickup pins drifted from the D4 corridor stops")
        if (self.delivery, self.delivery_front) != (
            TERRAIN_DELIVERY_TILE,
            TERRAIN_DELIVERY_FRONT_TILE,
        ):
            raise ValueError("delivery pins drifted from the D4 corridor stops")
        if (self.depot, self.depot_front) != (TERRAIN_DEPOT_TILE, TERRAIN_DEPOT_FRONT_TILE):
            raise ValueError("depot pins drifted from the D4 corridor depot")
        if self.expected_funds != FUNDS_AT_D4_CLOSE:
            raise ValueError("the plan binds the candidate-5 close-out funds exactly")
        if len(self.terra_tiles) != len(TERRAIN_TILES) or tuple(self.terra_tiles) != TERRAIN_TILES:
            raise ValueError("terrain tiles drifted from the pinned observation order")
        if (
            len(self.accept_tiles) != len(TERRAIN_ACCEPT_TILES)
            or tuple(self.accept_tiles) != TERRAIN_ACCEPT_TILES
        ):
            raise ValueError("acceptance tiles drifted from the pinned control-first pair")
        if self.schedule != TERRAIN_EXCHANGE_IDS:
            raise ValueError("schedule drifted from the planned ten terrain-survey exchanges")
        return self


def terrain_survey_plan() -> TerrainSurveyPlan:
    """The pinned ``D5-TERRAIN-SURVEY-1`` plan derived from the module's pins."""
    return TerrainSurveyPlan(
        company=TERRAIN_COMPANY,
        cargo=TERRAIN_CARGO_ID,
        pickup=TERRAIN_PICKUP_TILE,
        pickup_front=TERRAIN_PICKUP_FRONT_TILE,
        delivery=TERRAIN_DELIVERY_TILE,
        delivery_front=TERRAIN_DELIVERY_FRONT_TILE,
        depot=TERRAIN_DEPOT_TILE,
        depot_front=TERRAIN_DEPOT_FRONT_TILE,
        expected_funds=FUNDS_AT_D4_CLOSE,
        terra_tiles=TERRAIN_TILES,
        accept_tiles=TERRAIN_ACCEPT_TILES,
        schedule=TERRAIN_EXCHANGE_IDS,
    )


class TerrainRequest(Contract):
    """One protocol-7 terrain-survey exchange request (fixed correlation stride).

    Every request carries the corridor identity pins (defence in depth: the
    native handler refuses a drifted pin before any observation), the
    uniform ``plan`` seal digest, and — on ``tile`` and ``accept`` exactly —
    the one tile it queries. ``max_cost`` is 0 on every terrain-survey
    exchange: the survey has no cost-bearing operation of any kind.
    """

    protocol: Literal[7] = 7
    op: TerrainOp
    request_id: Annotated[str, Field(pattern=r"^[a-z0-9-]{1,32}$")]
    plan: Digest
    company: CompanyID
    max_cost: Annotated[StrictInt, Field(ge=0, le=0)]
    pickup: TileID
    delivery: TileID
    depot: TileID
    tile: TileID | None = None

    @model_validator(mode="after")
    def coherent(self) -> TerrainRequest:
        if self.op in ("tile", "accept"):
            if self.tile is None:
                raise ValueError(f"{self.op} requests carry exactly one pinned observation tile")
            tiles = TERRAIN_TILES if self.op == "tile" else TERRAIN_ACCEPT_TILES
            if self.tile not in tiles:
                raise ValueError(f"{self.op} requests may only query the pinned survey tiles")
        elif self.tile is not None:
            raise ValueError("only the tile and accept ops carry a tile")
        return self

    def to_bytes(self) -> bytes:
        raw = canonical_bytes(self)
        if len(raw) > MAX_TERRAIN_REQUEST_BYTES:
            raise ValueError(f"terrain request exceeds {MAX_TERRAIN_REQUEST_BYTES} bytes")
        return raw


_TERRAIN_MEASUREMENT_FIELDS = (
    "radius",
    "tile",
    "accept",
    "slope",
    "min_height",
    "max_height",
    "buildable",
    "owner",
    "tree",
    "water",
    "coast",
    "farm",
    "rock",
    "rough",
    "road",
    "rail",
    "water_transport",
    "air_transport",
)

_TERRAIN_SUBSETS: dict[TerrainOp, frozenset[str]] = {
    "radius": frozenset(("radius",)),
    "tile": frozenset(
        (
            "tile",
            "slope",
            "min_height",
            "max_height",
            "buildable",
            "owner",
            "tree",
            "water",
            "coast",
            "farm",
            "rock",
            "rough",
            "road",
            "rail",
            "water_transport",
            "air_transport",
        )
    ),
    "accept": frozenset(("accept", "radius")),
}
# Tile echo positions: the tile/accept response must echo the tile it
# observed so a stale or cross-tile readback can never be mistaken for a
# fresh one.
_TILE_ECHO_OPS = frozenset({"tile", "accept"})


class TerrainReadback(Contract):
    """One protocol-7 terrain-survey exchange response (strict per-op subsets).

    The handler echoes the request correlation keys, ``funds`` and a status
    literal. Success frames carry the complete op subset — a full tile fact
    set, or an acceptance reading plus the radius it was measured under.
    Refusal frames carry none (a spoofed hybrid is refused on the wire).
    Every success value is domain-checked here: a value outside the native
    slope/height/radius/eighths bounds is an out-of-range observation that
    can never parse, so the fail-closed surface cannot accidentally record
    it as measured.
    """

    protocol: Literal[7] = 7
    op: TerrainOp
    request_id: str
    plan: Digest
    company: CompanyID
    max_cost: Money
    pickup: TileID
    delivery: TileID
    depot: TileID
    tile: TileID | None = None
    status: TerrainStatus
    funds: SignedMoney
    cost: Money
    radius: Annotated[StrictInt, Field(ge=0, le=MAX_TERRAIN_RADIUS)] | None = None
    accept: Annotated[StrictInt, Field(ge=0, le=8)] | None = None
    slope: Annotated[StrictInt, Field(ge=0, le=MAX_TERRAIN_SLOPE)] | None = None
    min_height: Annotated[StrictInt, Field(ge=0, le=MAX_TERRAIN_HEIGHT)] | None = None
    max_height: Annotated[StrictInt, Field(ge=0, le=MAX_TERRAIN_HEIGHT)] | None = None
    buildable: bool | None = None
    owner: Annotated[StrictInt, Field(ge=-2, le=65535)] | None = None
    tree: bool | None = None
    water: bool | None = None
    coast: bool | None = None
    farm: bool | None = None
    rock: bool | None = None
    rough: bool | None = None
    road: bool | None = None
    rail: bool | None = None
    water_transport: bool | None = None
    air_transport: bool | None = None

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()

    @model_validator(mode="after")
    def coherent(self) -> TerrainReadback:
        if self.op not in _TERRAIN_SUCCESS_STATUS:
            raise ValueError("unknown terrain-survey op")
        subset = _TERRAIN_SUBSETS[self.op]
        # The tile echo (protocol-6 precedent) is a correlation key, not an
        # observation: refusal frames may carry it, so it is excluded from
        # the refused "unclaimed observation set" check.
        present = {
            f for f in _TERRAIN_MEASUREMENT_FIELDS if f != "tile" and getattr(self, f) is not None
        }
        outside = present - subset
        if outside:
            raise ValueError(
                f"{self.op} readback carries fields outside its subset: {sorted(outside)}"
            )
        success = self.status == _TERRAIN_SUCCESS_STATUS[self.op]
        if success:
            missing = subset - present - {"tile"}
            if missing:
                raise ValueError(f"{self.op} success readback lacks {sorted(missing)}")
            if self.op in _TILE_ECHO_OPS:
                if self.tile is None:
                    raise ValueError(f"{self.op} success must echo its observed tile")
                if self.op == "accept" and self.radius is None:
                    raise ValueError("accept success must echo its native radius")
        elif self.status not in _TERRAIN_REFUSAL_STATUS:  # pragma: no cover - literal exhausts
            raise ValueError("unknown terrain-survey status")
        elif present:
            raise ValueError("refusal readback carries an unclaimed observation set")
        if self.op == "radius" and self.tile is not None:
            raise ValueError("radius readback must not name a tile")
        return self

    @classmethod
    def parse_for(cls, request: TerrainRequest, raw: bytes):
        if len(raw) > MAX_TERRAIN_RESPONSE_BYTES:
            raise ValueError(f"terrain response exceeds {MAX_TERRAIN_RESPONSE_BYTES} bytes")

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
            raise ValueError("terrain response correlation mismatch")
        for key in ("pickup", "delivery", "depot"):
            if getattr(criteria, key) != getattr(request, key):
                raise ValueError("terrain response pin mismatch")
        if request.tile is not None and criteria.tile != request.tile:
            raise ValueError("terrain response tile echo mismatch")
        return criteria


def verify_request_against_terrain_survey_plan(
    request: TerrainRequest, *, plan: TerrainSurveyPlan, seal: str
) -> None:
    """Refuse a request that is not bound to the local terrain-survey plan.

    Python is the trust anchor: every request must present the staged seal,
    the pinned corridor identity and — for tile/accept — exactly the pinned
    observation tile of its scheduled exchange. This runs before any byte
    reaches the Admin session.
    """
    if request.plan != seal:
        raise ValueError("request plan digest is not the staged prelaunch seal")
    if request.company != plan.company:
        raise ValueError("request company drifted from the planned company")
    if (request.pickup, request.delivery, request.depot) != (
        plan.pickup,
        plan.delivery,
        plan.depot,
    ):
        raise ValueError("request pins drifted from the planned corridor")
    if request.op == "tile":
        exchange_index = (
            TERRAIN_EXCHANGE_IDS.index(request.request_id)
            if request.request_id in TERRAIN_EXCHANGE_IDS
            else -1
        )
        expected = _TILE_BY_EXCHANGE.get(request.request_id)
        if (
            exchange_index < 1
            or expected is None
            or request.tile != expected
            or request.tile != plan.terra_tiles[exchange_index - 1]
        ):
            raise ValueError("tile request drifted from the planned observation")
    if request.op == "accept":
        expected = _ACCEPT_TILE_BY_EXCHANGE.get(request.request_id)
        if expected is None or request.tile != expected:
            raise ValueError("accept request tile drifted from the planned observation")


_TERRAIN_OBSERVATION_KINDS = ("MEASURED", "REFUSED", "MISSING", "MALFORMED")


def _terrain_state() -> dict:
    return dict(
        index=0,
        terra={},
        observations={},
        ledger=[],
        funds=None,
    )


def _terrain_read_step(
    state: dict,
    request: TerrainRequest,
    readback: TerrainReadback,
    *,
    plan: TerrainSurveyPlan,
    seal: str,
) -> dict:
    """Verify one ordered terrain-survey exchange against the state."""
    expected = TERRAIN_EXCHANGE_IDS[state["index"]]
    if request.request_id != expected or readback.request_id != expected:
        raise ValueError(f"terrain exchange out of order: expected {expected}")
    verify_request_against_terrain_survey_plan(request, plan=plan, seal=seal)
    if readback.status != "READY":
        raise ValueError(f"terrain exchange {expected} ended {readback.status}")
    if readback.funds != plan.expected_funds:
        raise ValueError("terrain survey funds must equal the D4 close-out level exactly")
    if readback.cost != 0:
        raise ValueError("terrain survey exchanges must observe at zero cost")
    # Paused and unpinned worlds are refused inside the handler; a
    # correlated READY reply is the only surface that may record a fact.
    if request.op == "radius":
        state["radius"] = readback.radius
    if request.op == "tile":
        tile = plan.terra_tiles[state["index"] - 1]
        state["terra"][tile] = dict(
            slope=readback.slope,
            min_height=readback.min_height,
            max_height=readback.max_height,
            buildable=readback.buildable,
            owner=readback.owner,
            tree=readback.tree,
            water=readback.water,
            coast=readback.coast,
            farm=readback.farm,
            rock=readback.rock,
            rough=readback.rough,
            road=readback.road,
            rail=readback.rail,
            water_transport=readback.water_transport,
            air_transport=readback.air_transport,
            request_id=readback.request_id,
            digest=readback.digest,
        )
    if request.op == "accept":
        radius = state.get("radius")
        if radius is None:
            raise ValueError("acceptance requires the measured native radius first")
        tile = request.tile
        state["observations"][tile] = dict(
            value=readback.accept,
            radius=radius,
            request_id=readback.request_id,
            digest=readback.digest,
        )
    state["ledger"].append(
        dict(
            exchange=request.request_id,
            op=request.op,
            status=readback.status,
            funds=readback.funds,
        )
    )
    state["funds"] = readback.funds
    state["index"] += 1
    receipt = dict(
        schema="company-terrain-survey-receipt-v1",
        request_id=readback.request_id,
        op=request.op,
        plan_digest=plan.digest,
        seal=seal,
        status=readback.status,
        funds=readback.funds,
        verification="SURVEY_OBSERVED",
    )
    if request.op in _TILE_ECHO_OPS:
        receipt.update(tile=request.tile)
    if request.op == "radius":
        receipt.update(radius=readback.radius)
    elif request.op == "tile":
        receipt.update(
            slope=readback.slope,
            min_height=readback.min_height,
            max_height=readback.max_height,
            buildable=readback.buildable,
            owner=readback.owner,
        )
    elif request.op == "accept":
        receipt.update(accept=readback.accept, radius=readback.radius)
    return receipt


def terrain_phase_outcome(
    exchanges: list[tuple[TerrainRequest, TerrainReadback | Exception]],
    *,
    prelaunch_digest: str,
    plan: TerrainSurveyPlan,
) -> dict:
    """Fail-closed terrain-survey verification over preserved evidence only.

    Each exchange is ``(request, readback_or_error)``; an error element is
    an observation whose bytes never parsed or correlated (malformed,
    stale, torn or duplicate). The first halted exchange ends
    verification: earlier receipts are preserved, later exchanges are
    pending, and an unfinished schedule can never manufacture success.
    Exchange-level verdicts are recorded per observation kind:

    - ``MEASURED`` — a correlated READY readback whose domain-checked fact
      set (including its tile echo, or acceptance radius echo) was
      accepted; a measured nonzero slope or an occupied tile is a FINDING,
      not a survey failure;
    - ``REFUSED`` — a typed refusal (out-of-map tile, unpaused/pin/company
      drift, unsupported native fact) carrying no observation set;
    - ``MISSING`` — a scheduled exchange without a readback;
    - ``MALFORMED`` — the attached error element for that exchange.
    """
    receipts: list[dict] = []
    failed = None
    state = _terrain_state()
    for request, readback in exchanges:
        if failed is not None:
            continue
        if isinstance(readback, Exception):
            failed = dict(
                label=request.request_id,
                status="MALFORMED",
                error=str(readback),
                world_state="HALTED_BEFORE_MUTATION",
            )
            continue
        try:
            receipts.append(
                _terrain_read_step(state, request, readback, plan=plan, seal=prelaunch_digest)
            )
        except Exception as error:  # noqa: BLE001 - fail closed on any defect
            failed = dict(
                label=request.request_id,
                status=str(getattr(readback, "status", "UNKNOWN")),
                error=str(error),
                world_state="HALTED_BEFORE_MUTATION",
            )
            continue
    complete = failed is None and len(exchanges) == PLANNED_TERRAIN_EXCHANGES
    pending = (
        list(TERRAIN_EXCHANGE_IDS[len(exchanges) :])
        if failed is None
        else list(TERRAIN_EXCHANGE_IDS[TERRAIN_EXCHANGE_IDS.index(failed["label"]) + 1 :])
    )
    return dict(
        schema="terrain-survey-phase-outcome-v1",
        seal=prelaunch_digest,
        plan_digest=plan.digest,
        receipts=receipts,
        failed=failed,
        pending=pending,
        terra=state["terra"],
        observations=state["observations"],
        radius=state.get("radius"),
        funds=state["funds"],
        observation_kinds=_TERRAIN_OBSERVATION_KINDS,
        verification="SURVEY_COMPLETE" if complete else "SURVEY_INCOMPLETE",
    )
