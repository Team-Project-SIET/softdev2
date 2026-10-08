"""Conservative target lifetime gate; endpoint equality alone is insufficient."""

from dataclasses import dataclass, replace

from app.simulation.openttd.gamescript_protocol import BridgeProtocolError
from app.simulation.openttd.production_observation import (
    IndustryProductionObservation,
    production_pairs,
)
from app.simulation.openttd.qualification_clock import IndustryLifetimeReading, calendar_bounds
from app.simulation.openttd.qualification_state import NativeRolloverEvidence, QualificationState
from app.simulation.openttd.structural_world import StructuralWorldObservation


@dataclass(frozen=True)
class QualificationProfile:
    calendar_economy: bool
    no_newgrf: bool
    continuous_runtime: bool
    pre_decision: bool
    synchronized_generated_calendar: bool = True

    def __post_init__(self):
        if any(type(v) is not bool or not v for v in vars(self).values()):
            raise BridgeProtocolError(
                "calendar-time, no-NewGRF continuous PRE-DECISION profile required"
            )


@dataclass(frozen=True)
class TargetStability:
    profile: QualificationProfile
    clock: NativeRolloverEvidence
    anchor: StructuralWorldObservation
    final: StructuralWorldObservation
    anchor_lifetimes: tuple[IndustryLifetimeReading, ...]
    final_lifetimes: tuple[IndustryLifetimeReading, ...]

    def __post_init__(self):
        if not isinstance(self.profile, QualificationProfile):
            raise BridgeProtocolError("explicit qualification profile required")
        if self.clock.state is not QualificationState.SECOND_ROLLOVER_OBSERVED:
            raise BridgeProtocolError("two observed adjacent rollovers required")
        for source in (self.anchor, self.final):
            replace(source)
            self.clock.context.require_same_run(source.inventory.context)
        if production_pairs(self.anchor) != production_pairs(self.final):
            raise BridgeProtocolError("produced target set changed during bounded month")
        ids = tuple(sorted({industry for industry, _ in production_pairs(self.final)}))
        for lifetimes, month in (
            (self.anchor_lifetimes, self.clock.boundaries[1].month),
            (self.final_lifetimes, self.clock.boundaries[2].month),
        ):
            if (
                type(lifetimes) is not tuple
                or any(not isinstance(v, IndustryLifetimeReading) for v in lifetimes)
                or tuple(v.industry_id for v in lifetimes) != ids
            ):
                raise BridgeProtocolError("exact canonical native lifetime coverage required")
            for v in lifetimes:
                if not month.start_date <= v.economy_before <= v.economy_after < month.end_date:
                    raise BridgeProtocolError("lifetime reads outside collection month")
                # Only the restricted generated, synchronized calendar profile admits
                # this CALENDAR boundary. Never compare construction identity to
                # an arbitrary economy ordinal (wallclock/saves are excluded).
                calendar_start, _ = calendar_bounds(
                    self.clock.boundaries[1].economy_year, self.clock.boundaries[1].economy_month
                )
                if v.construction_date >= calendar_start:
                    raise BridgeProtocolError("target industry born/replaced during bounded month")
        anchor_records = {r.id: r for r in self.anchor.inventory.observation.records}
        final_records = {r.id: r for r in self.final.inventory.observation.records}
        if any(anchor_records[i] != final_records[i] for i in ids) or tuple(
            v.construction_date for v in self.anchor_lifetimes
        ) != tuple(v.construction_date for v in self.final_lifetimes):
            raise BridgeProtocolError("producing industry identity changed")


@dataclass(frozen=True)
class QualifiedProductionVerification:
    stability: TargetStability
    production: IndustryProductionObservation

    def __post_init__(self):
        replace(self.stability)
        replace(self.production)
        clock = self.stability.clock
        clock.context.require_same_run(self.production.context)
        if (
            self.production.source_structural_world_digest
            != self.stability.final.structural_world_digest
            or self.production.qualification.observed_months
            != tuple(v.month for v in clock.boundaries)
            or not self.production.complete
            or not self.production.qualified_for_planning
        ):
            raise BridgeProtocolError("fresh final coverage and observed native window required")

    @property
    def qualified_month(self):
        return self.stability.clock.bounded_month

    @property
    def qualified_month_identity(self):
        from app.simulation.openttd.qualification_state import QualifiedMonthIdentity

        clock = self.stability.clock
        return QualifiedMonthIdentity(
            clock.boundaries[1].economy_year,
            clock.boundaries[1].economy_month,
            clock.boundaries[1],
            clock.boundaries[2],
            clock.context,
        )
