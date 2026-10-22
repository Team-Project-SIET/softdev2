"""Native road/station/depot corridor construction wire contract (additive).

Milestone D4: the compiled Seed 17 corridor is one ordered schedule of bounded
native road commands executed by one authorized company through the shared
D2/D3 one-launch machinery. This module is the protocol-4 wire contract for
that schedule: typed requests, fail-closed response parsing, admission
latching, per-operation verification receipts, a prefix-preserving phase
outcome and the final route connectivity verification.

Design constraints mirrored from the proven ceremonies:

- The wire stays small and bounded: requests serialize below 512 bytes and
  every response binds below 640 bytes — the final route read echoes the
  ordered 24-tile corridor witness (24 five-digit tile ids) plus its
  observation set, which cannot honestly fit the historical 512 response
  bound; every other response stays far below it and the Guard() numeric
  bounds still make any oversized or spoofed readback a refused frame.
- Tile bounds are 256×256-safe (``TileID <= 65535``); the historical 64×64
  road contracts cannot address this corridor (tiles ≈ 45k) and are neither
  reused nor modified.
- A build assertion covers exactly its own referenced pins: nothing here
  claims depot/station/road state for tiles outside the staged schedule.
- No command is authorized from a zero-cost native refusal; every structural
  fact is a native readback, never a planning derivation.
- Catchment/acceptance are native construction facts only: a truck-stop
  quotation of zero cost or a refused build is terminal for its operation.
- Wire identity style (terrain_terraform): the command request presents the
  prelaunch seal the inspect latched; the independent verification re-read
  presents the admitted intent digest.
"""

import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictInt, model_validator

from app.planning.canonical import canonical_bytes
from app.planning.domain import Contract, Digest

TileID = Annotated[StrictInt, Field(ge=0, le=65535)]
TileSentinel = Annotated[StrictInt, Field(ge=-1, le=1 << 31 - 1)]
CompanyID = Annotated[StrictInt, Field(ge=0, le=14)]
OwnerID = Annotated[StrictInt, Field(ge=-1, le=14)]
Money = Annotated[StrictInt, Field(ge=0, le=2147483647)]
SignedMoney = Annotated[StrictInt, Field(ge=-2147483648, le=2147483647)]
RunKey = Annotated[StrictInt, Field(ge=0, le=48)]
FailIndex = Annotated[StrictInt, Field(ge=-1, le=48)]
StationID = Annotated[StrictInt, Field(ge=-1, le=1 << 31 - 1)]
# ScriptCompany::COMPANY_INVALID in the 15.3 API, not COMPANY_SPECTATOR (255).
UNOWNED_COMPANY = -1

CORRIDOR_PROTOCOL = 4
ROAD_OPS = ("full", "road")
SITE_OPS = ("station", "depot")
# Inspect/read requests name the command kind they admit or re-verify.
TARGETS = ROAD_OPS + SITE_OPS
CORRIDOR_OPS = ("inspect", "full", "road", "station", "depot", "read", "route")
# Fail-closed statuses mirror the proven roads/clearing pattern; the corridor
# admission gates add the attempt/order/cost-statuses the one-shot exchange
# groups require.
STATUS = Literal[
    "READY",
    "BUILT",
    "READ",
    "INVALID_COMPANY",
    "INVALID_LOCATION",
    "NOT_BUILDABLE",
    "OWNERSHIP_MISMATCH",
    "UNSUPPORTED_NATIVE_FACT",
    "REJECTED",
    "COST_LIMIT",
    "INSUFFICIENT_FUNDS",
    "ALREADY_ATTEMPTED",
    "COST_CHANGED",
    "STALE_ADMISSION",
    "READBACK_MISMATCH",
    "OUT_OF_ORDER",
]
MAX_FULL_SPAN = 36
_NATIVE_COMMANDS = {
    "full": "CMD_BUILD_ROAD",
    "road": "CMD_BUILD_ROAD",
    "station": "CMD_BUILD_ROAD_STATION",
    "depot": "CMD_BUILD_ROAD_DEPOT",
}
_OPERATIONS = {
    "full": "ROAD_FULL",
    "road": "ROAD_CONNECT",
    "station": "ROAD_STATION",
    "depot": "ROAD_DEPOT",
}


def native_command(kind: str) -> str:
    """The engine command class behind one scheduled op kind."""
    if kind not in _NATIVE_COMMANDS:
        raise ValueError(f"unknown corridor op kind: {kind}")
    return _NATIVE_COMMANDS[kind]


def operation_name(kind: str) -> str:
    """The receipt operation label for one scheduled op kind."""
    if kind not in _OPERATIONS:
        raise ValueError(f"unknown corridor op kind: {kind}")
    return _OPERATIONS[kind]


def _correlation_validators():
    def _shape(self: "CorridorRequest") -> "CorridorRequest":
        def adjacent(a: int, b: int) -> bool:
            return abs(a % 256 - b % 256) + abs(a // 256 - b // 256) == 1

        if self.op not in CORRIDOR_OPS:
            raise ValueError("unknown corridor op")
        if self.op in ("inspect", "read"):
            if self.target not in TARGETS:
                raise ValueError("inspect/read requires a command-kind target")
        elif self.target is not None:
            raise ValueError("command/route op must not carry a target")
        if self.target in ROAD_OPS or self.op in ("full", "road"):
            if self.start is None or self.end is None or self.tile is not None:
                raise ValueError("road op pins are start/end only")
            dx = abs(self.start % 256 - self.end % 256)
            dy = abs(self.start // 256 - self.end // 256)
            kind = self.target if self.target is not None else self.op
            if kind == "full":
                if (dx != 0 and dy != 0) or dx + dy < 1 or dx + dy > MAX_FULL_SPAN:
                    raise ValueError("full requires one straight axis within the bound")
            elif dx + dy != 1:
                raise ValueError("road requires directly adjacent endpoints")
        elif self.target in SITE_OPS or self.op in ("station", "depot"):
            if self.tile is None or self.front is None or self.start is not None:
                raise ValueError("site op pins are tile/front only")
            if not adjacent(self.tile, self.front):
                raise ValueError("site front must be directly adjacent")
        elif self.target == "route" or self.op == "route":
            if self.tiles is None or self.start is not None:
                raise ValueError("route carries the ordered corridor path only")
            if not 2 <= len(self.tiles) <= 48:
                raise ValueError("route path must span 2..48 tiles")
            if tuple(self.tiles)[0] == tuple(self.tiles)[-1]:
                raise ValueError("route path must have distinct endpoints")
        elif self.op != "route":
            raise ValueError("non-route requests must name their op target")
        return self

    return _shape


class CorridorRequest(Contract):
    """One protocol-4 corridor exchange request.

    A request carries exactly the pins of its own op kind: road builds
    (``full``/``road``) carry ``start``/``end``, site builds
    (``station``/``depot``) carry ``tile``/``front``, the route read carries
    ``tiles``. ``inspect``/``read`` repeat the pinned shape of the operation
    they admit or re-verify (with ``target`` naming that op kind) and the
    ``route`` read carries the full ordered corridor witness path.
    """

    protocol: Literal[4] = 4
    op: Literal["inspect", "full", "road", "station", "depot", "read", "route"]
    request_id: Annotated[str, Field(pattern=r"^[a-z0-9-]{1,32}$")]
    plan: Digest
    company: CompanyID
    max_cost: Money
    target: Literal["full", "road", "station", "depot"] | None = None
    start: TileID | None = None
    end: TileID | None = None
    tile: TileID | None = None
    front: TileID | None = None
    tiles: tuple[TileID, ...] | None = None

    def pins(self) -> dict[str, int | tuple[int, ...] | None]:
        return dict(
            target=self.target,
            start=self.start,
            end=self.end,
            tile=self.tile,
            front=self.front,
            tiles=self.tiles,
        )

    def shape(self) -> tuple[int, ...]:
        """The op's sorted pin tuple (schedule-identity key)."""
        kind = self.kind
        if kind in ROAD_OPS:
            return tuple(sorted((self.start, self.end)))
        if kind in SITE_OPS:
            return (self.tile, self.front)
        if kind == "route":
            return tuple(self.tiles)
        raise ValueError("an inspection request has no command shape")

    @property
    def kind(self) -> str:
        """The op kind the request names or targets."""
        if self.op in ("inspect", "read"):
            return self.target or ""
        if self.op in ROAD_OPS:
            return self.op
        if self.op in SITE_OPS:
            return self.op
        return "route"

    @model_validator(mode="after")
    def coherent(self) -> "CorridorRequest":
        def adjacent(a: int, b: int) -> bool:
            return abs(a % 256 - b % 256) + abs(a // 256 - b // 256) == 1

        if self.op not in CORRIDOR_OPS:
            raise ValueError("unknown corridor op")
        if self.op in ("inspect", "read"):
            if self.target not in TARGETS:
                raise ValueError("inspect/read requires a command-kind target")
        elif self.target is not None:
            raise ValueError("command/route op must not carry a target")
        if self.target in ROAD_OPS or self.op in ("full", "road"):
            if self.start is None or self.end is None or self.tile is not None:
                raise ValueError("road op pins are start/end only")
            dx = abs(self.start % 256 - self.end % 256)
            dy = abs(self.start // 256 - self.end // 256)
            kind = self.target if self.target is not None else self.op
            if kind == "full":
                if (dx != 0 and dy != 0) or dx + dy < 1 or dx + dy > MAX_FULL_SPAN:
                    raise ValueError("full requires one straight axis within the bound")
            elif dx + dy != 1:
                raise ValueError("road requires directly adjacent endpoints")
        elif self.target in SITE_OPS or self.op in ("station", "depot"):
            if self.tile is None or self.front is None or self.start is not None:
                raise ValueError("site op pins are tile/front only")
            if not adjacent(self.tile, self.front):
                raise ValueError("site front must be directly adjacent")
        elif self.target == "route" or self.op == "route":
            if self.tiles is None or self.start is not None:
                raise ValueError("route carries the ordered corridor path only")
            if not 2 <= len(self.tiles) <= 48:
                raise ValueError("route path must span 2..48 tiles")
            if tuple(self.tiles)[0] == tuple(self.tiles)[-1]:
                raise ValueError("route path must have distinct endpoints")
        elif self.op != "route":
            raise ValueError("non-route requests must name their op target")
        return self

    def to_bytes(self) -> bytes:
        raw = json.dumps(
            self.model_dump(mode="json", exclude_none=True),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(raw) > 512:
            raise ValueError("corridor request exceeds 512 bytes")
        return raw


class CorridorReadback(Contract):
    """One protocol-4 corridor exchange response (strict field subsets).

    The handler echoes the request correlation keys and reports only the
    observation set of the request's op kind. A response the package's own
    bounds gate would refuse (funds/cost overflow, oversized stream) is
    rejected here identically.
    """

    protocol: Literal[4] = 4
    op: Literal["inspect", "full", "road", "station", "depot", "read", "route"]
    request_id: str
    plan: Digest
    company: Annotated[StrictInt, Field(ge=0, le=14)]
    max_cost: Money
    target: Literal["full", "road", "station", "depot"] | None
    start: TileID | None
    end: TileID | None
    tile: TileID | None
    front: TileID | None
    tiles: tuple[TileID, ...] | None
    status: STATUS
    eligible: StrictBool
    funds: SignedMoney
    cost: Money
    # Road-op observation: endpoint owners/road flags and the run summary.
    owner0: OwnerID | None = None
    owner1: OwnerID | None = None
    road0: StrictBool | None = None
    road1: StrictBool | None = None
    run_len: RunKey | None = None
    covered: RunKey | None = None
    pairs_ok: RunKey | None = None
    pair_total: RunKey | None = None
    # Site-op observation: the stop/depot tile, its front and attachments.
    stop: StrictBool | None = None
    drive_through: StrictBool | None = None
    truck: StrictBool | None = None
    sid: StationID | None = None
    stop_owner: OwnerID | None = None
    front_owner: OwnerID | None = None
    linked: StrictBool | None = None
    depot: StrictBool | None = None
    depot_front_id: TileSentinel | None = None
    depot_linked: StrictBool | None = None
    stop_min_height: Annotated[StrictInt, Field(ge=0, le=255)] | None = None
    stop_slope: Annotated[StrictInt, Field(ge=0, le=31)] | None = None
    front_min_height: Annotated[StrictInt, Field(ge=0, le=255)] | None = None
    front_slope: Annotated[StrictInt, Field(ge=0, le=31)] | None = None
    # Route-read observation over the ordered corridor witness path.
    connected_pairs: RunKey | None = None
    first_fail: FailIndex | None = None
    pickup_stop: StrictBool | None = None
    pickup_truck: StrictBool | None = None
    pickup_sid: StationID | None = None
    delivery_stop: StrictBool | None = None
    delivery_truck: StrictBool | None = None
    delivery_sid: StationID | None = None
    depot_pin_ok: StrictBool | None = None

    @property
    def kind(self) -> str:
        if self.op in ("inspect", "read"):
            return self.target or ""
        if self.op in ROAD_OPS:
            return self.op
        if self.op in SITE_OPS:
            return self.op
        return "route"

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()

    @classmethod
    def parse_for(cls, request: CorridorRequest, raw: bytes):
        if len(raw) > 640:
            raise ValueError("application response exceeds 640 bytes")

        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate response key")
                result[key] = value
            return result

        value = json.loads(raw, object_pairs_hook=unique)
        if isinstance(value.get("tiles"), list):
            value = dict(value, tiles=tuple(value["tiles"]))
        criteria = cls.model_validate(value)
        correlated = ("protocol", "op", "request_id", "plan", "company", "max_cost")
        if any(getattr(criteria, k) != getattr(request, k) for k in correlated):
            raise ValueError("corridor response correlation mismatch")
        for k in ("target", "start", "end", "tile", "front"):
            expected = getattr(request, k, None)
            if expected is not None and getattr(criteria, k) != expected:
                raise ValueError("corridor response pin mismatch")
        if request.tiles is not None and tuple(criteria.tiles or ()) != request.tiles:
            raise ValueError("corridor response path mismatch")
        return criteria


def _road_summary(readback: CorridorReadback) -> tuple[int, int, int, int]:
    present = (
        readback.run_len is not None
        and readback.covered is not None
        and readback.pairs_ok is not None
        and readback.pair_total is not None
    )
    if not present:
        raise ValueError("road readback lacks its run summary")
    return readback.run_len, readback.covered, readback.pairs_ok, readback.pair_total


def _road_post_state(readback: CorridorReadback, *, company: int) -> None:
    if (
        readback.owner0 != company
        or readback.owner1 != company
        or readback.road0 is not True
        or readback.road1 is not True
    ):
        raise ValueError("native road ownership/connectivity mismatch")


def _site_post_state(readback: CorridorReadback, *, company: int, depot: bool) -> None:
    if depot:
        if (
            readback.depot is not True
            or readback.depot_front_id != readback.front
            or readback.depot_linked is not True
            or readback.front_owner != company
            or readback.stop is not False
            or readback.truck is not False
        ):
            raise ValueError("native depot structure mismatch")
        return
    if (
        readback.stop is not True
        or readback.drive_through is not False
        or readback.truck is not True
        or readback.sid is None
        or readback.sid < 0
        or readback.stop_owner != company
        or readback.front_owner != company
        or readback.linked is not True
        or readback.depot is not False
        or readback.truck is not True
    ):
        raise ValueError("native truck-stop structure mismatch")


def _site_pre_state(readback: CorridorReadback, *, depot: bool) -> None:
    if readback.stop_owner not in (UNOWNED_COMPANY, readback.company):
        raise ValueError(f"{'depot' if depot else 'stop'} admission owner mismatch")
    if readback.front_owner != readback.company:
        raise ValueError("site front admission requires the company's road")
    if depot:
        if readback.depot is not False or readback.depot_linked is not False:
            raise ValueError("depot admission requires unplanned ground")
        return
    if (
        readback.stop is not False
        or readback.drive_through is not False
        or readback.truck is not False
        or readback.sid not in (None, -1)
    ):
        raise ValueError("stop admission requires unplanned ground")


def admit_corridor(
    readback: CorridorReadback,
    *,
    prelaunch_digest: str,
    source_save_digest: str,
    staged_run_len: int | None,
    max_cost: int,
) -> CorridorIntent:
    """Latch one corridor intent from a fresh native inspect readback.

    Requires READY with a positive tested cost within the ceiling, funds for
    it, and the handler's own eligible verdict. Road runs must report their
    staged run length with a fully roadless unowned pre-state; the corner
    ``road`` op must report both endpoints as company road with the pair not
    yet connected; a site op must report its footprint unplanned with the
    front an owned company road attachment. A zero-cost native refusal is
    terminal: it must never trigger a build command, so it is refused here.
    """
    kind = readback.kind
    if kind not in ROAD_OPS + SITE_OPS:
        raise ValueError(f"no admissible corridor command for op kind {kind}")
    if (
        readback.op != "inspect"
        or readback.plan != prelaunch_digest
        or readback.status != "READY"
        or not readback.eligible
        or not 0 < readback.cost <= max_cost
        or readback.funds < readback.cost
    ):
        raise ValueError("native READY admission with positive tested cost required")
    run_len = None
    if kind in ROAD_OPS:
        covered_len, covered, pairs_ok, pair_total = _road_summary(readback)
        if staged_run_len is None or covered_len != staged_run_len:
            raise ValueError("road run length drifted from the staged schedule")
        if readback.owner0 is None or readback.owner1 is None:
            raise ValueError("road admission lacks its endpoint owners")
        if kind == "full":
            if (
                readback.owner0 != UNOWNED_COMPANY
                or readback.owner1 != UNOWNED_COMPANY
                or readback.road0 is not False
                or readback.road1 is not False
                or covered != 0
                or pairs_ok != 0
            ):
                raise ValueError("full admission requires a roadless unowned run")
        else:
            if (
                readback.owner0 != readback.company
                or readback.owner1 != readback.company
                or readback.road0 is not True
                or readback.road1 is not True
                or covered != staged_run_len
                or pairs_ok != 0
            ):
                raise ValueError(
                    "corner admission requires both endpoints company-owned road "
                    "and no existing connection"
                )
        if pair_total != staged_run_len - 1:
            raise ValueError("road pair accounting drifted from the staged schedule")
        run_len = staged_run_len
    else:
        _site_pre_state(readback, depot=kind == "depot")
    return CorridorIntent(
        prelaunch_digest=prelaunch_digest,
        source_save_digest=source_save_digest,
        company=readback.company,
        kind=kind,
        start=readback.start,
        end=readback.end,
        tile=readback.tile,
        front=readback.front,
        max_cost=max_cost,
        native_test_cost=readback.cost,
        before_digest=readback.digest,
        run_len=run_len,
    )


class CorridorIntent(Contract):
    """One admitted bounded corridor op with a fresh native bound."""

    schema_version: Literal[1] = 1
    prelaunch_digest: Digest
    source_save_digest: Digest
    company: CompanyID
    kind: Literal["full", "road", "station", "depot"]
    start: TileID | None
    end: TileID | None
    tile: TileID | None
    front: TileID | None
    max_cost: Money
    native_test_cost: Money
    before_digest: Digest
    run_len: RunKey | None

    @model_validator(mode="after")
    def coherent(self) -> "CorridorIntent":
        if self.kind in ROAD_OPS:
            if self.start is None or self.end is None or self.run_len is None:
                raise ValueError("road intent requires start/end and run length")
            if self.tile is not None:
                raise ValueError("road intent carries no site pins")
        else:
            if self.tile is None or self.front is None:
                raise ValueError("site intent requires tile/front pins")
            if self.start is not None or self.run_len is not None:
                raise ValueError("site intent carries no run pins")
        if not 0 < self.native_test_cost <= self.max_cost:
            raise ValueError("admitted cost must be positive within its ceiling")
        return self

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()


def verify_corridor(
    intent: CorridorIntent,
    before: CorridorReadback,
    built: CorridorReadback,
    independent: CorridorReadback,
) -> dict:
    """Verify one corridor exchange group and emit the verified receipt."""
    if (
        admit_corridor(
            before,
            prelaunch_digest=intent.prelaunch_digest,
            source_save_digest=intent.source_save_digest,
            staged_run_len=intent.run_len,
            max_cost=intent.max_cost,
        )
        != intent
    ):
        raise ValueError("intent differs from native admitted facts")
    kind = intent.kind
    if kind in ROAD_OPS:
        pin_shape = (built.start, built.end)
        expected_pin = (intent.start, intent.end)
    elif kind in SITE_OPS:
        pin_shape = (built.tile, built.front)
        expected_pin = (intent.tile, intent.front)
    else:
        raise ValueError("intent runs no admissible corridor command")
    if pin_shape != expected_pin:
        raise ValueError("execution result correlation mismatch")
    # Wire identity: the build presents the latched admission (prelaunch
    # seal); the independent verification re-read presents the intent digest.
    if built.op != kind or (built.plan, built.company) != (
        intent.prelaunch_digest,
        intent.company,
    ):
        raise ValueError("execution result correlation mismatch")
    if (
        built.status != "BUILT"
        or built.cost != intent.native_test_cost
        or before.funds - built.funds != built.cost
    ):
        raise ValueError("construction result/native funds mismatch")
    if (
        independent.op != "read"
        or independent.status != "READ"
        or independent.plan != intent.digest
        or independent.company != intent.company
    ):
        raise ValueError("independent readback is not intent-scoped observation")
    if (
        (independent.start, independent.end, independent.tile, independent.front)
        != (built.start, built.end, built.tile, built.front)
        or independent.target != intent.kind
        or independent.funds != built.funds
    ):
        raise ValueError("independent readback correlation or funds mismatch")
    if kind in ROAD_OPS:
        _road_post_state(built, company=intent.company)
        built_summary = _road_summary(built)
        after_summary = _road_summary(independent)
        if (
            built_summary[0] != intent.run_len
            or built_summary[1] != intent.run_len
            or built_summary[2] != built_summary[3]
            or built_summary[3] != intent.run_len - 1
            or after_summary != built_summary
        ):
            raise ValueError("execution result/run summary mismatch")
        for readback in (built, independent):
            if (readback.owner0, readback.owner1) != (
                intent.company,
                intent.company,
            ) or readback.road0 is not True or readback.road1 is not True:
                raise ValueError("independent road ownership/connectivity mismatch")
    else:
        depot = kind == "depot"
        for readback in (built, independent):
            _site_post_state(readback, company=intent.company, depot=depot)
        if (built.stop_min_height, built.stop_slope) != (
            independent.stop_min_height,
            independent.stop_slope,
        ) or (built.front_min_height, built.front_slope) != (
            independent.front_min_height,
            independent.front_slope,
        ):
            raise ValueError("independent site geometry mismatch")
    return dict(
        schema="company-corridor-receipt-v1",
        execution_request_id=built.request_id,
        readback_request_id=independent.request_id,
        plan_digest=intent.digest,
        prelaunch_digest=intent.prelaunch_digest,
        source_save_digest=intent.source_save_digest,
        before_digest=intent.before_digest,
        construction_digest=built.digest,
        after_digest=independent.digest,
        company=intent.company,
        kind=kind,
        native_command=native_command(kind),
        native_command_count=1,
        operation=operation_name(kind),
        pins=dict(
            start=intent.start,
            end=intent.end,
            tile=intent.tile,
            front=intent.front,
            tiles=None if intent.run_len is None else intent.run_len,
        ),
        native_quote=intent.native_test_cost,
        execution_status=built.status,
        cost=built.cost,
        cost_category="construction",
        error_code=None,
        verification="NATIVE_STATE_CHANGED",
    )


def verify_corridor_route(
    route: CorridorReadback,
    *,
    prelaunch_digest: str,
    expected_pairs: int,
    expected_path: tuple[int, ...],
) -> dict:
    """Verify the final route connectivity read and emit the route receipt.

    The route read is pure observation of the whole scheduled corridor:
    every adjacent pair along the staged witness path joined by company road
    (road stops attach through their fronts), both planned stops classified
    as non-drive-through truck stops with valid station ids, and the depot
    joined to its pinned front. No build assertion follows from this read;
    the route receipt only records the connected, usable infrastructure the
    constructed world actually holds.
    """
    if (
        route.op != "route"
        or route.status != "READ"
        or route.plan != prelaunch_digest
        or route.cost != 0
        or tuple(route.tiles or ()) != tuple(expected_path)
    ):
        raise ValueError("route evidence is not a correlated route observation")
    if (
        route.connected_pairs is None
        or route.first_fail is None
        or route.connected_pairs != expected_pairs
        or route.first_fail != -1
    ):
        raise ValueError("route connectivity is incomplete; no connected route proved")
    if (
        route.pickup_stop is not True
        or route.pickup_truck is not True
        or route.delivery_stop is not True
        or route.delivery_truck is not True
        or route.pickup_sid is None
        or route.pickup_sid < 0
        or route.delivery_sid is None
        or route.delivery_sid < 0
        or route.depot_pin_ok is not True
    ):
        raise ValueError("route stop/depot structure mismatch")
    return dict(
        schema="company-route-receipt-v1",
        request_id=route.request_id,
        prelaunch_digest=route.plan,
        after_digest=route.digest,
        expected_pairs=expected_pairs,
        connected_pairs=route.connected_pairs,
        first_fail_index=route.first_fail,
        funds=route.funds,
        cost=0,
        verification="ROUTE_VERIFIED",
    )


def corridor_phase_outcome(attempts: list[tuple[str, dict]]) -> dict:
    """Fail-closed corridor-phase verification over preserved evidence only.

    Each attempt is ``(label, evidence)`` where evidence holds the retained
    ``intent``, ``before`` and optional ``built``/``independent`` readbacks.
    The first attempt whose evidence fails verification halts the phase:
    earlier verified receipts are preserved, later attempts are reported as
    pending, and no retry or compensating mutation is represented or implied.
    A failed attempt leaves the world state explicitly uncertain: a failed
    native road command may still have built some pieces and the phase
    evidence keeps the world state explicitly uncertain. This verifies
    evidence; it never issues requests.
    """
    receipts: list[dict] = []
    failed = None
    pending: list[str] = []
    for label, evidence in attempts:
        if failed is not None:
            pending.append(label)
            continue
        try:
            intent = evidence.get("intent")
            before = evidence.get("before")
            built = evidence.get("built")
            independent = evidence.get("independent")
            if intent is None or before is None or built is None:
                raise ValueError("corridor attempt lacks retained execution evidence")
            if independent is None:
                raise ValueError("corridor attempt lacks its independent readback")
            if (built.plan, built.company) != (intent.prelaunch_digest, intent.company):
                raise ValueError("construction result correlation mismatch")
            if built.status != "BUILT" or built.cost != intent.native_test_cost:
                raise ValueError("execution result/native tested cost disagreement")
            receipts.append(verify_corridor(intent, before, built, independent))
        except Exception as error:  # noqa: BLE001 - fail closed on any defect
            failed = dict(
                label=label,
                error=str(error),
                world_state="UNCERTAIN_AFTER_FAILED_COMMAND",
            )
    return dict(
        schema="corridor-phase-outcome-v1",
        completed=receipts,
        failed=failed,
        pending=pending,
        verification="PHASE_COMPLETE"
        if failed is None and len(attempts) > 0
        else "PARTIAL_EXECUTION_EVIDENCE",
    )
