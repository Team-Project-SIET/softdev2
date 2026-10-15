"""Immutable observation types and validation; no execution dependencies."""

from dataclasses import dataclass, replace
from enum import Enum

from app.simulation.openttd.observation_protocol import BridgeProtocolError
from app.simulation.openttd.observation_session_evidence import (
    ProductionSessionEvidence,
    StructuralWorldSessionEvidence,
)
from app.simulation.openttd.qualification_clock import EconomyClockReading
from app.simulation.openttd.qualification_evidence import NativeReadTransaction
from app.simulation.openttd.qualification_policy import PHASE_BOUNDS
from app.simulation.openttd.qualification_stability import QualifiedProductionVerification
from app.simulation.openttd.qualification_state import NativeRolloverEvidence


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
