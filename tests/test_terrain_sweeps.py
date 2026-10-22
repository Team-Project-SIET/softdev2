"""Two independently complete controlled sweeps through public admission."""

import hashlib
import json
from dataclasses import FrozenInstanceError, replace

import pytest

from app.simulation.openttd.supplemental_planning_facts import Region
from app.simulation.openttd.terrain_pagination import PaginationBudget
from app.simulation.openttd.terrain_sweeps import (
    TerrainSweepContext,
    TerrainTwoSweep,
    TwoSweepBudget,
)
from tests.test_terrain_pagination import exchange


def context():
    return TerrainSweepContext("pair", "a" * 64, 64, 64, Region(x=1, y=1, width=6, height=1))


def test_complete_equal_pair():
    c = context()
    pair = TerrainTwoSweep(c)
    for sweep in (1, 2):
        for q in pair.requests:
            pair.accept(("pair", sweep), c, exchange(q))
        pair.complete_sweep()
    result = pair.finish()
    assert [r[0] for r in result.rows] == [65, 66, 67, 68, 69, 70]
    assert pair.state == "ACCEPTED"
    assert result.metadata["pages"] == 4
    assert result.metadata["query_operations"] == 16
    assert (
        result.sweeps[0].exchanges[0].request_payload
        != result.sweeps[1].exchanges[0].request_payload
    )


def changed(ex, mutate):
    value = json.loads(ex.response_payload)
    mutate(value)
    payload = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return replace(
        ex,
        response_payload=payload,
        receipt=replace(ex.receipt, response_payload_sha256=hashlib.sha256(payload).hexdigest()),
    )


def collect(pair, c, sweep):
    for q in pair.requests:
        pair.accept((c.acquisition_id, sweep), c, exchange(q, c.map_width, c.map_height))
    pair.complete_sweep()


@pytest.mark.parametrize("n", [1, 5, 6, 255, 256])
def test_sizes_and_independent_replay(n):
    region = (
        Region(x=1, y=1, width=16, height=16) if n == 256 else Region(x=1, y=1, width=n, height=1)
    )
    c = TerrainSweepContext("size", "a" * 64, 512, 512, region)
    pair = TerrainTwoSweep(c)
    collect(pair, c, 1)
    assert pair.state == "SECOND_COLLECTING"
    collect(pair, c, 2)
    r = pair.finish()
    assert len(r.rows) == n
    assert len(r.sweeps[0].exchanges) == (n + 4) // 5
    r.verify()
    assert pair.finish() is r
    with pytest.raises(FrozenInstanceError):
        setattr(r, "context", replace(c, world_fingerprint="b" * 64))
    assert r.context is c
    metadata = r.metadata
    metadata["sweeps"][0]["complete"] = False
    assert r.metadata["sweeps"][0]["complete"] is True
    with pytest.raises(ValueError, match="ACCEPTED"):
        pair.accept(("size", 2), c, r.sweeps[1].exchanges[0])
    assert pair.finish() is r


@pytest.mark.parametrize(
    "field,value", [(0, 99), (1, 1), (2, 1), (3, 2), (4, 1), (5, 1), (6, 1), (7, 2), (8, 2), (9, 0)]
)
def test_every_row_field_is_checked(field, value):
    c = context()
    pair = TerrainTwoSweep(c)
    collect(pair, c, 1)
    ex = changed(exchange(pair.requests[0]), lambda o: o["tiles"][0].__setitem__(field, value))
    with pytest.raises(ValueError):
        pair.accept(("pair", 2), c, ex)
        for q in pair.requests[1:]:
            pair.accept(("pair", 2), c, exchange(q))
        pair.complete_sweep()
    assert pair.state == "REJECTED"
    with pytest.raises(ValueError):
        pair.finish()


@pytest.mark.parametrize("sweep", [1, 2])
@pytest.mark.parametrize("problem", ["missing", "duplicate", "order", "abort"])
def test_coverage_failures_are_terminal(sweep, problem):
    c = context()
    p = TerrainTwoSweep(c)
    if sweep == 2:
        collect(p, c, 1)
    q = p.requests
    if problem == "abort":
        p.abort("Interrupted")
    else:
        with pytest.raises(ValueError):
            if problem == "missing":
                p.accept(("pair", sweep), c, exchange(q[0]))
                p.complete_sweep()
            elif problem == "order":
                p.accept(("pair", sweep), c, exchange(q[1]))
            else:
                p.accept(("pair", sweep), c, exchange(q[0]))
                p.accept(("pair", sweep), c, exchange(q[0]))
    assert p.state == "REJECTED"
    with pytest.raises(ValueError):
        p.complete_sweep()


@pytest.mark.parametrize(
    "change", ["fingerprint", "geometry", "region", "sweep", "sequence", "date"]
)
def test_identity_and_transport_failure(change):
    c = context()
    p = TerrainTwoSweep(c)
    collect(p, c, 1)
    ex = exchange(p.requests[0])
    observed, identity = c, ("pair", 2)
    if change == "fingerprint":
        observed = replace(c, world_fingerprint="b" * 64)
    elif change == "geometry":
        observed = replace(c, map_width=128)
    elif change == "region":
        observed = replace(c, region=Region(x=2, y=1, width=6, height=1))
    elif change == "sweep":
        identity = ("pair", 1)
    elif change == "sequence":
        ex = replace(ex, ordered_sequence=("wrong",))
    else:
        # Establish a later date in the first sweep, then regress.
        p = TerrainTwoSweep(c)
        for q in p.requests:
            p.accept(
                ("pair", 1),
                c,
                changed(exchange(q), lambda o: o.update(date_before=3, date_after=3)),
            )
        p.complete_sweep()
        ex = exchange(p.requests[0])
    with pytest.raises(ValueError):
        p.accept(identity, observed, ex)
    assert p.state == "REJECTED"


@pytest.mark.parametrize(
    "field,limit", [("max_request_bytes", 350), ("max_response_bytes", 800), ("max_operations", 12)]
)
def test_combined_budget_cannot_reset(field, limit):
    c = context()
    p = TerrainTwoSweep(c, combined_budget=replace(TwoSweepBudget(), **{field: limit}))
    collect(p, c, 1)
    with pytest.raises(ValueError, match="Combined budget"):
        collect(p, c, 2)
    assert p.state == "REJECTED"


@pytest.mark.parametrize(
    "kwargs",
    [{"max_pages": 3}, {"max_pages": True}, {"max_operations": 833}, {"max_response_bytes": 0}],
)
def test_invalid_or_insufficient_budget(kwargs):
    with pytest.raises(ValueError, match="budget"):
        TerrainTwoSweep(context(), combined_budget=TwoSweepBudget(**kwargs))


def test_per_sweep_budget_and_distinct_transport_metadata():
    c = context()
    p = TerrainTwoSweep(c, per_sweep_budget=PaginationBudget(max_operations=4))
    with pytest.raises(ValueError, match="budget"):
        collect(p, c, 1)
    p = TerrainTwoSweep(c)
    collect(p, c, 1)
    for q in p.requests:
        ex = changed(exchange(q), lambda o: o.update(date_before=4, date_after=4))
        p.accept(("pair", 2), c, replace(ex, protocol_operations=8))
    p.complete_sweep()
    r = p.finish()
    assert r.metadata["query_operations"] == 24
    r.verify()
    ex = r.sweeps[1].exchanges[0]
    forged = replace(ex, response_payload=ex.response_payload + b" ")
    bad = replace(
        r,
        sweeps=(r.sweeps[0], replace(r.sweeps[1], exchanges=(forged, *r.sweeps[1].exchanges[1:]))),
    )
    with pytest.raises(ValueError):
        bad.verify()
