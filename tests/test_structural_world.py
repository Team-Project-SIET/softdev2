"""Structural-world assembly and coordinator at typed query/evidence seams; no live runtime."""

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_industry_inventory import InventoryWire, world_context

from app.simulation.openttd.cargo_catalog import CargoCatalogSession
from app.simulation.openttd.cargo_page import (
    CargoCatalogRecord,
    CargoPageRequest,
    CargoPageResponse,
)
from app.simulation.openttd.cargo_page_evidence import parse_cargo_page_evidence
from app.simulation.openttd.gamescript_bridge import BridgePackage
from app.simulation.openttd.industry_capability import IndustryCapabilitySession
from app.simulation.openttd.industry_cargo import (
    IndustryCargoCapability,
    IndustryCargoRequest,
    IndustryCargoResponse,
)
from app.simulation.openttd.industry_cargo_evidence import parse_industry_cargo_evidence
from app.simulation.openttd.industry_query import IndustryInventorySession
from app.simulation.openttd.structural_world import (
    ScopedObservation,
    StructuralWorldContext,
    StructuralWorldObservation,
)


def context():
    return StructuralWorldContext(
        world_context(),
        BridgePackage(Path("controlled-bridge"), "f" * 64),
        "c" * 64,
        object(),
        object(),
    )


def token(value):
    return "null" if value is None else str(value)


class StructuralWire(InventoryWire):
    """Synthetic Admin peer; real DTOs, frame decoder, transport and evidence validators."""

    def __init__(self, industries=(2, 17), cargoes=(1, 9, 63), produces=(1,), accepts=(9,)):
        from app.simulation.openttd.admin_protocol import encode_admin_frame

        super().__init__(industries)
        self.context = replace(context(), connection_identity=self.transport.session)
        self.cargoes, self.produces, self.accepts = cargoes, produces, accepts
        self.all_requests = []
        original = self.writer.write.side_effect

        def send(frame):
            if frame[2] != 6:
                return original(frame)
            obj = json.loads(frame[3:-1])
            self.all_requests.append(obj)
            if obj["type"] == "industry_page":
                return original(frame)
            if obj["type"] == "industry_cargo":
                q = IndustryCargoRequest.parse(frame[3:-1])
                r = IndustryCargoResponse(
                    q.request_id,
                    IndustryCargoCapability(q.industry_id, self.produces, self.accepts),
                )
            else:
                q = CargoPageRequest.parse(frame[3:-1])
                ids = [i for i in self.cargoes if q.after_id is None or i > q.after_id]
                selected = ids[: q.limit]
                more = len(ids) > len(selected)
                records = tuple(CargoCatalogRecord(i, "434F414C", True, 0, 16) for i in selected)
                r = CargoPageResponse(q.request_id, records, selected[-1] if more else None, more)
            self.reader.feed_data(encode_admin_frame(124, r.to_bytes() + b"\0"))

        self.writer.write.side_effect = send

    @property
    def session(self):
        return self.transport.session

    async def industry_page(self, *args, **kwargs):
        return await self.transport.industry_page(*args, **kwargs)

    async def industry_cargo(self, *args, **kwargs):
        return await self.transport.industry_cargo(*args, **kwargs)

    async def cargo_page(self, *args, **kwargs):
        return await self.transport.cargo_page(*args, **kwargs)

    async def cargo_evidence(self, q, exchange):
        r = exchange.response.capability
        p, a = r.produces, r.accepts
        read = (
            f"industry_id={q.industry_id} produced_count={len(p)} accepted_count={len(a)} "
            f"first_produced={token(p[0] if p else None)} "
            f"last_produced={token(p[-1] if p else None)} "
            f"first_accepted={token(a[0] if a else None)} "
            f"last_accepted={token(a[-1] if a else None)}"
        )
        return parse_industry_cargo_evidence(
            self.log(q, "industry_cargo", "INDUSTRY_CARGO_READ", read), q.request_id
        )

    async def catalog_evidence(self, q, exchange):
        r = exchange.response
        ids = [c.cargo_id for c in r.cargoes]
        read = (
            f"after_id={token(q.after_id)} limit={q.limit} returned_count={len(ids)} "
            f"first_id={token(ids[0] if ids else None)} last_id={token(ids[-1] if ids else None)} "
            f"next_after_id={token(r.next_after_id)} has_more={str(r.has_more).lower()}"
        )
        return parse_cargo_page_evidence(
            self.log(q, "cargo_page", "CARGO_PAGE_READ", read), q.request_id
        )

    def log(self, q, command, marker, read):
        lines = [
            f"BRIDGE_REQUEST_RECEIVED request_id={q.request_id} type={command} protocol=1",
            f"{marker} request_id={q.request_id} {read}",
            f"BRIDGE_RESPONSE_SENT request_id={q.request_id} "
            f"type={command}_result status=ok protocol=1",
            f"BRIDGE_POST_RESPONSE_ALIVE request_id={q.request_id}",
        ]
        return "".join("dbg: [script:4] [18] [I] " + s + "\n" for s in lines).encode()


async def sources(wire=None, page_size=2, prefix="synthetic"):
    wire = wire or StructuralWire()
    ctx = wire.context
    inventory = await IndustryInventorySession(
        prefix + "-inv", ctx.world, page_size=page_size
    ).collect(wire, wire.evidence)
    capability = await IndustryCapabilitySession(prefix + "-cap", inventory).collect(
        wire, wire.cargo_evidence
    )
    catalog = await CargoCatalogSession(
        prefix + "-cat",
        page_size=page_size,
        runtime_identity=ctx.world.runtime_identity,
        world_id=ctx.world.world_id,
    ).collect(wire, wire.catalog_evidence)
    return (
        ScopedObservation(inventory, ctx),
        ScopedObservation(capability, ctx),
        ScopedObservation(catalog, ctx),
    )


def test_complete_structural_observation_references_valid_immutable_sources():
    async def run():
        inventory, capability, catalog = await sources()
        observation = StructuralWorldObservation(inventory, capability, catalog)
        assert observation.complete
        assert observation.industry_count == observation.capability_count == 2
        assert observation.cargo_count == 3
        assert observation.ordered_industry_ids == (2, 17)
        assert observation.ordered_cargo_ids == (1, 9, 63)
        assert observation.inventory_digest == inventory.observation.inventory_digest
        assert observation.capability_digest == capability.observation.capability_digest
        assert observation.cargo_catalog_digest == catalog.observation.catalog_digest
        assert observation.runtime_identity == inventory.context.world.runtime_identity

    asyncio.run(run())


@pytest.mark.parametrize(
    "kind", ["process", "connection", "runtime", "map", "world", "config", "bridge"]
)
def test_cross_run_or_world_context_cannot_assemble_complete(kind):
    async def run():
        inv, cap, cat = await sources()
        ctx = cat.context
        changes = {
            "process": dict(process_identity=object()),
            "connection": dict(connection_identity=object()),
            "runtime": dict(
                world=replace(
                    ctx.world, runtime_identity=replace(ctx.world.runtime_identity, sha256="b" * 64)
                )
            ),
            "map": dict(world=replace(ctx.world, map_width=128)),
            "world": dict(world=replace(ctx.world, world_id="another-world")),
            "config": dict(configuration_digest="d" * 64),
            "bridge": dict(bridge=replace(ctx.bridge, sha256="e" * 64)),
        }
        with pytest.raises(ValueError, match="share runtime/world/process/connection"):
            StructuralWorldObservation(
                inv, cap, replace(cat, context=replace(ctx, **changes[kind]))
            )

    asyncio.run(run())


@pytest.mark.parametrize("produces,accepts", [((63,), ()), ((), (63,))])
def test_missing_referenced_produced_or_accepted_cargo_rejected(produces, accepts):
    async def run():
        components = await sources(
            StructuralWire(cargoes=(1, 9), produces=produces, accepts=accepts)
        )
        with pytest.raises(ValueError, match="missing catalog cargo IDs.*63"):
            StructuralWorldObservation(*components)

    asyncio.run(run())


@pytest.mark.parametrize(
    "industries,produces,accepts,cargoes",
    [
        ((), (), (), (1, 9)),
        ((17,), (1,), (), (1, 9)),
        ((2, 17), (1,), (1, 9), (1, 9, 63)),
        ((0, 31), (63,), (63,), (0, 9, 63)),
    ],
)
def test_empty_sparse_shared_and_unreferenced_cargo_valid(industries, produces, accepts, cargoes):
    async def run():
        result = StructuralWorldObservation(
            *await sources(StructuralWire(industries, cargoes, produces, accepts))
        )
        assert result.complete and result.industry_count == len(industries)
        assert result.cargo_count == len(cargoes)

    asyncio.run(run())


def test_digest_independent_of_pagination_request_ids_and_transient_paths():
    async def run():
        a = StructuralWorldObservation(*await sources(page_size=1, prefix="first"))
        components = await sources(page_size=2, prefix="second")
        ctx = components[0].context
        world = replace(
            ctx.world,
            runtime_identity=replace(
                ctx.world.runtime_identity, executable=Path("/tmp/other-runtime")
            ),
        )
        moved = replace(
            ctx, world=world, bridge=replace(ctx.bridge, directory=Path("/tmp/other-bridge"))
        )
        inv = replace(components[0].observation, world=world)
        cap = replace(components[1].observation, inventory=inv)
        cat = replace(components[2].observation, runtime_identity=world.runtime_identity)
        b = StructuralWorldObservation(
            ScopedObservation(inv, moved),
            ScopedObservation(cap, moved),
            ScopedObservation(cat, moved),
        )
        assert a.structural_world_digest == b.structural_world_digest
        assert a.to_bytes() == b.to_bytes()
        assert b"/tmp/" not in b.to_bytes() and b"first" not in a.to_bytes()

    asyncio.run(run())


def test_coordinator_orders_phases_and_retains_complete_evidence():
    from app.simulation.openttd.structural_world_session import StructuralWorldSession

    async def run():
        wire = StructuralWire()
        session = StructuralWorldSession(wire.context)
        observation = await session.collect(
            wire, wire.evidence, wire.cargo_evidence, wire.catalog_evidence
        )
        assert observation.complete
        assert [q["type"] for q in wire.all_requests] == [
            "industry_page",
            "industry_cargo",
            "industry_cargo",
            "cargo_page",
            "cargo_page",
        ]
        assert [q["request_id"] for q in wire.all_requests] == [
            "openttd15-structural-world-001-inv-p001",
            "openttd15-structural-world-001-cap-i00002",
            "openttd15-structural-world-001-cap-i00017",
            "openttd15-structural-world-001-cat-p001",
            "openttd15-structural-world-001-cat-p002",
        ]
        assert session.evidence.events == (
            "STRUCTURAL_WORLD_SESSION_STARTED",
            "INDUSTRY_INVENTORY_COMPLETED",
            "INDUSTRY_CAPABILITY_COMPLETED",
            "CARGO_CATALOG_COMPLETED",
            "REFERENTIAL_INTEGRITY_VALIDATED",
            "STRUCTURAL_WORLD_ASSEMBLED",
            "STRUCTURAL_WORLD_VERIFIED",
            "STRUCTURAL_WORLD_SESSION_COMPLETED",
        )
        assert (
            session.evidence.complete
            and session.evidence.structural_world_digest == observation.structural_world_digest
        )
        assert session.evidence.retries == session.evidence.reconnects == 0

    asyncio.run(run())


@pytest.mark.parametrize("phase", ["industry_page", "industry_cargo", "cargo_page"])
@pytest.mark.parametrize("failure", ["timeout", "disconnect"])
def test_timeout_disconnect_in_any_phase_fail_whole_session_without_resume(phase, failure):
    from app.simulation.openttd.structural_world_session import StructuralWorldSession

    async def run():
        wire = StructuralWire()
        send = wire.writer.write.side_effect

        def fail(frame):
            if frame[2] == 6 and json.loads(frame[3:-1])["type"] == phase:
                wire.all_requests.append(json.loads(frame[3:-1]))
                if failure == "disconnect":
                    wire.reader.feed_eof()
                return
            send(frame)

        wire.writer.write.side_effect = fail
        session = StructuralWorldSession(wire.context, timeout=0.02)
        with pytest.raises((TimeoutError, ConnectionError, ValueError)):
            await session.collect(wire, wire.evidence, wire.cargo_evidence, wire.catalog_evidence)
        before = tuple(wire.all_requests)
        assert not session.evidence.complete and session.evidence.structural_world_digest is None
        assert session.phase == "FAILED" and session.evidence.failure
        assert session.evidence.retries == session.evidence.reconnects == 0
        with pytest.raises(ValueError, match="single-use; no retry/resume"):
            await session.collect(wire, wire.evidence, wire.cargo_evidence, wire.catalog_evidence)
        assert tuple(wire.all_requests) == before
        assert [q["type"] for q in before].count(phase) == 1

    asyncio.run(run())


@pytest.mark.parametrize("phase", ["inventory", "capability", "catalog"])
@pytest.mark.parametrize("change", ["connection", "process", "map"])
def test_identity_change_during_evidence_blocks_following_phases(phase, change):
    from app.simulation.openttd.structural_world_session import StructuralWorldSession

    async def run():
        wire = StructuralWire()
        callbacks = [wire.evidence, wire.cargo_evidence, wire.catalog_evidence]
        index = ["inventory", "capability", "catalog"].index(phase)
        original = callbacks[index]

        async def changed(q, e):
            native = await original(q, e)
            if change == "connection":
                from app.simulation.openttd.gamescript_transport import GameScriptSession

                wire.transport.session = GameScriptSession(asyncio.StreamReader(), wire.writer)
            elif change == "process":
                wire.context = replace(wire.context, process_identity=object())
            else:
                wire.context = replace(
                    wire.context, world=replace(wire.context.world, map_height=128)
                )
            return native

        callbacks[index] = changed
        session = StructuralWorldSession(wire.context)
        with pytest.raises(
            ValueError, match="connection changed|share runtime/world/process/connection"
        ):
            await session.collect(wire, *callbacks)
        assert not session.evidence.complete
        assert session.observation is None
        assert len(wire.all_requests) == (1, 2, 4)[index]

    asyncio.run(run())


def test_combined_bounds_derived_and_exact_total_accepted():
    from app.simulation.openttd.structural_world import StructuralWorldBudget
    from app.simulation.openttd.structural_world_session import StructuralWorldSession

    assert StructuralWorldBudget() == StructuralWorldBudget(96, 49152, 1024)

    async def run():
        wire = StructuralWire()
        first = StructuralWorldSession(wire.context)
        observation = await first.collect(
            wire, wire.evidence, wire.cargo_evidence, wire.catalog_evidence
        )
        # Independently counted synthetic stream: startup query 7, four later queries 4 each.
        assert observation.total_requests == 5
        assert observation.protocol_operations == 23
        strict = StructuralWorldBudget(5, observation.total_response_bytes, 23)
        other = StructuralWire()
        result = await StructuralWorldSession(other.context, budget=strict).collect(
            other, other.evidence, other.cargo_evidence, other.catalog_evidence
        )
        assert result.complete

    asyncio.run(run())


@pytest.mark.parametrize("field", ["max_requests", "max_response_bytes", "max_operations"])
def test_over_combined_budget_fails_without_a_complete_observation(field):
    from app.simulation.openttd.structural_world import StructuralWorldBudget
    from app.simulation.openttd.structural_world_session import StructuralWorldSession

    async def run():
        wire = StructuralWire()
        baseline = StructuralWorldSession(wire.context)
        result = await baseline.collect(
            wire, wire.evidence, wire.cargo_evidence, wire.catalog_evidence
        )
        values = dict(
            max_requests=5, max_response_bytes=result.total_response_bytes, max_operations=23
        )
        values[field] -= 1
        other = StructuralWire()
        session = StructuralWorldSession(other.context, budget=StructuralWorldBudget(**values))
        with pytest.raises(ValueError, match="budget exhausted"):
            await session.collect(
                other, other.evidence, other.cargo_evidence, other.catalog_evidence
            )
        assert session.observation is None and not session.evidence.complete
        assert len(other.all_requests) <= 5

    asyncio.run(run())


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_requests", 97),
        ("max_response_bytes", 49153),
        ("max_operations", 1025),
        ("max_requests", 0),
        ("max_response_bytes", True),
        ("max_operations", -1),
    ],
)
def test_invalid_combined_bounds(field, value):
    from app.simulation.openttd.structural_world import StructuralWorldBudget

    with pytest.raises(ValueError, match="invalid combined"):
        StructuralWorldBudget(**{field: value})


@pytest.mark.parametrize("missing_phase", ["inventory", "capability", "catalog"])
def test_assembly_rejects_missing_or_partial_component(missing_phase):
    async def run():
        components = list(await sources())
        index = ["inventory", "capability", "catalog"].index(missing_phase)
        components[index] = replace(components[index], observation=None)
        with pytest.raises(ValueError, match="typed complete component"):
            StructuralWorldObservation(*components)

    asyncio.run(run())


@pytest.mark.parametrize("phase", ["inventory", "capability", "catalog"])
def test_post_response_liveness_required_in_every_phase(phase):
    from app.simulation.openttd.structural_world_session import StructuralWorldSession

    async def run():
        wire = StructuralWire()
        callbacks = [wire.evidence, wire.cargo_evidence, wire.catalog_evidence]
        index = ["inventory", "capability", "catalog"].index(phase)
        original = callbacks[index]

        async def missing(q, e):
            native = await original(q, e)
            return replace(native, ordered_sequence=native.ordered_sequence[:-1])

        callbacks[index] = missing
        session = StructuralWorldSession(wire.context)
        with pytest.raises(ValueError):
            await session.collect(wire, *callbacks)
        assert not session.evidence.complete
        assert len(session.evidence.exchanges) == (1, 2, 4)[index]

    asyncio.run(run())


def test_empty_inventory_performs_zero_capability_queries_but_collects_catalog():
    from app.simulation.openttd.structural_world_session import StructuralWorldSession

    async def run():
        wire = StructuralWire(industries=())
        session = StructuralWorldSession(wire.context)
        result = await session.collect(
            wire, wire.evidence, wire.cargo_evidence, wire.catalog_evidence
        )
        assert result.complete and result.industry_count == result.capability_count == 0
        assert [q["type"] for q in wire.all_requests] == [
            "industry_page",
            "cargo_page",
            "cargo_page",
        ]

    asyncio.run(run())


def test_sources_immutable_and_failed_referential_join_preserves_source_digests():
    from dataclasses import FrozenInstanceError

    async def run():
        components = await sources(StructuralWire(cargoes=(9,), produces=(1,)))
        inv_digest = components[0].observation.inventory_digest
        cap_digest = components[1].observation.capability_digest
        with pytest.raises(ValueError, match="missing catalog cargo"):
            StructuralWorldObservation(*components)
        assert components[0].observation.inventory_digest == inv_digest
        assert components[1].observation.capability_digest == cap_digest
        with pytest.raises(FrozenInstanceError):
            components[0].observation.world = None
        with pytest.raises(FrozenInstanceError):
            components[1].context = None

    asyncio.run(run())


@pytest.mark.parametrize("different_ids", [(2,), (2, 17, 31), ()])
def test_capability_from_other_source_inventory_cannot_be_substituted(different_ids):
    async def run():
        inv, cap, cat = await sources()
        _, other, _ = await sources(StructuralWire(industries=different_ids))
        # Even attaching the same owner context cannot mask source inventory mismatch.
        with pytest.raises(ValueError, match="source inventory digest mismatch"):
            StructuralWorldObservation(inv, replace(other, context=cap.context), cat)

    asyncio.run(run())


def test_catalog_duplicate_record_cannot_complete_session():
    from app.simulation.openttd.structural_world_session import StructuralWorldSession

    async def run():
        wire = StructuralWire(cargoes=(1, 1))
        session = StructuralWorldSession(wire.context)
        with pytest.raises(ValueError):
            await session.collect(wire, wire.evidence, wire.cargo_evidence, wire.catalog_evidence)
        assert not session.evidence.complete and session.catalog is None

    asyncio.run(run())


def historical_sources():
    """Replay separate immutable runs; provenance keeps their ownership distinct."""
    from app.simulation.openttd.cargo_catalog import CargoCatalogObservation, CargoCatalogPage
    from app.simulation.openttd.cargo_page import (
        CARGO_PAGE_NETWORK_SEQUENCE,
        CargoPageExchange,
        CargoPageReceipt,
    )
    from app.simulation.openttd.industry_capability import (
        CapabilityTransaction,
        IndustryCapabilityObservation,
    )
    from app.simulation.openttd.industry_cargo import (
        CARGO_NETWORK_SEQUENCE,
        IndustryCargoExchange,
        IndustryCargoReceipt,
    )
    from app.simulation.openttd.industry_inventory import (
        IndustryInventoryObservation,
        IndustryInventoryPage,
    )
    from app.simulation.openttd.industry_page import (
        PAGE_NETWORK_SEQUENCE,
        IndustryPageExchange,
        IndustryPageReceipt,
        IndustryPageRequest,
    )
    from app.simulation.openttd.industry_page_evidence import parse_industry_page_evidence
    from app.simulation.openttd.runtime.identity import RuntimeIdentity

    enrichment = Path("tests/fixtures/industry_enrichment_v4_checkpoint")
    catalog = Path("tests/fixtures/cargo_catalog_checkpoint")
    runtime = json.loads((catalog / "runtime-identity.json").read_text())
    world = replace(
        world_context(),
        runtime_identity=RuntimeIdentity(
            Path(runtime["executable"]), runtime["version"], runtime["sha256"]
        ),
    )
    invctx = replace(context(), world=world)
    catctx = replace(invctx, process_identity=object(), connection_identity=object())

    def load_pairs(directory, phase):
        requests = [
            json.loads(s)
            for s in (directory / (phase + "-requests.jsonl")).read_text().splitlines()
        ]
        responses = [
            json.loads(s)
            for s in (directory / (phase + "-responses.jsonl")).read_text().splitlines()
        ]
        return zip(requests, responses, strict=True)

    pages = []
    for q, r in load_pairs(enrichment, "page"):
        request = IndustryPageRequest.parse(json.dumps(q).encode())
        raw = r["raw_payload"].encode()
        exchange = IndustryPageExchange(
            request.to_bytes(),
            raw,
            IndustryPageReceipt.correlate(request.to_bytes(), raw),
            PAGE_NETWORK_SEQUENCE,
        )
        pages.append(
            IndustryInventoryPage(
                exchange,
                parse_industry_page_evidence(
                    (enrichment / "stderr.log").read_bytes(), request.request_id
                ),
            )
        )
    inventory = IndustryInventoryObservation(
        "openttd15-industry-inventory-001", world, tuple(pages)
    )
    transactions = []
    for q, r in load_pairs(enrichment, "capability"):
        request = IndustryCargoRequest.parse(json.dumps(q).encode())
        raw = r["raw_payload"].encode()
        exchange = IndustryCargoExchange(
            request.to_bytes(),
            raw,
            IndustryCargoReceipt.correlate(request.to_bytes(), raw),
            CARGO_NETWORK_SEQUENCE,
        )
        transactions.append(
            CapabilityTransaction(
                exchange,
                parse_industry_cargo_evidence(
                    (enrichment / "stderr.log").read_bytes(), request.request_id
                ),
            )
        )
    capability = IndustryCapabilityObservation(
        "openttd15-industry-enrichment-001", inventory, tuple(transactions)
    )
    pages = []
    operations = [
        json.loads(s)["protocol_operations"]
        for s in (catalog / "page-verifications.jsonl").read_text().splitlines()
    ]
    for (q, r), frames in zip(load_pairs(catalog, "page"), operations, strict=True):
        request = CargoPageRequest.parse(json.dumps(q).encode())
        raw = r["raw_json"].encode()
        exchange = CargoPageExchange(
            request.to_bytes(),
            raw,
            CargoPageReceipt.correlate(request.to_bytes(), raw),
            CARGO_PAGE_NETWORK_SEQUENCE,
            protocol_operations=frames,
        )
        pages.append(
            CargoCatalogPage(
                exchange,
                parse_cargo_page_evidence(
                    (catalog / "stderr.log").read_bytes(), request.request_id
                ),
            )
        )
    observation = CargoCatalogObservation(
        "openttd15-cargo-catalog-001",
        tuple(pages),
        runtime_identity=world.runtime_identity,
        world_id=world.world_id,
    )
    return (
        ScopedObservation(inventory, invctx),
        ScopedObservation(capability, invctx),
        ScopedObservation(observation, catctx),
    )


def test_real_catalog_and_enrichment_regression_fixtures_are_valid_but_separate_runs():
    import hashlib

    inventory, capability, catalog = historical_sources()
    assert (
        inventory.observation.complete
        and capability.observation.complete
        and catalog.observation.complete
    )
    assert (
        inventory.observation.inventory_digest
        == "dce9b4d257af150776e679b09c74880b918163b86ae5e5f9f6e30e35d26c865a"
    )
    assert (
        capability.observation.capability_digest
        == "b65dc04752fffcc3958dac6cb40aa5a8cd017a3f23fb2408d9122c6bfb8a94b3"
    )
    assert (
        catalog.observation.catalog_digest
        == "2859ff3ddac519e712a8513d14605a32313bc2a2f487abf632238258a64dffaa"
    )
    assert catalog.observation.page_count == 6 and len(catalog.observation.records) == 11
    with pytest.raises(ValueError, match="share runtime/world/process/connection"):
        StructuralWorldObservation(inventory, capability, catalog)
    fixture = Path("tests/fixtures/cargo_catalog_checkpoint")
    for name, digest in json.loads((fixture / "manifest.json").read_text())["sha256"].items():
        assert hashlib.sha256((fixture / name).read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("phase", ["inventory", "capability", "catalog"])
def test_phase_barrier_only_exposes_completed_prior_sources(phase):
    from app.simulation.openttd.structural_world_session import StructuralWorldSession

    async def run():
        wire = StructuralWire()
        session = StructuralWorldSession(wire.context)
        callbacks = [wire.evidence, wire.cargo_evidence, wire.catalog_evidence]
        index = ["inventory", "capability", "catalog"].index(phase)
        original = callbacks[index]

        async def barrier(q, e):
            assert session.observation is None
            if index == 0:
                assert session.inventory is None and session.capability_session is None
                assert session.catalog_session.evidence.exchanges == ()
            if index == 1:
                assert session.inventory is not None
                assert session.inventory.complete and session.inventory.inventory_digest
                assert (
                    session.capability is None and session.catalog_session.evidence.exchanges == ()
                )
            if index == 2:
                assert session.inventory is not None and session.capability is not None
                assert session.inventory.complete and session.capability.complete
                assert session.catalog is None
            return await original(q, e)

        callbacks[index] = barrier
        await session.collect(wire, *callbacks)

    asyncio.run(run())


@pytest.mark.parametrize("phase", ["inventory", "capability", "catalog"])
def test_partial_subclass_cannot_be_promoted_to_complete_world(phase):
    async def run():
        components = list(await sources())
        index = ["inventory", "capability", "catalog"].index(phase)
        original = components[index].observation

        class Partial(type(original)):
            @property
            def complete(self):
                return False

        from dataclasses import fields

        partial = Partial(**{f.name: getattr(original, f.name) for f in fields(original)})
        components[index] = replace(components[index], observation=partial)
        with pytest.raises(ValueError, match="complete component observations"):
            StructuralWorldObservation(*components)

    asyncio.run(run())


@pytest.mark.parametrize("field", ["runtime_identity", "world_id"])
def test_catalog_internal_provenance_checked_even_when_scope_claims_match(field):
    async def run():
        inv, cap, cat = await sources()
        value = (
            replace(cat.observation.runtime_identity, sha256="d" * 64)
            if field == "runtime_identity"
            else "other-world"
        )
        altered = replace(cat.observation, **{field: value})
        with pytest.raises(ValueError, match="component world/runtime provenance mismatch"):
            StructuralWorldObservation(inv, cap, replace(cat, observation=altered))

    asyncio.run(run())


def test_failed_catalog_join_retains_components_but_never_world_digest():
    from app.simulation.openttd.structural_world_session import StructuralWorldSession

    async def run():
        wire = StructuralWire(cargoes=(9,), produces=(1,))
        session = StructuralWorldSession(wire.context)
        with pytest.raises(ValueError, match="missing catalog cargo"):
            await session.collect(wire, wire.evidence, wire.cargo_evidence, wire.catalog_evidence)
        assert session.inventory is not None
        assert session.capability is not None and session.catalog is not None
        assert (
            session.inventory.complete and session.capability.complete and session.catalog.complete
        )
        assert not session.evidence.complete and session.evidence.structural_world_digest is None
        assert "STRUCTURAL_WORLD_ASSEMBLED" not in session.evidence.events

    asyncio.run(run())


def test_incomplete_nested_capability_source_inventory_rejected():
    async def run():
        inv, cap, cat = await sources()

        class PartialInventory(type(inv.observation)):
            @property
            def complete(self):
                return False

        from dataclasses import fields

        partial = PartialInventory(
            **{f.name: getattr(inv.observation, f.name) for f in fields(inv.observation)}
        )
        capability = replace(cap.observation, inventory=partial)
        with pytest.raises(ValueError, match="complete capability source inventory"):
            StructuralWorldObservation(inv, replace(cap, observation=capability), cat)

    asyncio.run(run())


def test_pre_send_transport_failure_counts_attempt_without_claiming_a_sent_request():
    from app.simulation.openttd.gamescript_transport import TransportProtocolError
    from app.simulation.openttd.structural_world_session import StructuralWorldSession

    class UnavailableWire(StructuralWire):
        async def industry_page(self, *args, **kwargs):
            raise TransportProtocolError("transport unavailable before send")

    async def run():
        wire = UnavailableWire()
        session = StructuralWorldSession(wire.context)
        with pytest.raises(TransportProtocolError, match="unavailable before send"):
            await session.collect(wire, wire.evidence, wire.cargo_evidence, wire.catalog_evidence)
        assert session.evidence.request_attempts == 1
        assert wire.all_requests == [] and session.evidence.exchanges == ()
        assert not session.evidence.complete

    asyncio.run(run())
