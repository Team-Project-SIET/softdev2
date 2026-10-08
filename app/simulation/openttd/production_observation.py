"""Immutable PRE-DECISION dynamic observations, separate from structural semantics."""

import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from enum import Enum

from app.simulation.openttd.industry_cargo import MAX_INDUSTRY_CARGOES
from app.simulation.openttd.industry_production import (
    MAX_PRODUCTION_RESPONSE_BYTES,
    IndustryProductionRecord,
)
from app.simulation.openttd.industry_production_evidence import ProductionTransaction
from app.simulation.openttd.observation_protocol import BridgeProtocolError
from app.simulation.openttd.structural_world import (
    StructuralWorldContext,
    StructuralWorldObservation,
)

MAX_PRODUCTION_PAIRS = 32 * MAX_INDUSTRY_CARGOES  # Verified native16 output slots.
MAX_PRODUCTION_BYTES = MAX_PRODUCTION_PAIRS * MAX_PRODUCTION_RESPONSE_BYTES


@dataclass(frozen=True)
class EconomyMonth:
    """Read-only owner-supplied GSDate year/month and GetDate boundary readings.

    No calendar is guessed here. Native integration must supply these boundaries
    from the frozen economy clock. Controlled fixtures explicitly supply readings.
    """

    year: int
    month: int
    start_date: int
    end_date: int  # Exclusive next month's start.

    def __post_init__(self):
        if (
            type(self.year) is not int
            or not 0 <= self.year <= 5000000
            or type(self.month) is not int
            or not 1 <= self.month <= 12
            or type(self.start_date) is not int
            or type(self.end_date) is not int
            or not 0 <= self.start_date < self.end_date <= 2147483647
            or not 28 <= self.end_date - self.start_date <= 31
        ):
            raise ValueError("invalid economy-month reading")

    def contains(self, record: IndustryProductionRecord) -> bool:
        return (
            self.start_date
            <= record.economy_date_before
            <= record.economy_date_after
            < self.end_date
        )


class ProductionQualificationStatus(Enum):
    UNQUALIFIED_INITIAL = "unqualified_initial"
    UNQUALIFIED_AFTER_FIRST_ROLLOVER = "unqualified_after_first_rollover"
    QUALIFIED_AFTER_SECOND_ROLLOVER = "qualified_after_second_rollover"


@dataclass(frozen=True)
class ProductionWindowQualification:
    source_structural_world_digest: str
    context: StructuralWorldContext
    observed_months: tuple[EconomyMonth, ...]

    def __post_init__(self):
        if not isinstance(self.context, StructuralWorldContext) or not re.fullmatch(
            r"[0-9a-f]{64}", self.source_structural_world_digest
        ):
            raise ValueError("typed same-run structural provenance required")
        if type(self.observed_months) is not tuple or not 1 <= len(self.observed_months) <= 3:
            raise ValueError("qualification retains initial and at most two observed boundaries")
        for m in self.observed_months:
            if not isinstance(m, EconomyMonth):
                raise ValueError("typed economy month required")
        for previous, current in zip(self.observed_months, self.observed_months[1:]):
            if (
                current.year * 12 + current.month != previous.year * 12 + previous.month + 1
                or previous.end_date != current.start_date
            ):
                raise ValueError("adjacent economy rollovers required; skipped/backward clock")

    @classmethod
    def initial(cls, source: StructuralWorldObservation, month: EconomyMonth):
        if not source.complete:
            raise BridgeProtocolError("complete structural source required")
        return cls(source.structural_world_digest, source.inventory.context, (month,))

    @property
    def rollover_count(self):
        return len(self.observed_months) - 1

    @property
    def status(self):
        return tuple(ProductionQualificationStatus)[self.rollover_count]

    @property
    def qualified(self):
        return self.status is ProductionQualificationStatus.QUALIFIED_AFTER_SECOND_ROLLOVER

    @property
    def current_month(self):
        return self.observed_months[-1]

    @property
    def measured_month(self):
        return self.observed_months[-2] if self.qualified else None

    def observe(self, month: EconomyMonth, context: StructuralWorldContext):
        self.context.require_same_run(context)
        if month == self.current_month:
            return self  # Duplicate observations are not another rollover.
        if self.qualified:
            raise BridgeProtocolError(
                "qualified window sealed; start a fresh window for later months"
            )
        return replace(self, observed_months=(*self.observed_months, month))

    def semantic_data(self):
        return dict(
            status=self.status.value,
            rollover_count=self.rollover_count,
            observed_months=[asdict(m) for m in self.observed_months],
        )


@dataclass(frozen=True)
class ProductionBudget:
    max_requests: int = MAX_PRODUCTION_PAIRS
    max_response_bytes: int = MAX_PRODUCTION_BYTES
    max_operations: int = 4096  # Controlled allowance512*8; NOT a native total-frame contract.

    def __post_init__(self):
        for v, maximum in (
            (self.max_requests, MAX_PRODUCTION_PAIRS),
            (self.max_response_bytes, MAX_PRODUCTION_BYTES),
            (self.max_operations, 4096),
        ):
            if type(v) is not int or not 1 <= v <= maximum:
                raise ValueError("invalid controlled production budget")

    def require(self, requests: int, response_bytes: int, operations: int):
        if any(type(v) is not int or v < 0 for v in (requests, response_bytes, operations)) or (
            requests > self.max_requests
            or response_bytes > self.max_response_bytes
            or operations > self.max_operations
        ):
            raise BridgeProtocolError("production budget exhausted")


def production_pairs(source: StructuralWorldObservation):
    replace(source)  # Revalidate complete immutable structural provenance.
    caps = source.capability.observation.capabilities
    if len(caps) > 32 or any(len(c.produces) > MAX_INDUSTRY_CARGOES for c in caps):
        raise BridgeProtocolError("production source pair bounds exceeded")
    catalog = set(source.ordered_cargo_ids)
    pairs = tuple((c.industry_id, cargo) for c in caps for cargo in c.produces)
    if len(pairs) > MAX_PRODUCTION_PAIRS or any(c not in catalog for _, c in pairs):
        raise BridgeProtocolError("production reference outside source catalog")
    return pairs


@dataclass(frozen=True)
class IndustryProductionObservation:
    source: StructuralWorldObservation
    context: StructuralWorldContext
    qualification: ProductionWindowQualification
    records: tuple[IndustryProductionRecord, ...]
    total_response_bytes: int
    protocol_operations: int
    transactions: tuple[ProductionTransaction, ...]
    budget: ProductionBudget = ProductionBudget()

    def __post_init__(self):
        self.source.inventory.context.require_same_run(self.context)
        self.context.require_same_run(self.qualification.context)
        if self.qualification.source_structural_world_digest != self.source.structural_world_digest:
            raise BridgeProtocolError("production source structural digest mismatch")
        if type(self.records) is not tuple or any(
            not isinstance(r, IndustryProductionRecord) for r in self.records
        ):
            raise BridgeProtocolError("immutable typed production records required")
        if type(self.transactions) is not tuple or len(self.transactions) != len(self.records):
            raise BridgeProtocolError("production transaction coverage missing")
        for transaction in self.transactions:
            if not isinstance(transaction, ProductionTransaction):
                raise BridgeProtocolError("typed production transaction required")
            transaction.validate()
        if sorted(
            (t.exchange.response.record for t in self.transactions), key=lambda r: r.pair
        ) != list(self.records):
            raise BridgeProtocolError("production records do not match validated transactions")
        if self.total_response_bytes != sum(
            len(t.exchange.response_payload) for t in self.transactions
        ) or self.protocol_operations != sum(
            t.exchange.protocol_operations for t in self.transactions
        ):
            raise BridgeProtocolError("production accounting mismatch")
        pairs = tuple(r.pair for r in self.records)
        if pairs != production_pairs(self.source):
            raise BridgeProtocolError(
                "missing/extra/duplicate/noncanonical production pair coverage"
            )
        if any(not self.qualification.current_month.contains(r) for r in self.records):
            raise BridgeProtocolError("mixed/changed economy window")
        self.budget.require(len(self.records), self.total_response_bytes, self.protocol_operations)
        if self.protocol_operations < 4 * len(self.records) or self.total_response_bytes < len(
            self.records
        ):
            raise BridgeProtocolError("missing production accounting")

    @property
    def source_structural_world_digest(self):
        return self.source.structural_world_digest

    @property
    def complete(self):
        return True  # Partial session retains evidence, never assembles complete observation.

    @property
    def qualified_for_planning(self):
        return self.complete and self.qualification.qualified

    @property
    def runtime_identity(self):
        return self.context.world.runtime_identity

    def to_bytes(self):
        # Date brackets are capture context. The coherent month is semantic authority.
        records = [
            {k: v for k, v in asdict(r).items() if not k.startswith("economy_date_")}
            for r in self.records
        ]
        return json.dumps(
            dict(
                schema="industry-production-v1",
                purpose="pre-decision",
                source_structural_world_digest=self.source_structural_world_digest,
                qualification=self.qualification.semantic_data(),
                records=records,
            ),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()

    @property
    def production_digest(self):
        return hashlib.sha256(self.to_bytes()).hexdigest()
