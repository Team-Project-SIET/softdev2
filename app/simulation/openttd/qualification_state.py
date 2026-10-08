"""Immutable native rollover evidence. Collection authorization is a separate gate."""

from dataclasses import dataclass, replace
from enum import Enum

from app.simulation.openttd.gamescript_protocol import BridgeProtocolError
from app.simulation.openttd.qualification_clock import EconomyClockReading
from app.simulation.openttd.qualification_policy import MAX_CLOCK_REQUESTS
from app.simulation.openttd.structural_world import StructuralWorldContext


class QualificationState(Enum):
    UNINITIALIZED = "uninitialized"
    BASELINE_MONTH_OBSERVED = "baseline_month_observed"
    FIRST_ROLLOVER_OBSERVED = "first_rollover_observed"
    SECOND_ROLLOVER_OBSERVED = "second_rollover_observed"
    QUALIFIED = "qualified"
    FAILED = "failed"


@dataclass(frozen=True)
class NativeRolloverEvidence:
    context: StructuralWorldContext
    boundaries: tuple[EconomyClockReading, ...] = ()
    last_sample: EconomyClockReading | None = None
    polls: int = 0
    failure: str | None = None
    max_polls: int = MAX_CLOCK_REQUESTS

    def __post_init__(self):
        if self.failure is not None and (type(self.failure) is not str or not self.failure):
            raise BridgeProtocolError("concrete typed qualification failure required")
        if not isinstance(self.context, StructuralWorldContext):
            raise BridgeProtocolError("typed runtime lineage required")
        if type(self.boundaries) is not tuple or len(self.boundaries) > 3:
            raise BridgeProtocolError("baseline and two boundary samples required")
        if (
            type(self.max_polls) is not int
            or not 1 <= self.max_polls <= MAX_CLOCK_REQUESTS
            or type(self.polls) is not int
            or not len(self.boundaries) <= self.polls <= self.max_polls
        ):
            raise BridgeProtocolError("clock poll budget exhausted")
        for index, reading in enumerate(self.boundaries):
            if not isinstance(reading, EconomyClockReading):
                raise BridgeProtocolError("typed native clock reading required")
            if index:
                previous = self.boundaries[index - 1]
                if (
                    reading.economy_year * 12 + reading.economy_month
                    != previous.economy_year * 12 + previous.economy_month + 1
                    or reading.economy_day != 1
                    or previous.month_end != reading.month_start
                ):
                    raise BridgeProtocolError("explicit adjacent first-day rollover required")
        if self.boundaries:
            if not isinstance(self.last_sample, EconomyClockReading):
                raise BridgeProtocolError("last native sample required")
            if (
                self.last_sample.month != self.boundaries[-1].month
                or self.last_sample.economy_date < self.boundaries[-1].economy_date
            ):
                raise BridgeProtocolError("incoherent last native sample")
        elif self.last_sample is not None:
            raise BridgeProtocolError("sample without baseline")

    @property
    def state(self):
        if self.failure is not None:
            return QualificationState.FAILED
        return (
            QualificationState.UNINITIALIZED,
            QualificationState.BASELINE_MONTH_OBSERVED,
            QualificationState.FIRST_ROLLOVER_OBSERVED,
            QualificationState.SECOND_ROLLOVER_OBSERVED,
        )[len(self.boundaries)]

    @property
    def qualified(self):
        # Clock evidence alone cannot establish structural stability or fresh coverage.
        return False

    @property
    def bounded_month(self):
        return self.boundaries[1].month if len(self.boundaries) == 3 else None

    def observe(self, reading: EconomyClockReading, context: StructuralWorldContext):
        self.context.require_same_run(context)
        if self.failure is not None:
            raise BridgeProtocolError("failed qualification cannot resume")
        if not isinstance(reading, EconomyClockReading):
            raise BridgeProtocolError("native clock sample required")
        if self.last_sample is not None and reading.economy_date < self.last_sample.economy_date:
            raise BridgeProtocolError("native economy date moved backward")
        boundaries = self.boundaries
        if not boundaries or reading.month != boundaries[-1].month:
            if len(boundaries) == 3:
                raise BridgeProtocolError("final collection crossed third rollover")
            boundaries = (*boundaries, reading)
        return replace(self, boundaries=boundaries, last_sample=reading, polls=self.polls + 1)

    def fail(self, reason: str):
        if not isinstance(reason, str) or not reason:
            raise BridgeProtocolError("concrete failure reason required")
        return replace(self, failure=reason)


@dataclass(frozen=True)
class QualifiedMonthIdentity:
    economy_year: int
    economy_month: int
    boundary_start: EconomyClockReading
    boundary_end: EconomyClockReading
    lineage: StructuralWorldContext

    def __post_init__(self):
        NativeRolloverEvidence(
            self.lineage, (self.boundary_start, self.boundary_end), self.boundary_end, 2
        )
        if (self.economy_year, self.economy_month) != (
            self.boundary_start.economy_year,
            self.boundary_start.economy_month,
        ) or self.boundary_start.economy_day != 1:
            raise BridgeProtocolError("qualified month requires native first-day boundaries")
