"""Economy-date evidence, separate from calendar time, script ticks and wall time."""

import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from app.planning.domain import Contract


class GameTimeMetrics(Contract):
    date_basis: Literal["economy"] = "economy"
    start_basis: Literal["bridge_start_before_world_preparation"] | None = None
    planning_completion_observed_by_date: int | None = Field(default=None, ge=0)
    simulation_start_date: int | None = Field(default=None, ge=0)
    planning_completion_date: int | None = Field(default=None, ge=0)
    construction_completion_date: int | None = Field(default=None, ge=0)
    construction_observed_by_date: int | None = Field(default=None, ge=0)
    elapsed_calendar_days: int | None = Field(default=None, ge=0)
    first_cargo_pickup_date: int | None = Field(default=None, ge=0)
    final_cargo_delivery_date: int | None = Field(default=None, ge=0)
    pickup_observed_by_date: int | None = Field(default=None, ge=0)
    total_elapsed_economy_days: int | None = Field(default=None, ge=0)
    elapsed_script_ticks: int | None = Field(default=None, ge=0)
    elapsed_wall_clock_seconds: float | None = Field(default=None, ge=0)
    evidence_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def elapsed_matches_dates(self):
        start, end = self.simulation_start_date, self.final_cargo_delivery_date
        if start is not None and end is not None:
            if end < start:
                raise ValueError("economy date chronology mismatch")
            elapsed = end - start
            if self.total_elapsed_economy_days not in (None, elapsed):
                raise ValueError("elapsed economy days mismatch")
            object.__setattr__(self, "total_elapsed_economy_days", elapsed)
        elif self.total_elapsed_economy_days is not None:
            raise ValueError("elapsed economy days requires start and final delivery dates")
        return self


def retained_game_time(receipt: dict) -> GameTimeMetrics:
    """Historical snapshots bound pickup; they do not timestamp the first pickup."""
    if "game_time" in receipt:
        return GameTimeMetrics.model_validate_json(json.dumps(receipt["game_time"]))
    return GameTimeMetrics()


def service_game_time(directory: Path, index: int, receipt: dict) -> GameTimeMetrics:
    if "game_time" in receipt:
        return retained_game_time(receipt)
    from app.simulation.openttd.freight_native_network import receipt_game_time

    if all(
        (directory / f"s{index}-{stage}-response.json").exists()
        for stage in ("read-9", "observe-1", "finish")
    ):
        return GameTimeMetrics.model_validate_json(json.dumps(receipt_game_time(directory, index)))
    return GameTimeMetrics()


def network_game_time(services: tuple[GameTimeMetrics, ...]) -> GameTimeMetrics:
    def complete(field, aggregate):
        values = [getattr(s, field) for s in services]
        return aggregate(values) if values and all(v is not None for v in values) else None

    return GameTimeMetrics(
        simulation_start_date=complete("simulation_start_date", min),
        start_basis=services[0].start_basis
        if services and all(s.start_basis == services[0].start_basis for s in services)
        else None,
        planning_completion_observed_by_date=complete("planning_completion_observed_by_date", max),
        planning_completion_date=complete("planning_completion_date", max),
        construction_completion_date=complete("construction_completion_date", max),
        construction_observed_by_date=complete("construction_observed_by_date", max),
        final_cargo_delivery_date=complete("final_cargo_delivery_date", max),
        first_cargo_pickup_date=complete("first_cargo_pickup_date", min),
        pickup_observed_by_date=complete("pickup_observed_by_date", min),
        evidence_refs=tuple(ref for s in services for ref in s.evidence_refs),
    )
