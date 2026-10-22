"""Offline replay through the existing qualification and planning validators."""

import asyncio
import hashlib
import json
import zipfile
from dataclasses import asdict
from types import SimpleNamespace
from typing import Any

from app.planning.domain import PreparedWorldManifest
from app.simulation.openttd.admin_protocol import (
    ServerProtocol,
    ServerWelcome,
    decode_server_packet,
)
from app.simulation.openttd.gamescript_bridge import BridgePackage
from app.simulation.openttd.industry_inventory import IndustryInventoryWorld
from app.simulation.openttd.qualification_session import ProductionQualificationSession
from app.simulation.openttd.qualification_stability import QualificationProfile
from app.simulation.openttd.runtime.identity import RuntimeIdentity
from app.simulation.openttd.structural_world import StructuralWorldContext
from app.simulation.openttd.world_planning_observation import WorldPlanningObservation

from .proof.harness import sha256
from .proof.qualification_accounting import QualificationFrameBudget
from .proof.qualification_attempt import _public_evidence
from .proof.qualification_native import QualificationNativeBackend, QualificationNativeTransport
from .proof.structural_native import StructuralRecordedSession


async def replay_qualified_world(directory, metadata, runtime, *, recovery=None):
    from .proof.freight_delivery import PlannerBackend

    prefix = json.loads((directory / "qualification-prefix-frames.json").read_bytes())
    frames = json.loads((directory / "frames.json").read_bytes())
    if len(prefix) < 5 or frames[: len(prefix)] != prefix:
        raise ValueError("qualified reads must be the same continuous secure stream prefix")
    accounting = QualificationFrameBudget()

    class RetainedSession:
        reader = None
        _writer = None
        cursor = 5

        def __init__(self):
            self._frame_observer = accounting.observe

        async def send(self, *outbound):
            for frame in outbound:
                if self.cursor >= len(prefix) or prefix[self.cursor] != ["outbound", frame.hex()]:
                    raise ValueError("retained qualification outbound sequence mismatch")
                self.cursor += 1
                self._frame_observer("outbound", frame)

        async def receive(self, size=4096):
            if self.cursor >= len(prefix) or prefix[self.cursor][0] != "inbound":
                raise ValueError("retained qualification inbound sequence mismatch")
            frame = bytes.fromhex(prefix[self.cursor][1])
            self.cursor += 1
            self._frame_observer("inbound", frame)
            return frame

        async def require_quiescent(self):
            if self.cursor < len(prefix) and prefix[self.cursor][0] == "inbound":
                raise ValueError("unconsumed or duplicate retained qualification response")

    for direction, raw in prefix[:2]:
        accounting.observe(direction, bytes.fromhex(raw))
    accounting.enter("setup")
    for direction, raw in prefix[2:5]:
        accounting.observe(direction, bytes.fromhex(raw))
    session = RetainedSession()
    if metadata.get("scenario"):
        from .proof.freight_delivery import verify_capital_frames

        verify_capital_frames(directory, prefix[5:9], recovery=recovery)
        session.cursor = 9
    # Retained replay uses opaque ownership handles, never native process/socket handles.
    # Initialize only retained validator state. Native construction requires launch authority.
    backend: Any = object.__new__(PlannerBackend)
    backend.health = lambda: None
    backend.process = object()
    backend.session = backend.secure_connection = session
    backend.accounting = accounting
    recorded = StructuralRecordedSession(session)
    backend.structural_session = recorded
    backend.query_operation_baseline = 0
    with zipfile.ZipFile(directory / "frozen-source.zip") as archive:
        names = sorted(
            n for n in archive.namelist() if n.startswith("staged/") and n.endswith(".nut")
        )
        bridge_digest = hashlib.sha256(
            b"".join(n.removeprefix("staged/").encode() + b"\0" + archive.read(n) for n in names)
        ).hexdigest()
        configuration_digest = hashlib.sha256(archive.read("staged/openttd.cfg")).hexdigest()
    from pathlib import Path

    identity = RuntimeIdentity(Path(metadata["binary"]), "15.3", metadata["binary_sha256"])
    establishment = [bytes.fromhex(row[1]) for row in prefix[:2]]
    protocol = decode_server_packet(establishment[0][2], establishment[0][3:])
    welcome = decode_server_packet(establishment[1][2], establishment[1][3:])
    if (
        not isinstance(protocol, ServerProtocol)
        or not isinstance(welcome, ServerWelcome)
        or welcome != ServerWelcome(**runtime["welcome"])
    ):
        raise ValueError("native establishment/welcome evidence mismatch")
    context = StructuralWorldContext(
        IndustryInventoryWorld.from_welcome("freight-planner", identity, welcome),
        BridgePackage(directory, bridge_digest),
        configuration_digest,
        backend.process,
        backend.structural_session,
    )
    transport = QualificationNativeTransport(backend.structural_session, protocol, context, backend)
    transport._registered = True

    async def pace(_):
        pass

    coordinator = ProductionQualificationSession(
        transport,
        context,
        accounting,
        QualificationProfile(True, True, True, True),
        session_id="freight-plan",
        pace=pace,
    )
    backend.qualification_coordinator = coordinator
    log = (directory / "stderr.log").read_bytes()
    prefixes = json.loads((directory / "qualification-log-prefixes.json").read_bytes())

    class RetainedLog:
        def read_bytes(self):
            request = recorded.transactions[-1]["request"]
            entry = prefixes[request.request_id]
            size = entry["bytes"]
            if type(size) is not int or not 0 < size <= len(log):
                raise ValueError("qualification log prefix extent mismatch")
            raw = log[:size]
            if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                raise ValueError("qualification log prefix digest mismatch")
            return raw

    retained = SimpleNamespace(spec=SimpleNamespace(stderr_path=RetainedLog()))

    async def evidence(request, exchange):
        return await QualificationNativeBackend.evidence(backend, retained, request, exchange)

    result = await coordinator.collect(evidence, evidence, evidence, evidence, evidence)
    if session.cursor != len(prefix) or _public_evidence(asdict(result.evidence)) != json.loads(
        (directory / "qualification-session.json").read_bytes()
    ):
        raise ValueError("qualified semantic witness/continuous stream mismatch")
    return WorldPlanningObservation(result.verification.stability.final, result)


def replay_planning_binding(directory, metadata, runtime, native_plan):
    from app.planning.canonical import plan_hash, scenario_hash
    from app.planning.domain import ExecutionPlan, PlanningScenario
    from app.planning.optimizer import optimize_candidate_network
    from app.planning.p08_adapter import MonthlyBatchPolicy, adapt_planning_facts
    from app.planning.p08_road import NoRoadScenario, generate_road_scenario
    from app.simulation.openttd.freight_planning import compile_freight_service
    from app.simulation.openttd.planning_fact_input import ValidatedPlanningFactInput
    from app.simulation.openttd.prepared_source_correspondence import (
        ControlledSourceLinks,
        PreparedSourceCorrespondence,
    )
    from app.simulation.openttd.supplemental_planning_facts import SupplementalPlanningFacts

    world = asyncio.run(replay_qualified_world(directory, metadata, runtime))
    if json.loads(world.to_bytes()) != json.loads(
        (directory / "world-planning-observation.json").read_bytes()
    ):
        raise ValueError("qualified world observation replay mismatch")
    facts = SupplementalPlanningFacts.model_validate_json(
        (directory / "supplemental-planning-facts.json").read_bytes()
    )
    from app.simulation.openttd.freight_runtime_planning import capture_planning_facts

    async def retained_read(session, request, root, *, response_type):
        if (root / (request.request_id + "-request.json")).read_bytes() != request.to_bytes():
            raise ValueError("retained supplemental selection/target mismatch")
        return response_type.parse_for(
            request, (root / (request.request_id + "-response.json")).read_bytes()
        )

    reconstructed = asyncio.run(
        capture_planning_facts(
            SimpleNamespace(health=lambda: None, session=None),
            SimpleNamespace(directory=directory),
            world,
            read_exchange=retained_read,
            retain=False,
        )
    )
    if reconstructed != facts:
        raise ValueError("supplemental facts differ from native bounded readbacks")
    from app.simulation.openttd.freight_runtime_planning import PlanningRead, PlanningReadback

    scopes = {s.role: s for s in facts.coverage_scopes}
    seal_request = PlanningRead(
        request_id="planning-seal",
        kind="settings",
        arg=0,
        src=scopes["pickup"].industry_id,
        dst=scopes["delivery"].industry_id,
        cargo=scopes["pickup"].cargo_id,
    )
    seal_read = asyncio.run(
        retained_read(None, seal_request, directory, response_type=PlanningReadback)
    )
    month = world.production.qualification.current_month
    if not month.start_date <= seal_read.before <= seal_read.after < month.end_date:
        raise ValueError("retained post-qualification save bracket crossed M2")
    links = ControlledSourceLinks.model_validate_json(
        (directory / "prepared-source-links.json").read_bytes()
    )
    if links.original_save_digest != sha256(
        directory / "before.sav"
    ) or links.post_qualification_save_digest != sha256(directory / "qualified.sav"):
        raise ValueError("native saved-state correspondence digest mismatch")
    cleanup = json.loads((directory / "cleanup.json").read_bytes())
    expected_authority = dict(
        schema="owned-freight-save-correspondence-v1",
        pid=cleanup["pid"],
        prelaunch_digest=sha256(directory / "PRELAUNCH.json"),
        runtime_digest=world.context.world.runtime_identity.sha256,
        configuration_digest=world.context.configuration_digest,
        bridge_digest=world.context.bridge.sha256,
        world_observation_digest=world.composition_digest,
        before_save_digest=links.original_save_digest,
        qualified_save_digest=links.post_qualification_save_digest,
        qualification_frames_digest=sha256(directory / "qualification-prefix-frames.json"),
        admin_port=metadata["admin_port"],
        encrypted=True,
    )
    if (
        json.loads((directory / "native-save-correspondence.json").read_bytes())
        != expected_authority
    ):
        raise ValueError("owned runtime/save authority record mismatch")
    for name in ("before", "qualified"):
        marker = "Map successfully saved to '" + str(directory / (name + ".sav"))
        if ((directory / "stdout.log").read_text() + (directory / "stderr.log").read_text()).count(
            marker
        ) != 1:
            raise ValueError("unique native save completion marker required")
    manifest = PreparedWorldManifest(
        schema_version=1,
        source_digest=links.post_qualification_save_digest,
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
    # Restore only after replaying native query receipts, liveness, rollovers,
    # supplemental readbacks and unique same-stream native save completions.
    from app.simulation.openttd.freight_runtime_planning import _ISSUER, NativeSaveCorrespondence

    if links.evidence_kind != "owned-native-save-snapshots":
        raise ValueError("controlled save links cannot restore native correspondence")
    authority = NativeSaveCorrespondence(
        _ISSUER,
        world=world,
        original_digest=links.original_save_digest,
        final_digest=links.post_qualification_save_digest,
        configuration_digest=links.configuration_digest,
    )
    source = PreparedSourceCorrespondence(world, manifest, links, authority)
    policy = MonthlyBatchPolicy.model_validate_json(
        (directory / "planning-policy.json").read_bytes()
    )
    if policy.delivery_batch_limit != metadata["delivery_batch_limit"]:
        raise ValueError("planning policy differs from authorized prelaunch batch")
    road = generate_road_scenario(
        adapt_planning_facts(ValidatedPlanningFactInput(world, facts, source), policy)
    )
    if isinstance(road, NoRoadScenario):
        raise ValueError("retained qualified facts no longer produce the supplied candidates")
    scenario = PlanningScenario.model_validate_json(
        (directory / "planning-scenario.json").read_bytes()
    )
    plan = ExecutionPlan.model_validate_json((directory / "execution-plan.json").read_bytes())
    if scenario_hash(scenario) != scenario_hash(road.scenario) or plan_hash(plan) != plan_hash(
        optimize_candidate_network(road.scenario).plan
    ):
        raise ValueError("P08/P05 decision replay mismatch")
    service = compile_freight_service(road, plan)
    selection = service.selection_request(require_native=False)
    if (
        selection.a != native_plan.a
        or service.capacity != native_plan.f[5]
        or native_plan.source_save_digest != manifest.source_digest
    ):
        raise ValueError("native execution differs from P05 selection")
    from app.simulation.openttd.freight_delivery import DeliveryReadback

    admission = DeliveryReadback.parse_for(
        selection.admission_request, (directory / "inspect-1-response.json").read_bytes()
    )
    return service.validate_native_selection(native_plan, admission)
