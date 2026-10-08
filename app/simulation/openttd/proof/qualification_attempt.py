"""Qualification lifecycle and evidence; shared owner handles all process cleanup."""

from dataclasses import asdict, replace
from enum import Enum, auto
from types import SimpleNamespace

from app.simulation.openttd.qualification_session import ProductionQualificationSession
from app.simulation.openttd.qualification_stability import QualificationProfile

from .harness import write_json
from .qualification_contract import SESSION_ID
from .structural_attempt import retain_structural


class QualificationProofState(Enum):
    PREPARED = auto()
    LAUNCHED = auto()
    ADMIN_ACTIVE = auto()
    QUALIFICATION_SESSION_STARTED = auto()
    BASELINE_MONTH_OBSERVED = auto()
    FIRST_ROLLOVER_OBSERVED = auto()
    ANCHOR_COLLECTION_STARTED = auto()
    ANCHOR_COLLECTION_COMPLETED = auto()
    QUALIFIED_MONTH_ACTIVE = auto()
    SECOND_ROLLOVER_OBSERVED = auto()
    QUALIFIED_MONTH_COMPLETED = auto()
    FINAL_COLLECTION_STARTED = auto()
    FINAL_STRUCTURAL_COMPLETED = auto()
    STABILITY_VALIDATED = auto()
    FINAL_PRODUCTION_COMPLETED = auto()
    QUALIFICATION_VALIDATED = auto()
    QUALIFIED_OBSERVATION_ASSEMBLED = auto()
    CLEANUP_STARTED = auto()
    PROCESS_REAPED = auto()
    ENDPOINTS_CLOSED = auto()
    CREDENTIAL_REMOVED = auto()
    WORKSPACE_DISPOSED = auto()
    POSTRUN_INTEGRITY_VERIFIED = auto()
    COMPLETED = auto()
    FAILED = auto()


class QualificationLifecycle:
    def __init__(self):
        self.states = [QualificationProofState.PREPARED]

    def advance(self, state):
        # Same barrier algorithm, scoped typed sequence; cleanup can start on failure.
        order = list(QualificationProofState)
        current = self.states[-1]
        if current in (order[-2], order[-1]) or state is order[-1]:
            raise ValueError("Terminal qualification lifecycle; no resume")
        if state is QualificationProofState.CLEANUP_STARTED:
            if order.index(current) >= order.index(state):
                raise ValueError("Cleanup already started")
        elif order.index(state) != order.index(current) + 1 or (
            state is order[-2] and self.states != order[:-2]
        ):
            raise ValueError("Qualification lifecycle barrier not passed")
        self.states.append(state)

    def fail(self):
        if self.states[-1] is QualificationProofState.COMPLETED:
            self.states.pop()
        if self.states[-1] is not QualificationProofState.FAILED:
            self.states.append(QualificationProofState.FAILED)


EVENT_STATES = {
    "QUALIFICATION_SESSION_STARTED": "QUALIFICATION_SESSION_STARTED",
    "BASELINE_MONTH_OBSERVED": "BASELINE_MONTH_OBSERVED",
    "FIRST_ROLLOVER_OBSERVED": "FIRST_ROLLOVER_OBSERVED",
    "QUALIFICATION_ANCHOR_COLLECTION_STARTED": "ANCHOR_COLLECTION_STARTED",
    "QUALIFICATION_ANCHOR_COLLECTION_COMPLETED": "ANCHOR_COLLECTION_COMPLETED",
    "QUALIFIED_MONTH_STARTED": "QUALIFIED_MONTH_ACTIVE",
    "SECOND_ROLLOVER_OBSERVED": "SECOND_ROLLOVER_OBSERVED",
    "QUALIFIED_MONTH_COMPLETED": "QUALIFIED_MONTH_COMPLETED",
    "FINAL_COLLECTION_STARTED": "FINAL_COLLECTION_STARTED",
    "FINAL_STRUCTURAL_OBSERVED": "FINAL_STRUCTURAL_COMPLETED",
    "LIFETIME_STABILITY_VALIDATED": "STABILITY_VALIDATED",
    "FINAL_PRODUCTION_COLLECTION_COMPLETED": "FINAL_PRODUCTION_COMPLETED",
    "PRODUCTION_QUALIFICATION_VALIDATED": "QUALIFICATION_VALIDATED",
    "QUALIFIED_PRODUCTION_OBSERVATION_ASSEMBLED": "QUALIFIED_OBSERVATION_ASSEMBLED",
}


class _Events(list):
    def __init__(self, lifecycle):
        super().__init__()
        self.lifecycle = lifecycle

    def append(self, event):
        if event in EVENT_STATES:
            self.lifecycle.advance(QualificationProofState[EVENT_STATES[event]])
        super().append(event)

    def extend(self, events):
        for event in events:
            self.append(event)


class QualificationRunner:
    def __init__(self, prepared, backend):
        self.prepared, self.backend = prepared, backend
        self.lifecycle = QualificationLifecycle()
        self.coordinator = None

    def launch_boundary(self):
        self.backend.validate_launch(self.prepared)
        if self.backend.accounting.total_frames or self.backend.accounting.failed:
            raise ValueError("Fresh shared qualification accounting required")
        return dict(
            qualification_runner_loaded=True,
            accounting_wired=True,
            launch_boundary_reached=True,
            max_query_operations=9088,
            max_total_post_auth_frames=9094,
        )

    async def collect(self):
        b = self.backend
        context = b.transport.context

        def current_context():
            if (
                b.process is not context.process_identity
                or b.session is not b.secure_connection
                or b.structural_session.session is not b.secure_connection
            ):
                raise ValueError("Qualification process/connection replaced")
            return b.transport.context

        self.coordinator = ProductionQualificationSession(
            b.transport,
            context,
            b.accounting,
            QualificationProfile(True, True, True, True),
            session_id=SESSION_ID,
            context_provider=current_context,
        )
        b.qualification_coordinator = self.coordinator
        self.coordinator._events = _Events(self.lifecycle)

        async def evidence(request, exchange):
            return await b.evidence(self.prepared, request, exchange)

        result = await self.coordinator.collect(evidence, evidence, evidence, evidence, evidence)
        replace(result)
        return result

    def semantic_complete(self):
        if self.coordinator is None or self.coordinator.result is None:
            return False
        replace(self.coordinator.result)
        return True


def _public_evidence(value):
    if isinstance(value, dict):
        return {k: _public_evidence(v) for k, v in value.items() if k != "raw_log"}
    if isinstance(value, (list, tuple)):
        return [_public_evidence(v) for v in value]
    if isinstance(value, bytes):
        return value.decode("ascii", errors="backslashreplace")
    if isinstance(value, Enum):
        return value.name
    return value


def retain_qualification(attempt, runner, backend, successful):
    c = runner.coordinator
    final_child = None if c is None else c.final_session
    retain_structural(
        attempt,
        SimpleNamespace(coordinator=final_child),
        backend,
        final_child is not None and final_child.observation is not None,
    )
    for prefix, child in (
        ("anchor", None if c is None else c.anchor_session),
        ("final", None if c is None else c.final_session),
    ):
        directory = attempt / prefix
        directory.mkdir(exist_ok=True)
        retain_structural(
            directory,
            SimpleNamespace(coordinator=child),
            backend,
            child is not None and child.observation is not None,
        )
    evidence = None if c is None or c.production_session is None else c.production_session.evidence
    production = None if c is None else c.production
    write_json(
        attempt / "qualification-session.json",
        dict(
            complete=successful,
            qualified_for_planning=successful,
            lifecycle=[s.name for s in runner.lifecycle.states],
            final_acceptance_pending=True,
            semantic_evidence=None if c is None else _public_evidence(asdict(c.evidence)),
            clock=None
            if c is None
            else dict(
                state=c.clock.state.name,
                samples=[asdict(v) for v in c.clock.boundaries],
                polls=c.clock.polls,
            ),
            targets_anchor=None if c is None else c.anchor_targets,
            targets_final=None if c is None else c.final_targets,
            lifetimes_anchor=[] if c is None else [asdict(v) for v in c.anchor_lifetimes],
            lifetimes_final=[] if c is None else [asdict(v) for v in c.final_lifetimes],
        ),
    )
    write_json(
        attempt / "production-session.json",
        dict(
            complete=successful,
            qualified_for_planning=successful,
            events=[] if evidence is None else evidence.events,
            failure=None if evidence is None else evidence.failure,
        ),
    )
    write_json(
        attempt / "production-observation.json",
        dict(
            complete=successful,
            qualified_for_planning=successful,
            source_structural_world_digest=None
            if c is None or c.final is None
            else c.final.structural_world_digest,
            records=[]
            if evidence is None
            else [asdict(t.exchange.response.record) for t in evidence.transactions],
            production_digest=None
            if production is None or not successful
            else production.production_digest,
        ),
    )
    if successful:
        assert production is not None and c is not None and c.result is not None
        (attempt / "production-canonical.json").write_bytes(production.to_bytes())
        identity = c.result.qualified_month_identity
        write_json(
            attempt / "qualified-month.json",
            dict(
                economy_year=identity.economy_year,
                economy_month=identity.economy_month,
                boundary_start=asdict(identity.boundary_start),
                boundary_end=asdict(identity.boundary_end),
                runtime=str(identity.lineage.world.runtime_identity),
                configuration_digest=identity.lineage.configuration_digest,
                bridge_digest=identity.lineage.bridge.sha256,
            ),
        )


async def execute_qualification_attempt(prepared, backend):
    from .raw_production_attempt import execute_raw_production_attempt

    return await execute_raw_production_attempt(prepared, backend, qualification=True)
