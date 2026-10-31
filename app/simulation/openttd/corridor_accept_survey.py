"""Native corridor acceptance-survey wire contract (protocol 6, additive).

Milestone D5-ACCEPT-SURVEY-1: after the consumed ``D5-FREIGHT-1`` attempt
recorded the finding of record — delivery stop 50351 (front 50095) has zero
cargo-1 native acceptance because the only coal-accepting tile of industry 1
(tile 51373, 173,200) lies outside the stop's effective catchment — the next
authority-gated step is a strictly read-only acceptance survey over the
authoritative D4 candidate-5 after-save. This module is the protocol-6 wire
contract for that survey: typed requests, fail-closed response parsing, a
pinned observation schedule, and a fail-closed survey verifier that
distinguishes a measured zero from a missing, malformed, stale, out-of-range
or inconclusive observation.

The survey is pure observation: it queries the native truck-stop coverage
radius (``GSStation.GetCoverageRadius``) and tile-level cargo-1 acceptance
(``GSTile.GetCargoAcceptance(tile, cargo, 1, 1, radius)`` — the same API the
proven D5 site admission uses, recorded as the acceptance-API pin in the D5
preparation docs), plus the pickup-side production control
(``GSIndustry.GetLastMonthProduction``). It never builds a stop, never proves
buildability and never proves a freight route; positive acceptance alone is
catchment evidence, not route evidence.

Protocol 6 stays additive over protocol 5 (the two never share a session
schedule): the GameScript bridge dispatches protocol 6 tables through a
separate guarded survey handler, while the freight schedule, latches and
request budget accounting stay untouched. Named constants (E33's lesson):
request and response bodies are canonical UTF-8 JSON bounded by
MAX_SURVEY_REQUEST_BYTES / MAX_SURVEY_RESPONSE_BYTES (512 each — the survey's
largest observation set is one acceptance reading plus its radius echo, far
below the protocol-5 640 precedent). Tile bounds are 256x256-safe
(``TileID <= 65535``), imported from corridor_construction. The world is the
same pinned Seed-17 corridor world as protocol 5.
"""

import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, StrictInt, model_validator

from app.planning.canonical import canonical_bytes
from app.planning.domain import Contract, Digest
from app.simulation.openttd.corridor_construction import (
    CompanyID,
    Money,
    SignedMoney,
    TileID,
)

ACCEPT_SURVEY_PROTOCOL = 6
# Small bodies: the largest request carries one tile pin, the largest
# response one acceptance reading plus its radius echo. 512 is the generic
# version-one transport default; nothing here needs the protocol-5 640 bound.
MAX_SURVEY_REQUEST_BYTES = 512
MAX_SURVEY_RESPONSE_BYTES = 512
# Native eighths (0..8) and the bounded truck-stop coverage radius readback.
# 255 seats any future configurable radius setting; a larger value is an
# out-of-range observation, refused before it can be recorded as measured.
MAX_SURVEY_RADIUS = 255
SURVEY_MAP_WIDTH = 256
SURVEY_MAP_HEIGHT = 256
SURVEY_MAX_TILE_ID = SURVEY_MAP_WIDTH * SURVEY_MAP_HEIGHT - 1
PLANNED_SURVEY_EXCHANGES = 8
SURVEY_REQUEST_BUDGET = 32
SURVEY_COMPANY = 0
SURVEY_CARGO_ID = 1
SURVEY_PICKUP_INDUSTRY = 0
SURVEY_DELIVERY_INDUSTRY = 1
FUNDS_AT_D4_CLOSE = 492149

# The pinned corridor world every survey request echoes (the authoritative
# D4 candidate-5 after-save geometry; stop/depot identity defence reuses the
# protocol-5 pins — the survey never queries un-pinned tiles).
SURVEY_PICKUP_TILE = 45748
SURVEY_PICKUP_FRONT_TILE = 45747
SURVEY_DELIVERY_TILE = 50351
SURVEY_DELIVERY_FRONT_TILE = 50095
SURVEY_DEPOT_TILE = 45487
SURVEY_DEPOT_FRONT_TILE = 45743

# The pinned observation schedule of D5-ACCEPT-SURVEY-1. accept-00 is the
# control: the consumed attempt's delivery stop, whose native acceptance is
# expected zero (the finding of record re-measured, never assumed). The five
# candidates are retained pre-construction census hypotheses
# (acceptance_eighths 8 for cargo 1 in the sealed network facts) — NOT
# proven buildable stops, NOT existing stations, and NOT a freight-route
# claim. Their native acceptance values are exactly what the survey
# measures, so a candidate disagreeing with its census hypothesis is a real
# finding, not a survey failure.
SURVEY_CONTROL_TILE = SURVEY_DELIVERY_TILE
SURVEY_CANDIDATE_TILES: tuple[int, ...] = (50607, 50863, 51119, 51375, 50605)
SURVEY_OBSERVATION_TILES: tuple[int, ...] = (SURVEY_CONTROL_TILE,) + SURVEY_CANDIDATE_TILES

SURVEY_OPS = ("radius", "accept", "prod")

SurveyOp = Literal["radius", "accept", "prod"]

SurveyStatus = Literal[
    "READY",
    "UNSUPPORTED_NATIVE_FACT",
    "INVALID_LOCATION",
    "INVALID_COMPANY",
    "PAUSED",
    "STALE_PIN",
    "OUT_OF_ORDER",
]

_SURVEY_SEQUENCE: tuple[tuple[str, SurveyOp], ...] = (
    ("radius-00", "radius"),
    ("accept-00", "accept"),
    ("accept-01", "accept"),
    ("accept-02", "accept"),
    ("accept-03", "accept"),
    ("accept-04", "accept"),
    ("accept-05", "accept"),
    ("prod-00", "prod"),
)
SURVEY_EXCHANGE_IDS: tuple[str, ...] = tuple(i for i, _ in _SURVEY_SEQUENCE)
_SURVEY_OP_BY_ID: dict[str, SurveyOp] = dict(_SURVEY_SEQUENCE)
_OBSERVATION_TILE_BY_EXCHANGE: dict[str, int] = {
    f"accept-{index:02d}": tile for index, tile in enumerate(SURVEY_OBSERVATION_TILES)
}
_SURVEY_SUCCESS_STATUS: dict[SurveyOp, str] = {
    "radius": "READY",
    "accept": "READY",
    "prod": "READY",
}
_SURVEY_REFUSAL_STATUS = frozenset(
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
    len(SURVEY_EXCHANGE_IDS) != PLANNED_SURVEY_EXCHANGES
    or len(set(SURVEY_EXCHANGE_IDS)) != PLANNED_SURVEY_EXCHANGES
    or set(_SURVEY_OP_BY_ID.values()) != set(SURVEY_OPS)
    or _OBSERVATION_TILE_BY_EXCHANGE != {
        "accept-00": 50351,
        "accept-01": 50607,
        "accept-02": 50863,
        "accept-03": 51119,
        "accept-04": 51375,
        "accept-05": 50605,
    }
):
    raise RuntimeError("acceptance-survey exchange schedule drifted from the pinned observations")


class AcceptSurveyPlan(Contract):
    """The pinned identities and ordered observations of one survey attempt.

    The plan binds the authoritative D4 candidate-5 after-save identity: the
    corridor pins funds and world exactly as protocol 5 does, and pins the
    ordered acceptance-observation tiles (control first, candidates after)
    that every accept exchange must query in order. Staging and sealing
    remain the adopted ceremony's gates; this plan types what those stages
    must bind.
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
    pickup_industry: Annotated[StrictInt, Field(ge=0, le=65535)]
    expected_funds: Money
    observations: tuple[TileID, ...]
    schedule: tuple[str, ...]
    request_budget: Annotated[StrictInt, Field(gt=0, le=SURVEY_REQUEST_BUDGET)] = (
        SURVEY_REQUEST_BUDGET
    )

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()

    @model_validator(mode="after")
    def coherent(self) -> AcceptSurveyPlan:
        if self.company != SURVEY_COMPANY or self.cargo != SURVEY_CARGO_ID:
            raise ValueError("the acceptance survey drives company 0 with cargo 1")
        if (self.pickup, self.pickup_front) != (SURVEY_PICKUP_TILE, SURVEY_PICKUP_FRONT_TILE):
            raise ValueError("pickup pins drifted from the D4 corridor stops")
        if (self.delivery, self.delivery_front) != (
            SURVEY_DELIVERY_TILE,
            SURVEY_DELIVERY_FRONT_TILE,
        ):
            raise ValueError("delivery pins drifted from the D4 corridor stops")
        if (self.depot, self.depot_front) != (SURVEY_DEPOT_TILE, SURVEY_DEPOT_FRONT_TILE):
            raise ValueError("depot pins drifted from the D4 corridor depot")
        if (
            self.pickup_industry != SURVEY_PICKUP_INDUSTRY
            or self.pickup_industry != SURVEY_PICKUP_INDUSTRY
        ):
            raise ValueError("the pickup control observes industry 0 only")
        if self.expected_funds != FUNDS_AT_D4_CLOSE:
            raise ValueError("the plan binds the candidate-5 close-out funds exactly")
        if len(self.observations) != len(SURVEY_OBSERVATION_TILES) or tuple(
            self.observations
        ) != SURVEY_OBSERVATION_TILES:
            raise ValueError("observations drifted from the pinned control-first tile list")
        if self.schedule != SURVEY_EXCHANGE_IDS:
            raise ValueError("schedule drifted from the planned eight survey exchanges")
        return self


def survey_plan() -> AcceptSurveyPlan:
    """The pinned D5-ACCEPT-SURVEY-1 plan derived from the module's own pins."""
    return AcceptSurveyPlan(
        company=SURVEY_COMPANY,
        cargo=SURVEY_CARGO_ID,
        pickup=SURVEY_PICKUP_TILE,
        pickup_front=SURVEY_PICKUP_FRONT_TILE,
        delivery=SURVEY_DELIVERY_TILE,
        delivery_front=SURVEY_DELIVERY_FRONT_TILE,
        depot=SURVEY_DEPOT_TILE,
        depot_front=SURVEY_DEPOT_FRONT_TILE,
        pickup_industry=SURVEY_PICKUP_INDUSTRY,
        expected_funds=FUNDS_AT_D4_CLOSE,
        observations=SURVEY_OBSERVATION_TILES,
        schedule=SURVEY_EXCHANGE_IDS,
    )


class SurveyRequest(Contract):
    """One protocol-6 survey exchange request (fixed correlation stride).

    Every request carries the corridor identity pins (defence in depth: the
    native handler refuses a drifted pin before any observation), the
    uniform ``plan`` seal digest, and — on ``accept`` exactly — the one tile
    it queries. ``max_cost`` is 0 on every survey exchange: the survey has
    no cost-bearing operation of any kind.
    """

    protocol: Literal[6] = 6
    op: SurveyOp
    request_id: Annotated[str, Field(pattern=r"^[a-z0-9-]{1,32}$")]
    plan: Digest
    company: CompanyID
    max_cost: Annotated[StrictInt, Field(ge=0, le=0)]
    pickup: TileID
    delivery: TileID
    depot: TileID
    tile: TileID | None = None

    @model_validator(mode="after")
    def coherent(self) -> SurveyRequest:
        if self.op == "accept":
            if self.tile is None:
                raise ValueError("accept requests carry exactly one pinned observation tile")
            if self.tile not in SURVEY_OBSERVATION_TILES:
                raise ValueError("accept requests may only query the pinned survey tiles")
        elif self.tile is not None:
            raise ValueError("only the accept op carries a tile")
        return self

    def to_bytes(self) -> bytes:
        raw = canonical_bytes(self)
        if len(raw) > MAX_SURVEY_REQUEST_BYTES:
            raise ValueError(f"survey request exceeds {MAX_SURVEY_REQUEST_BYTES} bytes")
        return raw


_SURVEY_FIELDS = (
    "radius",
    "accept",
    "prod",
)

_SURVEY_SUBSETS: dict[SurveyOp, frozenset[str]] = {
    "radius": frozenset(("radius",)),
    "accept": frozenset(("accept", "radius")),
    "prod": frozenset(("prod",)),
}
# Tile echo positions: the accept response must echo the tile it observed so
# a stale or cross-tile readback can never be mistaken for a fresh one.
_TILE_ECHO_OPS = frozenset({"accept"})


class SurveyReadback(Contract):
    """One protocol-6 survey exchange response (strict per-op field subsets).

    The handler echoes the request correlation keys, ``funds`` and a status
    literal. Success frames carry the complete op subset — a measured value
    plus, for accept, the radius it was measured under. Refusal frames carry
    none (a spoofed hybrid is refused on the wire). Every success value is
    domain-checked here: a value outside 0..8 eighths or 0..255 radius is an
    out-of-range observation that can never parse, so the fail-closed
    surface cannot accidentally record it as measured.
    """

    protocol: Literal[6] = 6
    op: SurveyOp
    request_id: str
    plan: Digest
    company: CompanyID
    max_cost: Money
    pickup: TileID
    delivery: TileID
    depot: TileID
    tile: TileID | None = None
    status: SurveyStatus
    funds: SignedMoney
    cost: Money
    radius: Annotated[StrictInt, Field(ge=0, le=MAX_SURVEY_RADIUS)] | None = None
    accept: Annotated[StrictInt, Field(ge=0, le=8)] | None = None
    prod: Annotated[StrictInt, Field(ge=0, le=2147483647)] | None = None

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()

    @model_validator(mode="after")
    def coherent(self) -> SurveyReadback:
        if self.op not in _SURVEY_SUCCESS_STATUS:
            raise ValueError("unknown survey op")
        subset = _SURVEY_SUBSETS[self.op]
        present = {field for field in _SURVEY_FIELDS if getattr(self, field) is not None}
        outside = present - subset
        if outside:
            raise ValueError(
                f"{self.op} readback carries fields outside its subset: {sorted(outside)}"
            )
        success = self.status == _SURVEY_SUCCESS_STATUS[self.op]
        if success:
            missing = subset - present
            if missing:
                raise ValueError(f"{self.op} success readback lacks {sorted(missing)}")
            if self.op == "accept":
                if self.tile is None:
                    raise ValueError("accept success must echo its observed tile")
                if self.radius is None:
                    raise ValueError("accept success must echo its native radius")
        elif self.status not in _SURVEY_REFUSAL_STATUS:  # pragma: no cover - literal exhausts
            raise ValueError("unknown survey status")
        elif present:
            raise ValueError("refusal readback carries an unclaimed observation set")
        if self.op == "radius" and self.tile is not None:
            raise ValueError("radius readback must not name a tile")
        if self.op == "prod" and self.tile is not None:
            raise ValueError("production readback must not name a tile")
        return self

    @classmethod
    def parse_for(cls, request: SurveyRequest, raw: bytes):
        if len(raw) > MAX_SURVEY_RESPONSE_BYTES:
            raise ValueError(f"survey response exceeds {MAX_SURVEY_RESPONSE_BYTES} bytes")

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
            raise ValueError("survey response correlation mismatch")
        for key in ("pickup", "delivery", "depot"):
            if getattr(criteria, key) != getattr(request, key):
                raise ValueError("survey response pin mismatch")
        if request.tile is not None and criteria.tile != request.tile:
            raise ValueError("survey response tile echo mismatch")
        return criteria


def verify_request_against_survey_plan(
    request: SurveyRequest, *, plan: AcceptSurveyPlan, seal: str
) -> None:
    """Refuse a request that is not bound to the local survey plan.

    Python is the trust anchor: every request must present the staged seal,
    the pinned corridor identity and — for accept — exactly the pinned
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
    if request.op == "accept":
        exchange_index = (
            SURVEY_EXCHANGE_IDS.index(request.request_id)
            if request.request_id in SURVEY_EXCHANGE_IDS
            else -1
        )
        expected = _OBSERVATION_TILE_BY_EXCHANGE.get(request.request_id)
        if (
            exchange_index < 1
            or expected is None
            or request.tile != expected
            or request.tile != plan.observations[exchange_index - 1]
        ):
            raise ValueError("accept request tile drifted from the planned observation")


_OBSERVATION_KINDS = ("MEASURED", "REFUSED", "MISSING", "MALFORMED")


def _survey_state() -> dict:
    return dict(
        index=0,
        observations={},
        ledger=[],
        funds=None,
    )


def _survey_read_step(
    state: dict,
    request: SurveyRequest,
    readback: SurveyReadback,
    *,
    plan: AcceptSurveyPlan,
    seal: str,
) -> dict:
    """Verify one ordered survey exchange against the accumulated state."""
    expected = SURVEY_EXCHANGE_IDS[state["index"]]
    if request.request_id != expected or readback.request_id != expected:
        raise ValueError(f"survey exchange out of order: expected {expected}")
    verify_request_against_survey_plan(request, plan=plan, seal=seal)
    if readback.status != "READY":
        raise ValueError(f"survey exchange {expected} ended {readback.status}")
    if readback.funds != plan.expected_funds:
        raise ValueError("survey funds must equal the D4 close-out level exactly")
    if readback.cost != 0:
        raise ValueError("survey exchanges must observe at zero cost")
    # Paused and unpinned worlds are refused inside the handler; a correlated
    # READY reply is the only surface that may record a measurement.
    if request.op == "radius":
        state["radius"] = readback.radius
    if request.op == "prod":
        state["prod"] = readback.prod
    if request.op == "accept":
        radius = state.get("radius")
        if radius is None:
            raise ValueError("acceptance requires the measured native radius first")
        tile = plan.observations[state["index"] - 1]
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
        schema="company-accept-survey-receipt-v1",
        request_id=readback.request_id,
        op=request.op,
        plan_digest=plan.digest,
        seal=seal,
        status=readback.status,
        funds=readback.funds,
        verification="SURVEY_OBSERVED",
    )
    if request.op == "accept":
        receipt.update(
            tile=request.tile,
            accept=readback.accept,
            radius=readback.radius,
        )
    elif request.op == "radius":
        receipt.update(radius=readback.radius)
    else:
        receipt.update(prod=readback.prod)
    return receipt


def survey_phase_outcome(
    exchanges: list[tuple[SurveyRequest, SurveyReadback | Exception]],
    *,
    prelaunch_digest: str,
    plan: AcceptSurveyPlan,
) -> dict:
    """Fail-closed survey verification over preserved evidence only.

    Each exchange is ``(request, readback_or_error)``; an error element is an
    observation whose bytes never parsed or correlated (malformed, stale,
    torn or duplicate). The first halted exchange ends verification: earlier
    receipts are preserved, later exchanges are pending, and an unfinished
    schedule can never manufacture success. Exchange-level verdicts are
    recorded per observation kind:

    - ``MEASURED`` — a correlated READY readback whose domain-checked value
      (including its radius echo) was accepted; a ``value: 0`` recorded under
      such a readback is a measured zero, and nothing else is;
    - ``REFUSED`` — a typed refusal (out-of-map tile, unpaused/pin/company
      drift, unsupported native fact) carrying no observation set;
    - ``MISSING`` — a scheduled exchange without a readback;
    - ``MALFORMED`` — the attached error element for that exchange.
    """
    receipts: list[dict] = []
    failed = None
    pending: list[str] = []
    state = _survey_state()
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
                _survey_read_step(
                    state, request, readback, plan=plan, seal=prelaunch_digest
                )
            )
        except Exception as error:  # noqa: BLE001 - fail closed on any defect
            failed = dict(
                label=request.request_id,
                status=str(getattr(readback, "status", "UNKNOWN")),
                error=str(error),
                world_state="HALTED_BEFORE_MUTATION",
            )
            continue
    complete = failed is None and len(exchanges) == PLANNED_SURVEY_EXCHANGES
    pending = (
        list(SURVEY_EXCHANGE_IDS[len(exchanges):])
        if failed is None
        else list(SURVEY_EXCHANGE_IDS[SURVEY_EXCHANGE_IDS.index(failed["label"]) + 1:])
    )
    observations = state["observations"]
    return dict(
        schema="accept-survey-phase-outcome-v1",
        seal=prelaunch_digest,
        plan_digest=plan.digest,
        receipts=receipts,
        failed=failed,
        pending=pending,
        observations=observations,
        radius=state.get("radius"),
        production=state.get("prod"),
        funds=state["funds"],
        observation_kinds=_OBSERVATION_KINDS,
        verification="SURVEY_COMPLETE" if complete else "SURVEY_INCOMPLETE",
    )
