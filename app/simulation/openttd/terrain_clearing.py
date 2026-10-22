"""One owned bounded clearing intent, reusing the verified road-mutation pattern.

This is a bounded demolition intent for a single tile in an independently
classified clearing-eligible native class (trees, farm fields, rough or rocky
ground). It is not a substitute for native terrain validation: only a fresh
native test-mode quote and fresh native tile reads authorize its command.
`GSTile.IsBuildable()` is never treated as proof of road-readiness.
"""

import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictInt

from app.planning.canonical import canonical_bytes
from app.planning.domain import Contract, Digest
from app.simulation.openttd.road_mutation import UNOWNED_COMPANY
from app.simulation.openttd.tile_classification import (
    FLAG_MASK_LIMIT,
    TileClass,
    classify_tile,
)

CompanyID = Annotated[StrictInt, Field(ge=0, le=14)]
Money = Annotated[StrictInt, Field(ge=0, le=2147483647)]
TileID = Annotated[StrictInt, Field(ge=0, le=65535)]
# 0..65535 covers both the 64x64 disposable mutation world (<=4095) and the
# 256x256 retained Seed 17 census world. Elevation/slope bounds match the
# frozen classification wire contract.
Elevation = Annotated[StrictInt, Field(ge=0, le=255)]
Slope = Annotated[StrictInt, Field(ge=0, le=31)]
Flags = Annotated[StrictInt, Field(ge=0, le=(1 << 15) - 1)]
# ScriptCompany::COMPANY_INVALID (-1) is the only admissible owner: clearing may
# never act on company-owned or protected infrastructure.
AllowedClass = Literal["TREES", "FARM", "ROUGH", "ROCK"]

# Native classes eligible for one bounded DemolishTile clearing operation.
# Every other TileClass value (house, station, industry, water, coast, airport,
# road, rail, dock, CLEAR, UNKNOWN_OCCUPANCY) is rejected by precedence.
ALLOWED_CLEARING_CLASSES: tuple[str, ...] = (
    TileClass.TREES.value,
    TileClass.FARM.value,
    TileClass.ROUGH.value,
    TileClass.ROCK.value,
)
assert set(ALLOWED_CLEARING_CLASSES) <= {member.value for member in TileClass}


class ClearingIntent(Contract):
    schema_version: Literal[1] = 1
    prelaunch_digest: Digest
    source_save_digest: Digest
    company: CompanyID
    tile: TileID
    max_cost: Money
    native_test_cost: Money
    before_digest: Digest
    expected_classification: AllowedClass

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()


class ClearingRequest(Contract):
    # Adopted wire contract v2: the executing clear presents the admission
    # plan identity (the inspect request's plan), so the GameScript mutation
    # boundary can compare it against the latched admission before
    # GSTile.DemolishTile. Protocol 1 is retired.
    protocol: Literal[2] = 2
    op: Literal["inspect", "clear", "read"]
    request_id: Annotated[str, Field(pattern=r"^[a-z0-9-]{1,32}$")]
    plan: Digest
    company: CompanyID
    tile: TileID
    max_cost: Money

    def to_bytes(self) -> bytes:
        raw = canonical_bytes(self)
        if len(raw) > 512:
            raise ValueError("clearing request exceeds 512 bytes")
        return raw


class ClearingReadback(Contract):
    protocol: Literal[2] = 2
    op: Literal["inspect", "clear", "read"]
    request_id: str
    plan: Digest
    company: CompanyID
    tile: TileID
    status: Literal[
        "READY",
        "NO_OP",
        "CLEARED",
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
    flags: int = Field(ge=0, le=FLAG_MASK_LIMIT)
    industry: StrictInt | None = Field(ge=0, le=63999)
    owner: Annotated[StrictInt, Field(ge=-1, le=14)]
    elevation: Elevation
    slope: Slope
    eligible: StrictBool
    funds: StrictInt
    cost: StrictInt

    @property
    def classification(self) -> TileClass:
        """The single native occupancy class by the frozen precedence rules."""
        return classify_tile(self.flags, self.industry)

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()

    @classmethod
    def parse_for(cls, request: ClearingRequest, raw: bytes):
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
            for k in ("protocol", "op", "request_id", "plan", "company", "tile")
        ):
            raise ValueError("clearing response correlation mismatch")
        return value


def admit_clearing(
    before: ClearingReadback, *, prelaunch_digest: str, source_save_digest: str, max_cost: int
):
    """Latch the clearing intent from a fresh native inspect readback.

    Requires exactly one allowed clearing class on an unowned tile, a positive
    tested cost within the ceiling, and funds for it. An already-clear tile is
    a NO_OP: it must never trigger a demolition command, so it is refused here.
    """
    if before.status == "NO_OP":
        raise ValueError("already-clear tile: no demolition command is required")
    classification = before.classification
    if (
        before.op != "inspect"
        or before.plan != prelaunch_digest
        or before.status != "READY"
        or not before.eligible
        or classification.value not in ALLOWED_CLEARING_CLASSES
        or before.owner != UNOWNED_COMPANY
        or not 0 < before.cost <= max_cost
        or before.funds < before.cost
    ):
        raise ValueError(
            "native allowed clearing class, unowned tile, positive tested cost and funds required"
        )
    intent = ClearingIntent(
        prelaunch_digest=prelaunch_digest,
        source_save_digest=source_save_digest,
        company=before.company,
        tile=before.tile,
        max_cost=max_cost,
        native_test_cost=before.cost,
        before_digest=before.digest,
        expected_classification=classification.value,
    )
    ClearingRequest(
        op="clear",
        request_id="clear-1",
        plan=prelaunch_digest,
        company=intent.company,
        tile=intent.tile,
        max_cost=intent.max_cost,
    ).to_bytes()
    return intent


def verify_clearing(
    intent: ClearingIntent,
    before: ClearingReadback,
    built: ClearingReadback,
    after: ClearingReadback,
) -> dict:
    """Verify one clearing exchange group and emit the verified receipt."""
    if (
        admit_clearing(
            before,
            prelaunch_digest=intent.prelaunch_digest,
            source_save_digest=intent.source_save_digest,
            max_cost=intent.max_cost,
        )
        != intent
    ):
        raise ValueError("intent differs from native admitted facts")
    # Adopted wire contract v2: the CLEAR readback must present the admission
    # plan (the prelaunch seal) its inspect latched under; the independent
    # read stays intent-scoped and carries the intent digest.
    for value, expected_plan in ((built, intent.prelaunch_digest), (after, intent.digest)):
        if (value.plan, value.company, value.tile) != (
            expected_plan,
            intent.company,
            intent.tile,
        ):
            raise ValueError("independent native clearing correlation mismatch")
    if built.op != "clear" or built.status != "CLEARED" or built.cost != intent.native_test_cost:
        raise ValueError("execution result/native tested cost disagreement")
    if (
        after.op != "read"
        or after.status != "READ"
        or after.classification != TileClass.CLEAR
        or after.owner != UNOWNED_COMPANY
        or after.industry is not None
        or (after.elevation, after.slope) != (before.elevation, before.slope)
        or after.funds != built.funds
        or before.funds - built.funds != built.cost
    ):
        raise ValueError("independent readback: obstruction, ownership or geometry mismatch")
    return dict(
        schema="company-clearing-receipt-v1",
        execution_request_id=built.request_id,
        readback_request_id=after.request_id,
        plan_digest=intent.digest,
        prelaunch_digest=intent.prelaunch_digest,
        source_save_digest=intent.source_save_digest,
        before_digest=before.digest,
        construction_digest=built.digest,
        after_digest=after.digest,
        company=intent.company,
        tile=intent.tile,
        original_classification=intent.expected_classification,
        expected_classification=TileClass.CLEAR.value,
        operation="DEMOLISH_CLEAR",
        native_command="CMD_LANDSCAPE_CLEAR",
        native_quote=intent.native_test_cost,
        execution_status=built.status,
        cost=built.cost,
        error_code=None,
        verification="NATIVE_STATE_CHANGED",
    )


def phase_outcome(attempts: list[tuple[str, dict]]) -> dict:
    """Fail-closed clearing-phase verification over preserved evidence only.

    Each attempt is ``(label, evidence)`` where evidence holds the retained
    ``intent``, ``before`` and optional ``built``/``after`` readbacks. The
    first attempt whose evidence fails verification halts the phase: earlier
    verified receipts are preserved, later attempts are reported as pending,
    and no retry or compensating demolition is represented or implied. This
    verifies evidence; it never issues requests.
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
            if intent is None or before is None or built is None:
                raise ValueError("clearing attempt lacks retained execution evidence")
            # Wire contract v2: the built CLEAR readback carries the admission
            # plan (compare against the prelaunch seal, never the intent
            # digest).
            if (built.plan, built.company, built.tile) != (
                intent.prelaunch_digest,
                intent.company,
                intent.tile,
            ):
                raise ValueError("independent native clearing correlation mismatch")
            if built.status != "CLEARED" or built.cost != intent.native_test_cost:
                raise ValueError("execution result/native tested cost disagreement")
            after = evidence.get("after")
            if after is None:
                raise ValueError("clearing attempt lacks an independent readback")
            receipts.append(verify_clearing(intent, before, built, after))
        except Exception as error:  # noqa: BLE001 - fail closed on any defect
            failed = dict(label=label, error=str(error))
    return dict(
        schema="clearing-phase-outcome-v1",
        completed=receipts,
        failed=failed,
        pending=pending,
        verification="PHASE_COMPLETE"
        if failed is None and len(attempts) > 0
        else "PARTIAL_EXECUTION_EVIDENCE",
    )
