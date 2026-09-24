"""Experiment history; operational logistics tables remain separate."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class ExperimentScenario(Base):
    __tablename__ = "experiment_scenarios"
    __table_args__ = (UniqueConstraint("identifier", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    identifier: Mapped[str] = mapped_column(String(120))
    version: Mapped[str] = mapped_column(String(80))
    openttd_config: Mapped[str] = mapped_column(Text, default="")


class PlanningStrategyRecord(Base):
    __tablename__ = "planning_strategies"
    __table_args__ = (UniqueConstraint("identifier", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    identifier: Mapped[str] = mapped_column(String(120))
    version: Mapped[str] = mapped_column(String(80))


class ExperimentRunRecord(Base):
    __tablename__ = "experiment_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("experiment_scenarios.id"))
    strategy_id: Mapped[int] = mapped_column(ForeignKey("planning_strategies.id"))
    strategy_configuration: Mapped[dict] = mapped_column(JSON)
    ai_configuration: Mapped[dict] = mapped_column(JSON)
    openttd_version: Mapped[str] = mapped_column(String(40))
    opengfx_version: Mapped[str] = mapped_column(String(40))
    seed: Mapped[int] = mapped_column(BigInteger)
    duration_days: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20))
    error: Mapped[str | None] = mapped_column(Text)
    raw_artifact_reference: Mapped[str | None] = mapped_column(Text)

    scenario: Mapped[ExperimentScenario] = relationship()
    strategy: Mapped[PlanningStrategyRecord] = relationship()
    simulation: Mapped[SimulationRunRecord | None] = relationship(
        back_populates="experiment", uselist=False
    )


class SimulationRunRecord(Base):
    __tablename__ = "simulation_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_run_id: Mapped[int] = mapped_column(
        ForeignKey("experiment_runs.id", ondelete="CASCADE"), unique=True
    )
    simulation_date: Mapped[date] = mapped_column(Date)
    savegame_version: Mapped[int] = mapped_column(Integer)

    experiment: Mapped[ExperimentRunRecord] = relationship(back_populates="simulation")
    metrics: Mapped[list[ExperimentMetricRecord]] = relationship(
        back_populates="simulation", cascade="all, delete-orphan"
    )


class ExperimentMetricRecord(Base):
    __tablename__ = "experiment_metrics"
    __table_args__ = (UniqueConstraint("simulation_run_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    simulation_run_id: Mapped[int] = mapped_column(
        ForeignKey("simulation_runs.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(100))
    value: Mapped[Decimal] = mapped_column(Numeric(24, 4))
    unit: Mapped[str] = mapped_column(String(40))

    simulation: Mapped[SimulationRunRecord] = relationship(back_populates="metrics")
