"""Same-session observation assembly for the existing freight proof runner."""

import hashlib
import json
import subprocess
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import Field, StrictInt

from app.planning.canonical import canonical_bytes
from app.planning.domain import Contract, PreparedWorldManifest
from app.planning.optimizer import optimize_candidate_network
from app.planning.p08_adapter import MonthlyBatchPolicy, adapt_planning_facts
from app.planning.p08_road import NoRoadScenario, generate_road_scenario
from app.simulation.openttd.freight_planning import compile_freight_service
from app.simulation.openttd.gamescript_bridge import BridgePackage
from app.simulation.openttd.industry_inventory import IndustryInventoryWorld
from app.simulation.openttd.planning_fact_input import ValidatedPlanningFactInput
from app.simulation.openttd.prepared_source_correspondence import (
    ControlledSourceLinks,
    PreparedSourceCorrespondence,
)
from app.simulation.openttd.qualification_session import ProductionQualificationSession
from app.simulation.openttd.qualification_stability import QualificationProfile
from app.simulation.openttd.secure_admin import AuthState
from app.simulation.openttd.structural_world import StructuralWorldContext
from app.simulation.openttd.supplemental_planning_facts import SupplementalPlanningFacts
from app.simulation.openttd.world_planning_observation import WorldPlanningObservation

from .proof.qualification_native import QualificationNativeBackend, QualificationNativeTransport
from .proof.structural_native import StructuralRecordedSession


class PlanningRead(Contract):
    protocol: Literal[1] = 1
    type: Literal["planning_read"] = "planning_read"
    request_id: str = Field(pattern=r"^[A-Za-z0-9-]{1,32}$")
    kind: Literal["settings", "engines", "engine", "tile"]
    arg: StrictInt = Field(ge=0, le=4095)
    src: StrictInt = Field(ge=0, le=63999)
    dst: StrictInt = Field(ge=0, le=63999)
    cargo: StrictInt = Field(ge=0, le=63)

    def to_bytes(self):
        return canonical_bytes(self)


class PlanningReadback(Contract):
    protocol: Literal[1]
    type: Literal["planning_read_result"]
    request_id: str
    kind: str
    arg: StrictInt
    src: StrictInt
    dst: StrictInt
    cargo: StrictInt
    before: StrictInt = Field(ge=0)
    after: StrictInt = Field(ge=0)
    data: tuple[StrictInt, ...] = Field(max_length=32)

    @classmethod
    def parse_for(cls, request, raw):
        if len(raw) > 512:
            raise ValueError("planning read exceeds 512 bytes")

        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError("duplicate planning read field")
                value[key] = item
            return value

        json.loads(raw, object_pairs_hook=unique)
        response = cls.model_validate_json(raw)
        if (
            any(
                getattr(response, k) != getattr(request, k)
                for k in ("protocol", "request_id", "kind", "arg", "src", "dst", "cargo")
            )
            or response.after < response.before
        ):
            raise ValueError("planning read identity/bracket mismatch")
        size = dict(settings=8, engine=7, tile=19).get(request.kind)
        if size is not None and len(response.data) != size:
            raise ValueError("planning read shape mismatch")
        return response


_ISSUER = object()


class NativeSaveCorrespondence:
    """Live capability issued after qualified reads and two owned native saves."""

    def __init__(self, token, *, world, original_digest, final_digest, configuration_digest):
        if token is not _ISSUER:
            raise ValueError("owned native capture issuer required")
        self.world = world
        self.original_digest = original_digest
        self.final_digest = final_digest
        self.configuration_digest = configuration_digest

    def require_correspondence(self, correspondence):
        links = correspondence.links
        if correspondence.world is not self.world or (
            links.original_save_digest,
            links.post_qualification_save_digest,
            links.configuration_digest,
            correspondence.manifest.source_digest,
        ) != (
            self.original_digest,
            self.final_digest,
            self.configuration_digest,
            self.final_digest,
        ):
            raise ValueError("native save/qualified observation correspondence mismatch")
        links.require_world(self.world)


def native_correspondence(backend, prepared, world, manifest, original_digest, final_digest):
    """No caller-provided labels or save hashes alone can issue runtime authority."""
    from .proof.harness import sha256, write_json
    from .proof.industry_native import owned_admin_listener

    context = world.context
    process, session = backend.process, backend.session
    if (
        not isinstance(process, subprocess.Popen)
        or process.poll() is not None
        or process is not context.process_identity
        or session is not backend.secure_connection
        or context.connection_identity is not backend.structural_session
        or backend.structural_session.session is not session
        or session.state is not AuthState.ACTIVE
        or not owned_admin_listener(process.pid, prepared.endpoints[1])
        or Path(f"/proc/{process.pid}/exe").resolve() != prepared.spec.identity.executable.resolve()
        or backend.qualification_coordinator.result is not world.qualification
        or sha256(prepared.spec.workspace.config) != context.configuration_digest
    ):
        raise ValueError("owned continuous native qualification runtime required")
    raw = prepared.spec.stdout_path.read_text() + prepared.spec.stderr_path.read_text()
    for name, digest in (("before", original_digest), ("qualified", final_digest)):
        path = prepared.directory / (name + ".sav")
        marker = "Map successfully saved to '" + str(path)
        if (
            path.is_symlink()
            or not path.is_file()
            or sha256(path) != digest
            or raw.count(marker) != 1
        ):
            raise ValueError("unique completed owned native save required")
    links = ControlledSourceLinks(
        original_save_digest=original_digest,
        loaded_source_digest=None,
        runtime_digest=context.world.runtime_identity.sha256,
        configuration_digest=context.configuration_digest,
        bridge_digest=context.bridge.sha256,
        world_id=context.world.world_id,
        world_observation_digest=world.composition_digest,
        final_structural_digest=world.structural.structural_world_digest,
        qualified_production_digest=world.production.production_digest,
        post_qualification_save_digest=final_digest,
        evidence_kind="owned-native-save-snapshots",
    )
    # These links are semantic references. The independent live capability is the
    # authority; this generated-world path does not claim a loaded original save.
    authority = NativeSaveCorrespondence(
        _ISSUER,
        world=world,
        original_digest=original_digest,
        final_digest=final_digest,
        configuration_digest=context.configuration_digest,
    )
    write_json(
        prepared.directory / "native-save-correspondence.json",
        dict(
            schema="owned-freight-save-correspondence-v1",
            pid=process.pid,
            prelaunch_digest=sha256(prepared.directory / "PRELAUNCH.json"),
            runtime_digest=context.world.runtime_identity.sha256,
            configuration_digest=context.configuration_digest,
            bridge_digest=context.bridge.sha256,
            world_observation_digest=world.composition_digest,
            before_save_digest=original_digest,
            qualified_save_digest=final_digest,
            qualification_frames_digest=sha256(
                prepared.directory / "qualification-prefix-frames.json"
            ),
            admin_port=prepared.endpoints[1],
            encrypted=True,
        ),
    )
    return PreparedSourceCorrespondence(world, manifest, links, authority)


async def collect_qualified_world(backend, prepared, session, accounting):
    from .proof.harness import sha256

    backend.secure_connection = session
    backend.accounting = accounting
    backend.structural_session = StructuralRecordedSession(session)
    backend.query_operation_baseline = 0
    package = prepared.spec.workspace.game / "RoadFreightProof"
    bridge_digest = hashlib.sha256(
        b"".join(
            name.name.encode() + b"\0" + name.read_bytes() for name in sorted(package.glob("*.nut"))
        )
    ).hexdigest()
    context = StructuralWorldContext(
        IndustryInventoryWorld.from_welcome(
            "freight-planner", prepared.spec.identity, session.welcome
        ),
        BridgePackage(package, bridge_digest),
        sha256(prepared.spec.workspace.config),
        backend.process,
        backend.structural_session,
    )
    transport = QualificationNativeTransport(
        backend.structural_session, session.protocol, context, backend
    )
    transport._registered = True  # Exactly the subscription already counted by this accounting.
    coordinator = ProductionQualificationSession(
        transport,
        context,
        accounting,
        QualificationProfile(True, True, True, True),
        session_id="freight-plan",
    )
    backend.qualification_coordinator = coordinator

    async def evidence(request, exchange):
        return await QualificationNativeBackend.evidence(backend, prepared, request, exchange)

    result = await coordinator.collect(evidence, evidence, evidence, evidence, evidence)
    from .proof.harness import write_json
    from .proof.qualification_attempt import _public_evidence

    write_json(
        prepared.directory / "qualification-session.json", _public_evidence(asdict(result.evidence))
    )
    write_json(prepared.directory / "qualification-prefix-frames.json", backend.planning_frames)
    write_json(
        prepared.directory / "qualification-log-prefixes.json",
        {
            row["request"].request_id: dict(
                bytes=len(row["gamescript"].raw_log),
                sha256=hashlib.sha256(row["gamescript"].raw_log).hexdigest(),
            )
            for row in backend.structural_session.transactions
        },
    )
    session._frame_observer = backend.planning_frame_observer
    return WorldPlanningObservation(result.verification.stability.final, result)


async def capture_planning_facts(backend, prepared, world, *, read_exchange=None, retain=True):
    from .proof.freight_delivery import exchange
    from .proof.harness import sha256, write_json

    # Discover relationships from qualified structure, not the demo's assumed IDs.
    caps = world.structural.capability.observation.capabilities
    positive = {
        (r.industry_id, r.cargo_id) for r in world.production.records if r.last_month_produced > 0
    }
    freight = {r.cargo_id for r in world.structural.catalog.observation.records if r.is_freight}
    relationships = sorted(
        (src.industry_id, dst.industry_id, cargo)
        for src in caps
        for cargo in src.produces
        for dst in caps
        if (src.industry_id, cargo) in positive
        and cargo in freight
        and src.industry_id != dst.industry_id
        and cargo in dst.accepts
    )
    if not relationships:
        raise ValueError("no qualified compatible freight relationship")
    src, dst, cargo = relationships[0]
    records = {r.id: r for r in world.structural.inventory.observation.records}
    a, b = records[src], records[dst]
    x, y = min(a.x, b.x) - 2, min(a.y, b.y) - 2
    width, height = abs(a.x - b.x) + 4, abs(a.y - b.y) + 4
    if x < 1 or y < 1 or x + width >= 63 or y + height >= 63 or width * height > 256:
        raise ValueError("qualified freight region exceeds bounded capture")
    responses = []

    async def read(kind, arg=0):
        backend.health()
        request = PlanningRead(
            request_id=f"planning-{len(responses)}",
            kind=kind,
            arg=arg,
            src=src,
            dst=dst,
            cargo=cargo,
        )
        response = await (read_exchange or exchange)(
            backend.session, request, prepared.directory, response_type=PlanningReadback
        )
        responses.append(response)
        return response.data

    settings = await read("settings")
    if settings[2] != 0 or settings[3] not in (3, 4):
        raise ValueError("calendar default-content catchment required")
    engines = []
    for engine in await read("engines"):
        row = await read("engine", engine)
        if row[1] != cargo:
            continue
        engines.append(
            dict(
                engine_id=row[0],
                default_cargo_id=row[1],
                engine_road_type_id=row[2],
                public_available=True,
                articulated=False,
                has_power_on_road=True,
                capacity_cargo_units=row[3],
                purchase_cost_gbp=row[4],
                running_cost_gbp_per_economy_year=row[5],
                max_speed_native=row[6],
            )
        )
    tiles, coverage = [], []
    names = (
        "buildable",
        "water",
        "coast",
        "tree",
        "farm",
        "rock",
        "rough",
        "road",
        "rail",
        "water_transport",
        "air_transport",
    )
    for ty in range(y, y + height):
        for tx in range(x, x + width):
            row = await read("tile", ty * 64 + tx)
            if any(v not in (0, 1) for v in row[3:14] + row[17:19]):
                raise ValueError("nonboolean native planning fact")
            tiles.append(
                dict(
                    tile_id=row[0],
                    x=tx,
                    y=ty,
                    min_height=row[1],
                    slope=row[2],
                    **dict(zip(names, map(bool, row[3:14]))),
                    industry_id=None if row[14] == -1 else row[14],
                )
            )
            for industry, role, covered in ((src, "pickup", row[17]), (dst, "delivery", row[18])):
                coverage.append(
                    dict(
                        tile_id=row[0],
                        industry_id=industry,
                        cargo_id=cargo,
                        role=role,
                        producer_count=row[15],
                        acceptance_eighths=row[16],
                        industry_covered=bool(covered),
                    )
                )
    context = world.context
    content = sha256(prepared.directory / "graphics-identity.json")
    facts = SupplementalPlanningFacts.model_validate_json(
        json.dumps(
            dict(
                schema_version=1,
                transport_mode="road",
                source=dict(
                    world_observation_digest=world.composition_digest,
                    structural_digest=world.structural.structural_world_digest,
                    production_digest=world.production.production_digest,
                    world_id=context.world.world_id,
                    runtime_digest=context.world.runtime_identity.sha256,
                    configuration_digest=context.configuration_digest,
                    bridge_digest=context.bridge.sha256,
                    content_digest=content,
                    map_width=64,
                    map_height=64,
                ),
                region=dict(x=x, y=y, width=width, height=height),
                settings=dict(
                    content_digest=content,
                    generation_seed=42,
                    modified_catchment=bool(settings[0]),
                    serve_neutral_industries=bool(settings[1]),
                    timekeeping="calendar",
                    effective_truck_stop_radius=settings[3],
                    context="company-0",
                    gameplay_newgrf_ids=[],
                ),
                road=dict(
                    road_type_id=0,
                    public_available=True,
                    max_speed_native=settings[4],
                    road_piece_cost_gbp=settings[5],
                    truck_stop_cost_gbp=settings[6],
                    depot_cost_gbp=settings[7],
                    currency="GBP",
                ),
                tiles=tiles,
                coverage=coverage,
                engines=engines,
                coverage_scopes=[
                    dict(industry_id=src, cargo_id=cargo, role="pickup"),
                    dict(industry_id=dst, cargo_id=cargo, role="delivery"),
                ],
                capture_economy_date_before=responses[0].before,
                capture_economy_date_after=responses[-1].after,
            )
        )
    )
    facts.require_world(world)
    backend.planning_read_count = len(responses)
    if retain:
        write_json(
            prepared.directory / "supplemental-planning-facts.json", facts.model_dump(mode="json")
        )
    return facts


async def plan_same_world(backend, prepared, session, accounting, before, *, batch_limit):
    from .proof.harness import write_json
    from .proof.road_mutation import save

    world = await collect_qualified_world(backend, prepared, session, accounting)
    # Qualification accounting closes here; subsequent bounded reads are retained
    # by the runner's continuous secure frame observer, never by a second connection.
    facts = await capture_planning_facts(backend, prepared, world)
    final = await save(backend, prepared, "qualified")
    from .proof.freight_delivery import exchange

    scopes = {s.role: s for s in facts.coverage_scopes}
    seal_read = await exchange(
        session,
        PlanningRead(
            request_id="planning-seal",
            kind="settings",
            arg=0,
            src=scopes["pickup"].industry_id,
            dst=scopes["delivery"].industry_id,
            cargo=scopes["pickup"].cargo_id,
        ),
        prepared.directory,
        response_type=PlanningReadback,
    )
    month = world.production.qualification.current_month
    if not month.start_date <= seal_read.before <= seal_read.after < month.end_date:
        raise ValueError("native post-qualification save crossed the final collection month")
    backend.planning_read_count += 1
    manifest = PreparedWorldManifest(
        schema_version=1,
        source_digest=final,
        openttd_version="15.3",
        base_set_name="OpenGFX",
        base_set_version="8.0",
        width_tiles=64,
        height_tiles=64,
        seed=42,
        resolved_sites=(),
        cargo_types=(),
        vehicle_types=(),
        buildable_tiles=(),
    )
    source = native_correspondence(backend, prepared, world, manifest, before, final)
    policy = MonthlyBatchPolicy(
        start_date=date(1950, 1, 1), budget_gbp=Decimal(100000), delivery_batch_limit=batch_limit
    )
    road = generate_road_scenario(
        adapt_planning_facts(ValidatedPlanningFactInput(world, facts, source), policy)
    )
    if isinstance(road, NoRoadScenario):
        raise ValueError(f"P08 {road.code}: {road.detail}")
    result = optimize_candidate_network(road.scenario)
    service = compile_freight_service(road, result.plan)
    write_json(prepared.directory / "world-planning-observation.json", json.loads(world.to_bytes()))
    write_json(
        prepared.directory / "prepared-source-links.json", source.links.model_dump(mode="json")
    )
    write_json(prepared.directory / "planning-policy.json", policy.model_dump(mode="json"))
    write_json(prepared.directory / "planning-scenario.json", road.scenario.model_dump(mode="json"))
    write_json(prepared.directory / "execution-plan.json", result.plan.model_dump(mode="json"))
    return service, final
