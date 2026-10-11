"""Bounded four-tile native construction facts and receipt verification."""

import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictInt

from app.planning.canonical import canonical_bytes
from app.planning.domain import Contract, Digest
from app.simulation.openttd.road_mutation import CompanyID, Money, TileID

STAGES: tuple[Literal["road"], Literal["stop"], Literal["depot"]] = ("road", "stop", "depot")


class FreightRequest(Contract):
    protocol: Literal[1] = 1
    op: Literal["inspect", "road", "stop", "depot", "read"]
    request_id: Annotated[str, Field(pattern=r"^[a-z0-9-]{1,32}$")]
    plan: Digest
    company: CompanyID
    start: TileID
    end: TileID
    max_cost: Money

    def to_bytes(self) -> bytes:
        raw = canonical_bytes(self)
        if len(raw) > 512 or self.end != self.start + 1 or not 1 <= self.start % 64 <= 60:
            raise ValueError("four horizontal interior tiles required")
        return raw


class FreightReadback(Contract):
    protocol: Literal[1]
    op: Literal["inspect", "road", "stop", "depot", "read"]
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
        "OUT_OF_ORDER",
        "COST_CHANGED",
        "UNSUPPORTED_ROAD_TYPE",
    ]
    owners: tuple[StrictInt, StrictInt, StrictInt, StrictInt]
    road: tuple[StrictBool, StrictBool]
    stop: StrictBool
    truck: StrictBool
    depot: StrictBool
    fronts: tuple[StrictInt, StrictInt]
    links: tuple[StrictBool, StrictBool, StrictBool]
    eligible: StrictBool
    funds: StrictInt
    costs: tuple[Money, Money, Money]
    cost: Money
    sid: StrictInt

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()

    @classmethod
    def parse_for(cls, request: FreightRequest, raw: bytes):
        if len(raw) > 512:
            raise ValueError("application response exceeds 512 bytes")

        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate response key")
                result[key] = value
            return result

        json.loads(raw, object_pairs_hook=unique)
        value = cls.model_validate_json(raw)
        if any(
            getattr(value, k) != getattr(request, k)
            for k in ("protocol", "op", "request_id", "plan", "company", "start", "end")
        ):
            raise ValueError("freight response correlation mismatch")
        return value


class FreightConstructionPlan(Contract):
    schema_version: Literal[1] = 1
    prelaunch_digest: Digest
    source_save_digest: Digest
    before_digest: Digest
    company: CompanyID
    start: TileID
    end: TileID
    max_cost: Money
    native_costs: tuple[Money, Money, Money]

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()


def admit_site(
    before: FreightReadback, *, prelaunch_digest: str, source_save_digest: str, max_cost: int
) -> FreightConstructionPlan:
    FreightRequest(
        op="inspect",
        request_id=before.request_id,
        plan=prelaunch_digest,
        company=before.company,
        start=before.start,
        end=before.end,
        max_cost=max_cost,
    ).to_bytes()
    if (
        before.op != "inspect"
        or before.plan != prelaunch_digest
        or before.status != "READY"
        or not before.eligible
        or before.owners != (-1, -1, -1, -1)
        or any(before.road)
        or before.stop
        or before.truck
        or before.depot
        or any(before.links)
        or before.fronts != (-1, -1)
        or before.sid != -1
        or any(c <= 0 for c in before.costs)
        or before.cost != 0
        or not sum(before.costs) <= min(max_cost, before.funds)
    ):
        raise ValueError("native vacant four-tile site, three test costs and funds required")
    return FreightConstructionPlan(
        prelaunch_digest=prelaunch_digest,
        source_save_digest=source_save_digest,
        before_digest=before.digest,
        company=before.company,
        start=before.start,
        end=before.end,
        max_cost=max_cost,
        native_costs=before.costs,
    )


def verify_state(plan: FreightConstructionPlan, value: FreightReadback, stage: int) -> None:
    c = plan.company
    expected_owners = ((-1, c, c, -1), (c, c, c, -1), (c, c, c, c))[stage]
    if (
        (value.plan, value.company, value.start, value.end)
        != (plan.digest, c, plan.start, plan.end)
        or value.owners != expected_owners
        or value.road != (True, True)
        or value.stop != (stage >= 1)
        or value.truck != (stage >= 1)
        or value.depot != (stage >= 2)
        or value.fronts != (plan.start if stage >= 1 else -1, plan.end if stage >= 2 else -1)
        or value.links != (stage >= 1, True, stage >= 2)
        or ((value.sid >= 0) != (stage >= 1))
    ):
        raise ValueError("independent native ownership, facility or topology mismatch")


def verify_construction(
    plan: FreightConstructionPlan,
    before: FreightReadback,
    exchanges: list[tuple[FreightReadback, FreightReadback]],
) -> dict:
    if (
        admit_site(
            before,
            prelaunch_digest=plan.prelaunch_digest,
            source_save_digest=plan.source_save_digest,
            max_cost=plan.max_cost,
        )
        != plan
    ):
        raise ValueError("plan differs from admitted native facts")
    if len(exchanges) != 3:
        raise ValueError("exactly three construction and readback pairs required")
    funds = before.funds
    operations = []
    station_id = -1
    for i, (built, after) in enumerate(exchanges):
        verify_step(plan, built, after, i, funds)
        if i == 2 and after.sid != station_id:
            raise ValueError("station identity changed during depot construction")
        station_id = after.sid
        operations.append(
            dict(
                operation=STAGES[i],
                cost=built.cost,
                construction_digest=built.digest,
                readback_digest=after.digest,
            )
        )
        funds = after.funds
    return dict(
        schema="road-freight-infrastructure-receipt-v1",
        plan_digest=plan.digest,
        prelaunch_digest=plan.prelaunch_digest,
        source_save_digest=plan.source_save_digest,
        before_digest=before.digest,
        company=plan.company,
        tiles=[plan.start - 1, plan.start, plan.end, plan.end + 1],
        station_id=exchanges[-1][1].sid,
        spent=sum(plan.native_costs),
        operations=operations,
        verification="NATIVE_INFRASTRUCTURE_STATE_CHANGED",
    )


def verify_step(
    plan: FreightConstructionPlan,
    built: FreightReadback,
    after: FreightReadback,
    stage: int,
    funds: int,
) -> None:
    verify_state(plan, built, stage)
    verify_state(plan, after, stage)
    if (
        built.op != STAGES[stage]
        or built.status != "BUILT"
        or after.op != "read"
        or after.status != "READ"
        or built.cost != plan.native_costs[stage]
        or after.cost != 0
        or funds - built.funds != built.cost
        or after.funds != built.funds
        or built.sid != after.sid
        or built.costs != plan.native_costs
        or after.costs != plan.native_costs
    ):
        raise ValueError("construction result or native spending mismatch")
