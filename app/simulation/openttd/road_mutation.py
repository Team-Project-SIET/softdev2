"""One adjacent road-segment proof intent, independent of freight assumptions.

This is a bounded construction intent, not a substitute ExecutionPlan for freight.
Only native test-mode cost and fresh native tile reads can authorize its command.
"""

import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictInt

from app.planning.canonical import canonical_bytes
from app.planning.domain import Contract, Digest

TileID = Annotated[StrictInt, Field(ge=0, le=4095)]
CompanyID = Annotated[StrictInt, Field(ge=0, le=14)]
Money = Annotated[StrictInt, Field(ge=0, le=2147483647)]
# ScriptCompany::COMPANY_INVALID in the 15.3 API, not COMPANY_SPECTATOR (255).
UNOWNED_COMPANY = -1


class RoadSegmentIntent(Contract):
    schema_version: Literal[1] = 1
    prelaunch_digest: Digest
    source_save_digest: Digest
    company: CompanyID
    start: TileID
    end: TileID
    max_cost: Money
    native_test_cost: Money
    before_digest: Digest

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()


class RoadRequest(Contract):
    protocol: Literal[1] = 1
    op: Literal["inspect", "build", "read"]
    request_id: Annotated[str, Field(pattern=r"^[a-z0-9-]{1,32}$")]
    plan: Digest
    company: CompanyID
    start: TileID
    end: TileID
    max_cost: Money

    def to_bytes(self) -> bytes:
        raw = canonical_bytes(self)
        if (
            len(raw) > 512
            or abs(self.start % 64 - self.end % 64) + abs(self.start // 64 - self.end // 64) != 1
        ):
            raise ValueError("bounded adjacent segment required")
        return raw


class RoadReadback(Contract):
    protocol: Literal[1]
    op: Literal["inspect", "build", "read"]
    request_id: str
    plan: Digest
    company: CompanyID
    start: TileID
    end: TileID
    status: Literal[
        "READY",
        "BUILT",
        "READ",
        "INVALID_COMPANY",
        "INVALID_LOCATION",
        "NOT_BUILDABLE",
        "INSUFFICIENT_FUNDS",
        "COST_LIMIT",
        "REJECTED",
        "READBACK_MISMATCH",
        "ALREADY_ATTEMPTED",
        "UNSUPPORTED_ROAD_TYPE",
    ]
    owner0: StrictInt
    owner1: StrictInt
    road0: StrictBool
    road1: StrictBool
    connected: StrictBool
    eligible: StrictBool
    funds: StrictInt
    cost: StrictInt

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()

    @classmethod
    def parse_for(cls, request: RoadRequest, raw: bytes):
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
            for k in ("protocol", "op", "request_id", "plan", "company", "start", "end")
        ):
            raise ValueError("road response correlation mismatch")
        return value


def admit_segment(
    before: RoadReadback, *, prelaunch_digest: str, source_save_digest: str, max_cost: int
):
    if (
        before.op != "inspect"
        or before.plan != prelaunch_digest
        or before.status != "READY"
        or not before.eligible
        or before.road0
        or before.road1
        or before.connected
        or before.owner0 != UNOWNED_COMPANY
        or before.owner1 != UNOWNED_COMPANY
        or not 0 < before.cost <= max_cost
        or before.funds < before.cost
    ):
        raise ValueError("native vacant tiles, positive tested cost and funds required")
    intent = RoadSegmentIntent(
        prelaunch_digest=prelaunch_digest,
        source_save_digest=source_save_digest,
        company=before.company,
        start=before.start,
        end=before.end,
        max_cost=max_cost,
        native_test_cost=before.cost,
        before_digest=before.digest,
    )
    RoadRequest(
        op="build",
        request_id="build-1",
        plan=intent.digest,
        company=intent.company,
        start=intent.start,
        end=intent.end,
        max_cost=intent.max_cost,
    ).to_bytes()
    return intent


def verify_segment(
    intent: RoadSegmentIntent, before: RoadReadback, built: RoadReadback, after: RoadReadback
) -> dict:
    if (
        admit_segment(
            before,
            prelaunch_digest=intent.prelaunch_digest,
            source_save_digest=intent.source_save_digest,
            max_cost=intent.max_cost,
        )
        != intent
    ):
        raise ValueError("intent differs from native admitted facts")
    for value in (built, after):
        if (
            (value.plan, value.company, value.start, value.end)
            != (intent.digest, intent.company, intent.start, intent.end)
            or not (value.road0 and value.road1 and value.connected)
            or (value.owner0, value.owner1) != (intent.company, intent.company)
        ):
            raise ValueError("independent native road ownership/connectivity mismatch")
    if (
        built.op != "build"
        or built.status != "BUILT"
        or after.op != "read"
        or after.status != "READ"
        or built.cost != intent.native_test_cost
        or before.funds - built.funds != built.cost
    ):
        raise ValueError("construction result/native funds mismatch")
    return dict(
        schema="company-road-receipt-v1",
        plan_digest=intent.digest,
        prelaunch_digest=intent.prelaunch_digest,
        source_save_digest=intent.source_save_digest,
        before_digest=before.digest,
        construction_digest=built.digest,
        after_digest=after.digest,
        company=intent.company,
        start=intent.start,
        end=intent.end,
        cost=built.cost,
        owned_connected_road=True,
        verification="NATIVE_STATE_CHANGED",
    )
