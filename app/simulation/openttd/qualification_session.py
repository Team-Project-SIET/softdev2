"""Single-use Python qualification owner; no launch/connect/planning APIs."""

import asyncio
import time
from dataclasses import dataclass, replace
from enum import Enum

from app.simulation.openttd.gamescript_protocol import BridgeProtocolError, validate_request_id
from app.simulation.openttd.gamescript_transport import GameScriptTransport
from app.simulation.openttd.production_observation import (
    ProductionWindowQualification,
    production_pairs,
)
from app.simulation.openttd.production_session import (
    IndustryProductionSession,
    ProductionDecisionBoundary,
    ProductionSessionEvidence,
)
from app.simulation.openttd.proof.qualification_accounting import QualificationFrameBudget
from app.simulation.openttd.qualification_clock import (
    EconomyClockReading,
    EconomyClockRequest,
    IndustryLifetimeReading,
    IndustryLifetimeRequest,
)
from app.simulation.openttd.qualification_evidence import NativeReadTransaction
from app.simulation.openttd.qualification_policy import (
    MAX_APPLICATION_REQUESTS,
    MAX_QUERY_OPERATIONS,
    MAX_RESPONSE_BYTES,
    PHASE_BOUNDS,
    QualificationPollPolicy,
)
from app.simulation.openttd.qualification_stability import (
    QualificationProfile,
    QualifiedProductionVerification,
    TargetStability,
)
from app.simulation.openttd.qualification_state import NativeRolloverEvidence
from app.simulation.openttd.structural_world_session import (
    StructuralWorldSession,
    StructuralWorldSessionEvidence,
)


class QualificationPhase(Enum):
    PREPARED = "prepared"
    BASELINE = "baseline"
    FIRST_POLL = "first_poll"
    ANCHOR_STRUCTURAL = "anchor_structural"
    ANCHOR_LIFETIME = "anchor_lifetime"
    SECOND_POLL = "second_poll"
    FINAL_STRUCTURAL = "final_structural"
    FINAL_LIFETIME = "final_lifetime"
    FINAL_PRODUCTION = "final_production"
    QUALIFIED = "qualified"
    COMPLETED = "completed"
    FAILED = "failed"


class QualificationTransport(GameScriptTransport):
    """Same proven query/barrier machinery, independently bounded by the owner."""

    MAX_REQUESTS = MAX_APPLICATION_REQUESTS
    MAX_PRODUCTION_SESSION_REQUESTS = MAX_APPLICATION_REQUESTS


@dataclass(frozen=True)
class QualificationSessionEvidence:
    phase: QualificationPhase
    events: tuple[str, ...]
    native_transactions: tuple[NativeReadTransaction, ...]
    phase_usage: tuple[tuple[str, tuple[int, int, int]], ...]
    accounting_frames: tuple[tuple[str, int, str], ...]
    failure: str | None
    anchor: StructuralWorldSessionEvidence | None = None
    final: StructuralWorldSessionEvidence | None = None
    production: ProductionSessionEvidence | None = None
    partial_response: bytes | None = None
    retries: int = 0
    reconnects: int = 0

    @property
    def complete(self):
        return self.phase is QualificationPhase.COMPLETED and self.failure is None


QUALIFICATION_SEQUENCE = (
    "QUALIFICATION_SESSION_STARTED",
    "BASELINE_MONTH_OBSERVED",
    "FIRST_ROLLOVER_OBSERVED",
    "QUALIFICATION_ANCHOR_COLLECTION_STARTED",
    "QUALIFICATION_ANCHOR_COLLECTION_COMPLETED",
    "QUALIFIED_MONTH_STARTED",
    "SECOND_ROLLOVER_OBSERVED",
    "QUALIFIED_MONTH_COMPLETED",
    "FINAL_COLLECTION_STARTED",
    "FINAL_STRUCTURAL_OBSERVED",
    "TARGET_STABILITY_VALIDATED",
    "LIFETIME_STABILITY_VALIDATED",
    "FINAL_PRODUCTION_COLLECTION_STARTED",
    "FINAL_PRODUCTION_COLLECTION_COMPLETED",
    "PRODUCTION_QUALIFICATION_VALIDATED",
    "QUALIFIED_PRODUCTION_OBSERVATION_ASSEMBLED",
    "QUALIFICATION_SESSION_COMPLETED",
)


@dataclass(frozen=True)
class QualifiedProductionResult:
    verification: QualifiedProductionVerification
    evidence: QualificationSessionEvidence
    clock: NativeRolloverEvidence

    def __post_init__(self):
        replace(self.verification)
        if (
            not self.evidence.complete
            or tuple(e for e in self.evidence.events if e in QUALIFICATION_SEQUENCE)
            != QUALIFICATION_SEQUENCE
        ):
            raise BridgeProtocolError("complete local qualification semantic progression required")
        anchor, final, production = (
            self.evidence.anchor,
            self.evidence.final,
            self.evidence.production,
        )
        if anchor is None or final is None or production is None:
            raise BridgeProtocolError("complete component evidence required")
        for component in (anchor, final, production):
            if component is None or not component.complete or component.failure is not None:
                raise BridgeProtocolError(
                    "complete structural and production component evidence required"
                )
        if (
            anchor.structural_world_digest
            != self.verification.stability.anchor.structural_world_digest
            or final.structural_world_digest != self.production.source_structural_world_digest
        ):
            raise BridgeProtocolError("component evidence structural digest mismatch")
        if production.transactions != self.production.transactions:
            raise BridgeProtocolError("fresh final production evidence mismatch")
        usage = dict(self.evidence.phase_usage)
        if tuple(usage) != tuple(PHASE_BOUNDS) or len(self.evidence.phase_usage) != len(
            PHASE_BOUNDS
        ):
            raise BridgeProtocolError("exact phase accounting categories required")
        for category, values in usage.items():
            if (
                type(values) is not tuple
                or len(values) != 3
                or any(
                    type(v) is not int or not 0 <= v <= cap
                    for v, cap in zip(values, PHASE_BOUNDS[category])
                )
            ):
                raise BridgeProtocolError("qualified result phase budget invalid")
        native_exchanges = tuple(t.exchange for t in self.evidence.native_transactions)
        exchanges = (
            *anchor.exchanges,
            *final.exchanges,
            *production.exchanges,
            *native_exchanges,
        )
        if tuple(sum(v[i] for v in usage.values()) for i in range(3)) != (
            len(exchanges),
            sum(len(e.response_payload) for e in exchanges),
            sum(e.protocol_operations for e in exchanges),
        ):
            raise BridgeProtocolError("qualified result transaction accounting mismatch")
        if len(self.evidence.accounting_frames) != 5 + sum(v[2] for v in usage.values()):
            raise BridgeProtocolError("qualified result native frame/receipt accounting mismatch")
        for lifetimes, component in (
            (self.verification.stability.anchor_lifetimes, anchor),
            (self.verification.stability.final_lifetimes, final),
        ):
            actual = tuple(
                t.exchange.response.reading
                for t in self.evidence.native_transactions
                if t.exchange.request.request_id.startswith(component.session_id + "-life-")
            )
            if actual != lifetimes:
                raise BridgeProtocolError("qualified lifetime identity lacks native evidence")
        reconstructed = NativeRolloverEvidence(self.clock.context, max_polls=self.clock.max_polls)
        for transaction in self.evidence.native_transactions:
            transaction.validate()
            sample = transaction.exchange.response.reading
            if isinstance(sample, EconomyClockReading):
                reconstructed = reconstructed.observe(sample, self.clock.context)
        if (
            reconstructed != self.clock
            or self.clock.boundaries != self.verification.stability.clock.boundaries
        ):
            raise BridgeProtocolError("native rollover evidence/qualification boundary mismatch")
        self.clock.context.require_same_run(self.verification.production.context)

    @property
    def production(self):
        return self.verification.production

    @property
    def qualified_month(self):
        return self.verification.qualified_month

    @property
    def qualified_month_identity(self):
        return self.verification.qualified_month_identity


class _QualificationQueries:
    """Enforce phase-local budgets before each write, reconcile secure frames after."""

    def __init__(self, owner):
        self.owner = owner

    @property
    def session(self):
        return self.owner.transport.session

    @property
    def context(self):
        return self.owner.context_provider()

    async def industry_page(self, request, world, **kwargs):
        return await self.owner._query("industry_page", request, world, **kwargs)

    async def industry_cargo(self, request, **kwargs):
        return await self.owner._query("industry_cargo", request, **kwargs)

    async def cargo_page(self, request, **kwargs):
        return await self.owner._query("cargo_page", request, **kwargs)

    async def industry_production(self, request, **kwargs):
        return await self.owner._query("industry_production", request, **kwargs)


class ProductionQualificationSession:
    def __init__(
        self,
        transport: QualificationTransport,
        context,
        accounting: QualificationFrameBudget,
        profile: QualificationProfile,
        *,
        session_id="openttd15-qualification-001",
        policy=QualificationPollPolicy(),
        timeout=5.0,
        context_provider=None,
        pace=asyncio.sleep,
        monotonic=time.monotonic,
        decision=None,
    ):
        validate_request_id(session_id + "-final-cat-p32")
        if (
            not isinstance(accounting, QualificationFrameBudget)
            or not isinstance(profile, QualificationProfile)
            or not isinstance(policy, QualificationPollPolicy)
        ):
            raise ValueError("typed qualification contract required")
        if type(timeout) not in (int, float) or not 0 < timeout <= 5:
            raise ValueError("bounded per-query timeout required")
        self.transport, self.context, self.accounting, self.profile = (
            transport,
            context,
            accounting,
            profile,
        )
        self._owned_transport, self._owned_accounting = transport, accounting
        self.session_id, self.policy, self.timeout = session_id, policy, timeout
        self.context_provider = context_provider or (lambda: context)
        self.pace, self.monotonic = pace, monotonic
        self.decision = decision or ProductionDecisionBoundary()
        self.phase = QualificationPhase.PREPARED
        self.clock = NativeRolloverEvidence(context, max_polls=policy.max_clock_requests)
        self.anchor = self.final = self.production = self.result = None
        self.anchor_session = self.final_session = self.production_session = None
        self._anchor_targets = self._final_targets = None
        self.anchor_lifetimes = self.final_lifetimes = ()
        self._started = False
        self._failure = None
        self._events = []
        self._native = []
        self._usage = dict.fromkeys(PHASE_BOUNDS, (0, 0, 0))
        self._wait_polls = 0
        self._deadline: float | None = None
        self._cursor = accounting.snapshot()
        self._queries = _QualificationQueries(self)

    @property
    def anchor_targets(self):
        return self._anchor_targets

    @property
    def final_targets(self):
        return self._final_targets

    @property
    def evidence(self):
        snapshot = self.accounting.snapshot()
        return QualificationSessionEvidence(
            self.phase,
            tuple(self._events),
            tuple(self._native),
            tuple(self._usage.items()),
            tuple((r["direction"], r["packet_type"], r["sha256"]) for r in snapshot["frames"]),
            self._failure,
            self.anchor_session.evidence if self.anchor_session is not None else None,
            self.final_session.evidence if self.final_session is not None else None,
            self.production_session.evidence if self.production_session is not None else None,
            self.transport.response_payload,
        )

    def _check(self):
        if (
            self.transport is not self._owned_transport
            or self.accounting is not self._owned_accounting
        ):
            raise BridgeProtocolError("qualification transport/accounting replacement prohibited")
        self.context.require_same_run(self.context_provider())
        if (
            self.transport.session is not self.context.connection_identity
            or getattr(self.transport.session, "_frame_observer", None) != self.accounting.observe
        ):
            raise BridgeProtocolError(
                "one continuous stream and shared secure frame observer required"
            )
        self.decision.require_pre_decision()
        if self.accounting.failed or self.accounting.phase == "cleanup":
            raise BridgeProtocolError("frame accounting failed/closed; no resume")
        if self._deadline is not None and self.monotonic() >= self._deadline:
            raise TimeoutError("qualification operational deadline exhausted")
        current = self.accounting.snapshot()
        if (
            any(current["categories"][k] < v for k, v in self._cursor["categories"].items())
            or current["frames"][: len(self._cursor["frames"])] != self._cursor["frames"]
        ):
            raise BridgeProtocolError("shared accounting reset/replacement detected")
        if current["query_operations"] != sum(v[2] for v in self._usage.values()):
            raise BridgeProtocolError("secure frame/query receipt accounting mismatch")
        self._cursor = current

    def _category(self, command):
        if command not in (
            "economy_clock",
            "industry_lifetime",
            "industry_page",
            "industry_cargo",
            "cargo_page",
            "industry_production",
        ) or self.phase in (
            QualificationPhase.PREPARED,
            QualificationPhase.QUALIFIED,
            QualificationPhase.COMPLETED,
            QualificationPhase.FAILED,
        ):
            raise BridgeProtocolError("query outside active qualification contract")
        if command == "economy_clock":
            return "clock"
        if command == "industry_lifetime":
            if self.phase not in (
                QualificationPhase.ANCHOR_LIFETIME,
                QualificationPhase.FINAL_LIFETIME,
            ):
                raise BridgeProtocolError("lifetime query before structural target finalization")
            return self.phase.value
        if command == "industry_production":
            if self.phase is not QualificationPhase.FINAL_PRODUCTION:
                raise BridgeProtocolError("production before second rollover/final structure")
            return "production"
        if self.phase not in (
            QualificationPhase.ANCHOR_STRUCTURAL,
            QualificationPhase.FINAL_STRUCTURAL,
        ):
            raise BridgeProtocolError("structural query before required rollover")
        return self.phase.value

    def _bounded_evidence(self, callback):
        async def bounded(*args):
            self._check()
            if self._deadline is None:
                raise BridgeProtocolError("qualification session has not started")
            async with asyncio.timeout(min(self.timeout, self._deadline - self.monotonic())):
                result = await callback(*args)
            self._check()
            return result

        return bounded

    async def _query(self, command, request, *args, **kwargs):
        self._check()
        category = self._category(command)
        limit = PHASE_BOUNDS[category]
        used = self._usage[category]
        requests_limit = self.policy.max_clock_requests if category == "clock" else limit[0]
        if used[0] >= requests_limit:
            raise BridgeProtocolError("qualification phase request budget exhausted")
        allowance = 16 if command == "cargo_page" else 8
        remaining = min(
            limit[2] - used[2], MAX_QUERY_OPERATIONS - sum(v[2] for v in self._usage.values())
        )
        if remaining < 4 or sum(v[0] for v in self._usage.values()) >= MAX_APPLICATION_REQUESTS:
            raise BridgeProtocolError("qualification application/query budget exhausted")
        self.accounting.enter(category)
        # Count attempted applications before I/O; failure never resends.
        self._usage[category] = (used[0] + 1, used[1], used[2])
        if self._deadline is None:
            raise BridgeProtocolError("qualification session has not started")
        kwargs["timeout"] = min(
            kwargs.get("timeout", self.timeout), self.timeout, self._deadline - self.monotonic()
        )
        kwargs["operation_budget"] = min(
            kwargs.get("operation_budget") or allowance, allowance, remaining
        )
        exchange = await getattr(self.transport, command)(request, *args, **kwargs)
        size = len(exchange.response_payload)
        self._usage[category] = (
            used[0] + 1,
            used[1] + size,
            used[2] + exchange.protocol_operations,
        )
        if (
            self._usage[category][1] > limit[1]
            or sum(v[1] for v in self._usage.values()) > MAX_RESPONSE_BYTES
        ):
            raise BridgeProtocolError("qualification response-byte budget exhausted")
        if (
            category in ("clock", "anchor_lifetime", "final_lifetime")
            and size > limit[1] // limit[0]
        ):
            raise BridgeProtocolError("native read frozen payload bound exceeded")
        self._check()
        return exchange

    async def _native_read(self, request, evidence_for):
        exchange = await self._query(request.command, request)
        transaction = NativeReadTransaction(exchange, await evidence_for(request, exchange))
        transaction.validate()
        self._native.append(transaction)
        self._events.extend(exchange.network_sequence)
        self._check()
        return exchange.response.reading

    async def _clock_read(self, evidence_for, expected=None):
        request = EconomyClockRequest(f"{self.session_id}-clock-{self.clock.polls + 1}")
        sample = await self._native_read(request, evidence_for)
        if not isinstance(sample, EconomyClockReading):
            raise BridgeProtocolError("typed economy clock required")
        if expected is not None and sample.month != expected:
            raise BridgeProtocolError("collection crossed required economy month")
        self.clock = self.clock.observe(sample, self.context_provider())
        return sample

    async def _wait_rollover(self, count, evidence_for):
        while len(self.clock.boundaries) < count + 1:
            self._check()
            if self._wait_polls >= self.policy.max_wait_polls:
                raise BridgeProtocolError("paced clock poll budget exhausted")
            await self.pace(self.policy.interval)
            self._wait_polls += 1
            self._check()
            await self._clock_read(evidence_for)

    async def _lifetimes(self, source, evidence_for, prefix):
        readings = []
        for industry_id in sorted({i for i, _ in production_pairs(source)}):
            request = IndustryLifetimeRequest(
                f"{self.session_id}-{prefix}-life-{industry_id}", industry_id
            )
            reading = await self._native_read(request, evidence_for)
            if not isinstance(reading, IndustryLifetimeReading):
                raise BridgeProtocolError("typed calendar lifetime identity required")
            readings.append(reading)
        return tuple(readings)

    async def collect(
        self,
        inventory_evidence,
        capability_evidence,
        catalog_evidence,
        production_evidence,
        native_evidence,
    ):
        if self._started:
            raise BridgeProtocolError("qualification coordinator single-use; no restart/resume")
        self._started = True
        self._deadline = self.monotonic() + self.policy.timeout
        self._events.append("QUALIFICATION_SESSION_STARTED")
        inventory_evidence = self._bounded_evidence(inventory_evidence)
        capability_evidence = self._bounded_evidence(capability_evidence)
        catalog_evidence = self._bounded_evidence(catalog_evidence)
        production_evidence = self._bounded_evidence(production_evidence)
        native_evidence = self._bounded_evidence(native_evidence)
        try:
            async with asyncio.timeout(self.policy.timeout):
                self._check()
                if not self.transport.registered or self.accounting.total_frames != 5:
                    raise BridgeProtocolError(
                        "one explicit secure establishment/subscription required"
                    )
                self.phase = QualificationPhase.BASELINE
                await self._clock_read(native_evidence)
                self._events.append("BASELINE_MONTH_OBSERVED")
                self.phase = QualificationPhase.FIRST_POLL
                await self._wait_rollover(1, native_evidence)
                self._events.append("FIRST_ROLLOVER_OBSERVED")
                m1 = self.clock.boundaries[1].month
                await self._clock_read(native_evidence, m1)
                self.phase = QualificationPhase.ANCHOR_STRUCTURAL
                self._events.append("QUALIFICATION_ANCHOR_COLLECTION_STARTED")
                self.anchor_session = StructuralWorldSession(
                    self.context, session_id=self.session_id + "-anchor", timeout=self.timeout
                )
                self.anchor = await self.anchor_session.collect(
                    self._queries, inventory_evidence, capability_evidence, catalog_evidence
                )
                self.anchor.structural_world_digest
                self._anchor_targets = production_pairs(self.anchor)
                self.phase = QualificationPhase.ANCHOR_LIFETIME
                self.anchor_lifetimes = await self._lifetimes(
                    self.anchor, native_evidence, "anchor"
                )
                await self._clock_read(native_evidence, m1)
                self._events.extend(
                    ("QUALIFICATION_ANCHOR_COLLECTION_COMPLETED", "QUALIFIED_MONTH_STARTED")
                )
                self.phase = QualificationPhase.SECOND_POLL
                await self._wait_rollover(2, native_evidence)
                self._events.extend(("SECOND_ROLLOVER_OBSERVED", "QUALIFIED_MONTH_COMPLETED"))
                m2 = self.clock.boundaries[2].month
                await self._clock_read(native_evidence, m2)
                self.phase = QualificationPhase.FINAL_STRUCTURAL
                self._events.append("FINAL_COLLECTION_STARTED")
                self.final_session = StructuralWorldSession(
                    self.context, session_id=self.session_id + "-final", timeout=self.timeout
                )
                self.final = await self.final_session.collect(
                    self._queries, inventory_evidence, capability_evidence, catalog_evidence
                )
                self.final.structural_world_digest
                self._events.append("FINAL_STRUCTURAL_OBSERVED")
                self._final_targets = production_pairs(self.final)
                self.phase = QualificationPhase.FINAL_LIFETIME
                self.final_lifetimes = await self._lifetimes(self.final, native_evidence, "final")
                stability = TargetStability(
                    self.profile,
                    self.clock,
                    self.anchor,
                    self.final,
                    self.anchor_lifetimes,
                    self.final_lifetimes,
                )
                self._events.extend(("TARGET_STABILITY_VALIDATED", "LIFETIME_STABILITY_VALIDATED"))
                self.phase = QualificationPhase.FINAL_PRODUCTION
                self._events.append("FINAL_PRODUCTION_COLLECTION_STARTED")
                window = ProductionWindowQualification(
                    self.final.structural_world_digest,
                    self.context,
                    tuple(v.month for v in self.clock.boundaries),
                )
                self.production_session = IndustryProductionSession(
                    self._queries,
                    self.final,
                    self.context,
                    ProductionWindowQualification.initial(self.final, m2),
                    session_id=self.session_id + "-prod",
                    timeout=self.timeout,
                    context_provider=self.context_provider,
                    decision=self.decision,
                )
                fresh = await self.production_session.collect(production_evidence)
                self._events.append("FINAL_PRODUCTION_COLLECTION_COMPLETED")
                await self._clock_read(native_evidence, m2)
                self._check()
                # Only now publish a qualified observation; failed final guards retain
                # transactions without admitting a qualified result.
                result = QualifiedProductionVerification(
                    stability, replace(fresh, qualification=window)
                )
                self.phase = QualificationPhase.QUALIFIED
                self._events.extend(
                    (
                        "PRODUCTION_QUALIFICATION_VALIDATED",
                        "QUALIFIED_PRODUCTION_OBSERVATION_ASSEMBLED",
                    )
                )
                self.production = result.production
                self.phase = QualificationPhase.COMPLETED
                self._events.append("QUALIFICATION_SESSION_COMPLETED")
                self.result = QualifiedProductionResult(result, self.evidence, self.clock)
                return self.result
        except BaseException as error:
            self.phase = QualificationPhase.FAILED
            self.clock = self.clock.fail(f"{type(error).__name__}: {error}")
            self._failure = self.clock.failure
            self.production = self.result = None
            self._events.append("QUALIFICATION_SESSION_FAILED")
            try:
                async with asyncio.timeout(self.timeout):
                    await self.transport.session.close()
            except BaseException as cleanup:
                self._failure += f"; Admin close failed: {cleanup}"
            raise
