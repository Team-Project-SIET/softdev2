"""Bounded, native-only single freight delivery evidence; no planning assumptions."""

import hashlib
import json
from typing import Literal

from pydantic import StrictInt

from app.planning.canonical import canonical_bytes
from app.planning.domain import Contract, Digest

OPERATIONS = Literal["inspect", "build", "read", "observe", "finish"]
MAX_COST = 100000
OBS_TICKS = 2048
OBS_SAMPLES = 2049
OBS_SECONDS = 60


class DeliveryRequest(Contract):
    protocol: Literal[1] = 1
    op: OPERATIONS
    request_id: str
    plan: Digest
    arg: StrictInt = 0
    max_cost: Literal[100000] = MAX_COST

    def to_bytes(self):
        if (
            not 0 <= self.arg <= 9
            or not self.request_id.replace("-", "").isalnum()
            or len(self.request_id) > 32
            or not self.request_id.isascii()
        ):
            raise ValueError("invalid bounded delivery request")
        return canonical_bytes(self)


class DeliveryReadback(Contract):
    protocol: Literal[1]
    op: OPERATIONS
    request_id: str
    plan: Digest
    arg: StrictInt
    max_cost: Literal[100000]
    status: str
    # industry IDs, cargo, engine, two stop/front pairs, depot, bend
    a: tuple[StrictInt, ...]
    # native industry types/locations, production, capacity, price, coverage
    f: tuple[StrictInt, ...]
    # tick,date,pause,funds,vid,owner,engine,capacity,tile,state,speed,load,
    # count,order0,order1,waiting,sid0,sid1,delivered,income,profit,lastaccepted,
    # stage,cost,pickupmonitor,deliverymonitor,firsttick,samples
    s: tuple[StrictInt, ...]

    @property
    def digest(self):
        return hashlib.sha256(canonical_bytes(self)).hexdigest()

    @classmethod
    def parse_for(cls, q, raw):
        if len(raw) > 512:
            raise ValueError("response exceeds 512 bytes")

        def unique(pairs):
            d = {}
            for k, v in pairs:
                if k in d:
                    raise ValueError("duplicate response key")
                d[k] = v
            return d

        json.loads(raw, object_pairs_hook=unique)
        r = cls.model_validate_json(raw)
        if any(
            getattr(r, k) != getattr(q, k)
            for k in ("protocol", "op", "request_id", "plan", "arg", "max_cost")
        ):
            raise ValueError("response identity mismatch")
        if len(r.a) != 10 or len(r.f) != 8 or len(r.s) != 30:
            raise ValueError("native snapshot shape mismatch")
        admission_diagnostics(r)
        return r


class DeliveryPlan(Contract):
    prelaunch_digest: Digest
    source_save_digest: Digest
    predecessor_receipt_digest: Digest | None = None
    executor_source_digest: Digest | None = None
    admission_digest: Digest
    a: tuple[StrictInt, ...]
    f: tuple[StrictInt, ...]

    @property
    def digest(self):
        return hashlib.sha256(canonical_bytes(self)).hexdigest()


def admit(r, seal, save, predecessor, *, executor_source=None):
    if (
        r.status != "READY"
        or r.plan != seal
        or r.a[0] == r.a[1]
        or min(r.a[:4]) < 0
        or r.f[4] <= 0
        or r.f[5] <= 0
        or r.f[6] <= 0
        or not 1 <= r.f[7] <= 4
        or r.s[2] != 0
        or r.s[4] != -1
        or r.s[22] != 0
        or not 0 < r.s[23] <= min(MAX_COST, r.s[3])
    ):
        diagnostic = admission_diagnostics(r)
        detail = f"; diagnostics={diagnostic}" if diagnostic else ""
        raise ValueError(
            "native OD, buildability, supply, capacity, costs and funds admission required" + detail
        )
    return DeliveryPlan(
        prelaunch_digest=seal,
        source_save_digest=save,
        predecessor_receipt_digest=predecessor,
        executor_source_digest=executor_source,
        admission_digest=r.digest,
        a=r.a,
        f=r.f,
    )


def verify_snapshot(plan, r):
    if r.plan != plan.digest or r.a != plan.a or r.f != plan.f or r.s[2] != 0:
        raise ValueError("plan, native identities or pause mismatch")
    if r.s[22] >= 6 and r.s[28] != 1:
        raise ValueError("native connected owned route required")
    if r.s[22] >= 7 and (r.s[4] < 0 or r.s[5] != 0 or r.s[6] != plan.a[3] or r.s[7] != plan.f[5]):
        raise ValueError("vehicle ownership, engine or capacity mismatch")
    if r.s[22] >= 9 and (
        r.s[12] != 2 or r.s[13] != plan.a[4] or r.s[14] != plan.a[6] or r.s[29] != 1
    ):
        raise ValueError("two native orders required")


def verify_observation(plan, r, phase):
    verify_snapshot(plan, r)
    if (
        r.status != "OBSERVED"
        or r.arg != phase
        or not 0 <= r.s[0] - r.s[26] <= OBS_TICKS
        or not 1 <= r.s[27] <= OBS_SAMPLES
    ):
        raise ValueError("bounded native observation failed or inconclusive")
    if phase == 0 and r.s[15] <= 0:
        raise ValueError("source station availability not observed")
    if phase == 1 and (r.s[11] != plan.f[5] or r.s[8] != plan.a[4]):
        raise ValueError("full native source loading not observed")
    if phase == 2 and (r.s[8] != plan.a[6] or r.s[9] != 3 or r.s[11] <= 0):
        raise ValueError("loaded destination arrival not observed")
    if phase == 3 and r.s[11] != 0:
        raise ValueError("unloading not observed")


def verify_delivery(plan, baseline, observations, final):
    if len(observations) != 4:
        raise ValueError("four ordered native cargo observations required")
    verify_snapshot(plan, baseline)
    if baseline.s[22] != 9 or baseline.s[11] != 0 or final.s[22] != 10:
        raise ValueError("empty pre-start vehicle and complete lifecycle required")
    previous_tick = baseline.s[0]
    for phase, r in enumerate(observations):
        if r.s[0] < previous_tick or r.s[4] != baseline.s[4] or r.s[22] != 10:
            raise ValueError("cargo observation chronology or vehicle mismatch")
        previous_tick = r.s[0]
        verify_observation(plan, r, phase)
    verify_snapshot(plan, final)
    loaded = observations[1].s[11]
    if (
        final.s[0] < previous_tick
        or final.s[4] != baseline.s[4]
        or final.status != "DELIVERED"
        or final.s[11] != 0
        or final.s[24] != loaded
        or final.s[25] != loaded
        or final.s[18] - baseline.s[18] != loaded
        or final.s[19] <= baseline.s[19]
        or final.s[20] <= baseline.s[20]
        or final.s[21] < baseline.s[1]
    ):
        raise ValueError("native source pickup, industry delivery and actual payment required")
    return dict(
        schema="first-freight-delivery-receipt-v1",
        plan_digest=plan.digest,
        source=plan.a[0],
        destination=plan.a[1],
        cargo=plan.a[2],
        engine=plan.a[3],
        vehicle=final.s[4],
        route=list(plan.a[4:]),
        orders=[dict(tile=plan.a[4], flags=64), dict(tile=plan.a[6], flags=128)],
        loaded=loaded,
        delivered=final.s[25],
        pickup_monitor=final.s[24],
        payment_income=final.s[19] - baseline.s[19],
        vehicle_profit_delta=final.s[20] - baseline.s[20],
        native_digests=[baseline.digest] + [r.digest for r in observations] + [final.digest],
        verification="NATIVE_FINAL_INDUSTRY_DELIVERY_AND_PAYMENT",
    )


ADMISSION_COUNTERS = (
    "engines_seen",
    "engines_compatible",
    "pairs",
    "same_industry",
    "no_supply",
    "not_accepted",
    "layouts",
    "topology",
    "footprint",
    "height",
    "radius",
    "pickup_identity",
    "production_count",
    "acceptance",
    "destination_coverage",
    "quote",
    "budget",
    "funds",
)


def admission_diagnostics(r: DeliveryReadback):
    """Decode failure-only v2 overlay; historical snapshots have no counters."""
    if r.op != "inspect" or r.status == "READY" or r.s[29] != 2:
        return None
    counters = r.a + r.f
    limits = (33, 32, 32768, 32768, 32768, 32768) + (64,) * 12
    first = r.s[28]
    if (
        any(not 0 <= n <= limit for n, limit in zip(counters, limits, strict=True))
        or counters[1] > counters[0]
        or sum(counters[3:6]) > counters[2]
        or sum(counters[7:]) != counters[6]
        or not (
            first == 0
            and not any(counters[3:6] + counters[7:])
            or 4 <= first <= 18
            and counters[first - 1] > 0
        )
    ):
        raise ValueError("invalid admission diagnostics")
    classification = "NO_CANDIDATES_GENERATED" if counters[2] == 0 else "CANDIDATES_REJECTED"
    if r.status == "INVALID_WORLD":
        classification = "PRECONDITION_REJECTED"
    elif r.status in ("ENGINE_LIMIT", "INDUSTRY_LIMIT", "SITE_SEARCH_EXHAUSTED"):
        classification = "SEARCH_LIMIT_REACHED"
    return dict(
        classification=classification,
        first_rejection=ADMISSION_COUNTERS[first - 1] if first else None,
        counters=dict(zip(ADMISSION_COUNTERS, counters, strict=True)),
    )
