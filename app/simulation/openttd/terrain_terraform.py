"""One owned bounded terraforming intent for a single terrain corner write.

Additive D3 planning contract mirroring the verified bounded-clearing pattern
in ``terrain_clearing.py``: one ``GSTile.RaiseTile``/``GSTile.LowerTile``
corner mutation, admitted from fresh native observations, executed exactly
once, and verified against exact derived geometry by independent readbacks.
It introduces no new authorization framework: operator authorization, runtime
freeze, dependency identity, immutable environment, one-shot claims and signed
replay remain the existing D2 verification boundary's responsibilities.

Wire contract v3 (``protocol: 3``): inspect and terraform requests present the
admission plan identity (the prelaunch seal), so the GameScript mutation
boundary can compare it against the latched admission before the native
command, and verification reads are intent-scoped and present the intent
digest - mirroring the adopted v2 clearing semantics.
``GSTile.LevelTiles`` is outside this contract by design: a corner write is
always a single-bit ``RaiseTile``/``LowerTile`` mask, never a level command.

Uncertainty rule: a raised/lowered status asserts only the observed
post-command host corner geometry. No failed command is ever declared to have
left the world unchanged: a failed terraform may still have auto-cleared
neighbouring trees and changed the map, and the phase evidence keeps that
state explicitly uncertain.
"""

import hashlib
import json
from collections.abc import Sequence
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictInt, model_validator

from app.planning.canonical import canonical_bytes
from app.planning.domain import Contract, Digest
from app.simulation.openttd.road_mutation import UNOWNED_COMPANY
from app.simulation.openttd.tile_classification import TileClass, classify_tile

CompanyID = Annotated[StrictInt, Field(ge=0, le=14)]
Money = Annotated[StrictInt, Field(ge=0, le=2147483647)]
TileID = Annotated[StrictInt, Field(ge=0, le=65535)]
# Elevation/slope bounds match the frozen classification wire contract; the
# slope ceiling excludes halftile encodings (>= 0x20) so corner heights stay
# acquirable without native assertions.
Elevation = Annotated[StrictInt, Field(ge=0, le=255)]
Slope = Annotated[StrictInt, Field(ge=0, le=31)]
Flags = Annotated[StrictInt, Field(ge=0, le=(1 << 15) - 1)]
PointAxis = Annotated[StrictInt, Field(ge=0, le=65535)]
CornerName = Literal["N", "E", "W", "S"]
DirectionName = Literal["up", "down"]

# Official slope_type.h corner-bit constants (verified for tag 15.3); a corner
# mask must be exactly one of these single bits.
SLOPE_W = 0x1
SLOPE_S = 0x2
SLOPE_E = 0x4
SLOPE_N = 0x8
SLOPE_STEEP = 0x10
CORNER_MASKS: dict[str, int] = {"N": SLOPE_N, "E": SLOPE_E, "W": SLOPE_W, "S": SLOPE_S}
OPPOSITE_CORNER = {"N": "S", "S": "N", "E": "W", "W": "E"}

Status = Literal[
    "READY",
    "NO_OP",
    "RAISED",
    "LOWERED",
    "READ",
    "INVALID_COMPANY",
    "INVALID_LOCATION",
    "FORBIDDEN_CLASS",
    "OWNERSHIP_MISMATCH",
    "UNSUPPORTED_NATIVE_FACT",
    "REJECTED",
    "READBACK_MISMATCH",
    "ALREADY_ATTEMPTED",
    "COST_LIMIT",
    "INSUFFICIENT_FUNDS",
    "STALE_ADMISSION",
]


def expected_corner_heights(min_height: int, slope: int) -> dict[str, int]:
    """Official corner heights for a min height and slope encoding.

    Mirrors ``p08_terrain.corner_heights``; a halftile encoding (>= 0x20) is
    outside the wire contract and raises instead of being approximated.
    """
    if slope == 0:
        return {"N": min_height, "E": min_height, "W": min_height, "S": min_height}
    if slope & 0x20:
        raise ValueError("halftile slope encodings are outside the wire contract")
    if slope & SLOPE_STEEP:
        mask = slope & (SLOPE_N | SLOPE_E | SLOPE_W | SLOPE_S)
        if mask.bit_count() != 3:
            raise ValueError("steep slope needs exactly three raised corners")
        unmasked = next(name for name in CORNER_MASKS if not CORNER_MASKS[name] & mask)
        return {
            name: min_height + 2
            if name == OPPOSITE_CORNER[unmasked]
            else (min_height + 1 if CORNER_MASKS[name] & mask else min_height)
            for name in CORNER_MASKS
        }
    return {name: min_height + (1 if CORNER_MASKS[name] & slope else 0) for name in CORNER_MASKS}


class TerraformShareState(Contract):
    """Derived expected state for one tile sharing the commanded map point.

    The commanded corner is the corner of *this* tile that moves with the
    shared point. Reported corner heights are checked as the official
    derivation of the exact slope; a native report that disagrees is a native
    integrity failure and fails closed.
    """

    tile: TileID
    corner: CornerName
    before_min_height: Elevation
    before_slope: Slope
    after_min_height: Elevation
    after_slope: Slope

    @model_validator(mode="after")
    def coherent(self) -> TerraformShareState:
        try:
            expected_corner_heights(self.before_min_height, self.before_slope)
            expected_corner_heights(self.after_min_height, self.after_slope)
        except ValueError as error:
            raise ValueError(f"tile {self.tile_id}: unsupported slope encoding") from error
        return self


class TerraformExpectation(Contract):
    """Exact derived geometry for one bounded corner write.

    Fails closed over the four directly sharing tiles: an omission, a
    duplicate, a non-single-bit corner mask, a tile whose commanded corner is
    not the shared-point corner, or missing per-tile states cannot be built.
    """

    host_tile: TileID
    corner: CornerName
    direction: DirectionName
    corner_mask: Annotated[StrictInt, Field(ge=1, le=15)]
    shared_point_x: PointAxis
    shared_point_y: PointAxis
    sharing_tiles: tuple[TileID, TileID, TileID, TileID]
    tiles: tuple[TerraformShareState, ...]

    @model_validator(mode="after")
    def coherent(self) -> TerraformExpectation:
        mask = self.corner_mask
        if mask & (mask - 1) or mask != CORNER_MASKS.get(self.corner):
            raise ValueError("corner mask must be the official single bit of the named corner")
        if tuple(sorted(self.sharing_tiles)) != self.sharing_tiles:
            raise ValueError("sharing tiles must be four distinct ascending tile ids")
        if len(set(self.sharing_tiles)) != 4:
            raise ValueError("sharing tiles must be four distinct tile ids")
        if self.host_tile not in self.sharing_tiles:
            raise ValueError("host tile is not one of the four sharing tiles")
        states = tuple(sorted(state.tile for state in self.tiles))
        if states != self.sharing_tiles:
            raise ValueError("exactly one state per sharing tile, in tile-id order")
        return self


class TerraformIntent(Contract):
    """One admitted bounded corner write with a fresh native bound."""

    schema_version: Literal[1] = 1
    prelaunch_digest: Digest
    source_save_digest: Digest
    company: CompanyID
    tile: TileID  # host tile of the commanded corner
    max_cost: Money
    native_test_cost: Money
    before_digest: Digest
    expectation: TerraformExpectation

    @model_validator(mode="after")
    def coherent(self) -> TerraformIntent:
        if self.tile != self.expectation.host_tile:
            raise ValueError("intent tile differs from the expected host tile")
        return self

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()


class TerraformRequest(Contract):
    protocol: Literal[3] = 3
    op: Literal["inspect", "terraform", "read"]
    request_id: Annotated[str, Field(pattern=r"^[a-z0-9-]{1,32}$")]
    plan: Digest
    company: CompanyID
    tile: TileID
    corner: CornerName
    direction: DirectionName
    max_cost: Money

    def to_bytes(self) -> bytes:
        raw = canonical_bytes(self)
        if len(raw) > 512:
            raise ValueError("terraform request exceeds 512 bytes")
        return raw


class TerraformReadback(Contract):
    protocol: Literal[3] = 3
    op: Literal["inspect", "terraform", "read"]
    request_id: str
    plan: Digest
    company: CompanyID
    tile: TileID
    corner: CornerName
    direction: DirectionName
    status: Status
    flags: Flags
    industry: StrictInt | None = Field(ge=0, le=63999)
    owner: Annotated[StrictInt, Field(ge=-1, le=14)]
    min_height: Elevation
    slope: Slope
    h_n: Elevation
    h_e: Elevation
    h_s: Elevation
    h_w: Elevation
    eligible: StrictBool
    # Mirrors the package's own TERRAIN_RESPONSE_OUT_OF_BOUNDS gate so a report
    # the dispatcher refuses cannot be re-accepted in Python.
    funds: Annotated[StrictInt, Field(ge=-2147483648, le=2147483647)]
    cost: Annotated[StrictInt, Field(ge=0, le=2147483647)]

    @property
    def classification(self) -> TileClass:
        """The single native occupancy class by the frozen precedence rules."""
        return classify_tile(self.flags, self.industry)

    @property
    def corner_heights(self) -> tuple[int, int, int, int]:
        """Reported corner heights in the canonical N, E, W, S order."""
        return (self.h_n, self.h_e, self.h_w, self.h_s)

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()

    @classmethod
    def parse_for(cls, request: TerraformRequest, raw: bytes):
        if len(raw) > 512:
            raise ValueError("application response exceeds 512 bytes")

        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate response key")
                result[key] = value
            return result

        value = cls.model_validate(json.loads(raw, object_pairs_hook=unique))
        if any(
            getattr(value, k) != getattr(request, k)
            for k in (
                "protocol",
                "op",
                "request_id",
                "plan",
                "company",
                "tile",
                "corner",
                "direction",
            )
        ):
            raise ValueError("terraform response correlation mismatch")
        return value


def _observed_state(
    readback: TerraformReadback, state: TerraformShareState, *, after: bool
) -> None:
    """Required unowned, classified-clear geometry facts for one sharing tile.

    The exact expected slope cannot be satisfied by native noise: the reported
    slope plus its officially derived corner heights must both match exactly.
    """
    phase = "after" if after else "before"
    expected_min = state.after_min_height if after else state.before_min_height
    expected_slope = state.after_slope if after else state.before_slope
    try:
        heights = expected_corner_heights(expected_min, expected_slope)
    except ValueError as error:
        raise ValueError(f"tile {readback.tile}: derived slope encoding is unsupported") from error
    if (
        readback.owner != UNOWNED_COMPANY
        or readback.industry is not None
        or readback.classification != TileClass.CLEAR
        or (readback.min_height, readback.slope) != (expected_min, expected_slope)
        or readback.corner_heights != (heights["N"], heights["E"], heights["W"], heights["S"])
    ):
        raise ValueError(
            f"tile {readback.tile}: obstruction, ownership or geometry mismatch "
            f"against the {phase} expectation"
        )


def admit_terraform(
    before: TerraformReadback,
    neighbors: Sequence[TerraformReadback],
    expectation: TerraformExpectation,
    *,
    prelaunch_digest: str,
    source_save_digest: str,
    max_cost: int,
) -> TerraformIntent:
    """Latch the terraforming intent from a fresh native inspect readback.

    Requires a classified-clear, unowned host and all three other directly
    sharing tiles observed exactly at the derived expected on-disk geometry, a
    positive tested cost within the ceiling, and funds for it. A zero-cost
    native refusal (already at target height, map edge, terraform limit or any
    native refusal) is terminal: it must never trigger a mutation command, so
    it is refused here.
    """
    host_state = next(state for state in expectation.tiles if state.tile == expectation.host_tile)
    if before.status == "NO_OP":
        raise ValueError(
            "the tested native command reports no admissible change: "
            "no terraform command is authorized"
        )
    if (
        before.op != "inspect"
        or before.plan != prelaunch_digest
        or before.status != "READY"
        or not before.eligible
        or before.classification != TileClass.CLEAR
        or before.owner != UNOWNED_COMPANY
        or before.industry is not None
        or (before.tile, before.corner, before.direction)
        != (expectation.host_tile, expectation.corner, expectation.direction)
        or not 0 < before.cost <= max_cost
        or before.funds < before.cost
    ):
        raise ValueError(
            "native classified-clear unowned host, exact expected geometry, "
            "positive tested cost and funds required"
        )
    _observed_state(before, host_state, after=False)
    host = expectation.host_tile
    expected_neighbors = [tile for tile in expectation.sharing_tiles if tile != host]
    observed = [readback.tile for readback in neighbors]
    if len(neighbors) != 3 or sorted(observed) != expected_neighbors or len(set(observed)) != 3:
        raise ValueError("all three other directly sharing tiles must be freshly observed")
    by_tile = {readback.tile: readback for readback in neighbors}
    for tile in expected_neighbors:
        readback = by_tile[tile]
        state = next(state for state in expectation.tiles if state.tile == tile)
        if (
            readback.op != "read"
            or readback.status != "READ"
            or readback.plan != prelaunch_digest
            or readback.company != before.company
            or (readback.corner, readback.direction) != (expectation.corner, expectation.direction)
        ):
            raise ValueError(
                f"neighbor readback for tile {tile} is not a correlated inspection read"
            )
        _observed_state(readback, state, after=False)
    intent = TerraformIntent(
        prelaunch_digest=prelaunch_digest,
        source_save_digest=source_save_digest,
        company=before.company,
        tile=expectation.host_tile,
        max_cost=max_cost,
        native_test_cost=before.cost,
        before_digest=before.digest,
        expectation=expectation,
    )
    TerraformRequest(
        op="terraform",
        request_id="terraform-1",
        plan=prelaunch_digest,
        company=intent.company,
        tile=intent.tile,
        corner=intent.expectation.corner,
        direction=intent.expectation.direction,
        max_cost=intent.max_cost,
    ).to_bytes()
    return intent


def verify_terraform(
    intent: TerraformIntent,
    before: TerraformReadback,
    neighbors: Sequence[TerraformReadback],
    built: TerraformReadback,
    independent: Sequence[TerraformReadback],
) -> dict:
    """Verify one terraforming exchange group and emit the verified receipt."""
    if (
        admit_terraform(
            before,
            neighbors,
            intent.expectation,
            prelaunch_digest=intent.prelaunch_digest,
            source_save_digest=intent.source_save_digest,
            max_cost=intent.max_cost,
        )
        != intent
    ):
        raise ValueError("intent differs from native admitted facts")
    # Wire contract v3: the terraform readback must present the admission plan
    # (the prelaunch seal); every independent verification read stays
    # intent-scoped and presents the intent digest.
    direction_status = "RAISED" if intent.expectation.direction == "up" else "LOWERED"
    if (
        built.op != "terraform"
        or (built.plan, built.company, built.tile, built.corner, built.direction)
        != (
            intent.prelaunch_digest,
            intent.company,
            intent.tile,
            intent.expectation.corner,
            intent.expectation.direction,
        )
        or built.status != direction_status
        or built.cost != intent.native_test_cost
    ):
        raise ValueError("execution result/native tested cost disagreement or correlation mismatch")
    if before.funds - built.funds != built.cost:
        raise ValueError("native funds transition disagrees with the single command cost")
    host_state = next(
        state for state in intent.expectation.tiles if state.tile == intent.expectation.host_tile
    )
    heights = expected_corner_heights(host_state.after_min_height, host_state.after_slope)
    if (
        built.owner != UNOWNED_COMPANY
        or built.industry is not None
        or built.classification != TileClass.CLEAR
        or (built.min_height, built.slope) != (host_state.after_min_height, host_state.after_slope)
        or built.corner_heights != (heights["N"], heights["E"], heights["W"], heights["S"])
    ):
        raise ValueError("post-command host readback obstruction or geometry mismatch")
    observed = [readback.tile for readback in independent]
    if sorted(observed) != list(intent.expectation.sharing_tiles):
        raise ValueError("independent verification must cover all four sharing tiles")
    for readback in sorted(independent, key=lambda r: r.tile):
        state = next(state for state in intent.expectation.tiles if state.tile == readback.tile)
        if (
            readback.op != "read"
            or readback.status != "READ"
            or readback.plan != intent.digest
            or readback.company != intent.company
        ):
            raise ValueError(
                f"independent readback for tile {readback.tile} lacks intent-scoped correlation"
            )
        try:
            _observed_state(readback, state, after=True)
        except ValueError as error:
            raise ValueError(f"independent readback: {error}") from error
        if readback.funds != built.funds:
            raise ValueError(f"independent readback for tile {readback.tile} reveals spent funds")
    return dict(
        schema="company-terraform-receipt-v1",
        execution_request_id=built.request_id,
        readback_request_ids=tuple(readback.request_id for readback in independent),
        plan_digest=intent.digest,
        prelaunch_digest=intent.prelaunch_digest,
        source_save_digest=intent.source_save_digest,
        before_digest=before.digest,
        construction_digest=built.digest,
        after_digests=tuple(readback.digest for readback in independent),
        company=intent.company,
        tile=intent.tile,
        corner=intent.expectation.corner,
        direction=intent.expectation.direction,
        shared_point_x=intent.expectation.shared_point_x,
        shared_point_y=intent.expectation.shared_point_y,
        corner_mask=intent.expectation.corner_mask,
        operation="TERRAFORM_RAISE" if intent.expectation.direction == "up" else "TERRAFORM_LOWER",
        native_command="CMD_TERRAFORM_LAND",
        native_quote=intent.native_test_cost,
        execution_status=built.status,
        cost=built.cost,
        cost_category="terrain-modification",
        error_code=None,
        verification="NATIVE_STATE_CHANGED",
    )


def terraform_phase_outcome(attempts: list[tuple[str, dict]]) -> dict:
    """Fail-closed terraforming-phase verification over preserved evidence only.

    Each attempt is ``(label, evidence)`` where evidence holds the retained
    ``intent``, ``before``, ``neighbors`` and optional ``built``/
    ``independent`` readbacks. The first attempt whose evidence fails
    verification halts the phase: earlier verified receipts are preserved,
    later attempts are reported as pending, and no retry or compensating
    mutation is represented or implied. A failed attempt leaves the world
    state explicitly uncertain: a failed native terraform may still have
    auto-cleared tiles or shifted other geometry, and nothing claims otherwise.
    This verifies evidence; it never issues requests.
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
            neighbors = evidence.get("neighbors")
            built = evidence.get("built")
            if intent is None or before is None or neighbors is None or built is None:
                raise ValueError("terraform attempt lacks retained execution evidence")
            if (built.plan, built.company, built.tile, built.corner, built.direction) != (
                intent.prelaunch_digest,
                intent.company,
                intent.tile,
                intent.expectation.corner,
                intent.expectation.direction,
            ):
                raise ValueError("construction result correlation mismatch")
            direction_status = "RAISED" if intent.expectation.direction == "up" else "LOWERED"
            if built.status != direction_status or built.cost != intent.native_test_cost:
                raise ValueError("execution result/native tested cost disagreement")
            independent = evidence.get("independent")
            if independent is None:
                raise ValueError("terraform attempt lacks independent verification readbacks")
            receipts.append(verify_terraform(intent, before, neighbors, built, independent))
        except Exception as error:  # noqa: BLE001 - fail closed on any defect
            failed = dict(
                label=label,
                error=str(error),
                world_state="UNCERTAIN_AFTER_FAILED_COMMAND",
            )
    return dict(
        schema="terraform-phase-outcome-v1",
        completed=receipts,
        failed=failed,
        pending=pending,
        verification="PHASE_COMPLETE"
        if failed is None and len(attempts) > 0
        else "PARTIAL_EXECUTION_EVIDENCE",
    )
