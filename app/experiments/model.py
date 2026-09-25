"""Experiment history; operational logistics tables remain separate."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.experiments.domain import ExecutionFailureCode, ExecutionMode, TelemetryStatus

JSONDocument = JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql")


def allowed_values(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(str(value)) for value in values)})"


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
    __table_args__ = (
        CheckConstraint(
            allowed_values("execution_mode", tuple(ExecutionMode)), name="execution_mode_valid"
        ),
        CheckConstraint(
            "failure_code IS NULL OR "
            + allowed_values("failure_code", tuple(ExecutionFailureCode)),
            name="failure_code_valid",
        ),
        CheckConstraint(
            "execution_metadata IS NULL OR "
            "substr(ltrim(cast(execution_metadata AS text)), 1, 1) = '{'",
            name="execution_metadata_object",
        ),
    )

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
    execution_mode: Mapped[str] = mapped_column(
        String(20), default=ExecutionMode.BATCH, server_default=text("'batch'")
    )
    failure_code: Mapped[str | None] = mapped_column(String(40))
    execution_metadata: Mapped[dict | None] = mapped_column(JSONDocument)

    scenario: Mapped[ExperimentScenario] = relationship()
    strategy: Mapped[PlanningStrategyRecord] = relationship()
    simulation: Mapped[SimulationRunRecord | None] = relationship(
        back_populates="experiment", uselist=False
    )
    telemetry_session: Mapped[LiveTelemetrySessionRecord | None] = relationship(
        back_populates="experiment", uselist=False, cascade="all, delete-orphan"
    )


class LiveTelemetrySessionRecord(Base):
    __tablename__ = "live_telemetry_sessions"
    __table_args__ = (
        CheckConstraint(
            allowed_values("telemetry_status", tuple(TelemetryStatus)),
            name="telemetry_status_valid",
        ),
        CheckConstraint(
            "connection_count >= 0 AND received_count >= 0 AND persisted_count >= 0 "
            "AND unknown_packet_count >= 0 AND gap_count >= 0 AND dropped_count >= 0",
            name="counts_nonnegative",
        ),
        CheckConstraint(
            "last_observed_sequence IS NULL OR last_observed_sequence > 0",
            name="last_sequence_positive",
        ),
        CheckConstraint(
            "final_persisted_sequence IS NULL OR final_persisted_sequence > 0",
            name="final_sequence_positive",
        ),
        CheckConstraint(
            "last_observed_day IS NULL OR last_observed_day >= 0",
            name="last_day_nonnegative",
        ),
        CheckConstraint("length(error_summary) <= 1024", name="error_summary_bounded"),
    )

    experiment_run_id: Mapped[int] = mapped_column(
        ForeignKey("experiment_runs.id", ondelete="CASCADE"), primary_key=True
    )
    telemetry_status: Mapped[str] = mapped_column(String(20))
    protocol_version: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    negotiated_subscriptions: Mapped[dict | None] = mapped_column(JSONDocument)
    connection_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    received_count: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    persisted_count: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    unknown_packet_count: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=text("0")
    )
    gap_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    dropped_count: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    last_observed_sequence: Mapped[int | None] = mapped_column(BigInteger)
    last_observed_day: Mapped[int | None] = mapped_column(Integer)
    final_persisted_sequence: Mapped[int | None] = mapped_column(BigInteger)
    process_exit_code: Mapped[int | None] = mapped_column(Integer)
    terminal_reason: Mapped[str | None] = mapped_column(String(40))
    error_summary: Mapped[str | None] = mapped_column(String(1024))

    experiment: Mapped[ExperimentRunRecord] = relationship(back_populates="telemetry_session")
    observations: Mapped[list[TelemetryObservationRecord]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class TelemetryObservationRecord(Base):
    __tablename__ = "telemetry_observations"
    __table_args__ = (
        CheckConstraint("sequence > 0", name="sequence_positive"),
        CheckConstraint("schema_version > 0", name="schema_version_positive"),
        CheckConstraint("connection_epoch >= 0", name="epoch_nonnegative"),
        CheckConstraint(
            "kind = 'diagnostic' OR connection_epoch > 0", name="measurement_epoch_positive"
        ),
        CheckConstraint(
            allowed_values("source", ("openttd_admin", "live_runtime")), name="source_valid"
        ),
        CheckConstraint(
            "kind = 'diagnostic' OR source = 'openttd_admin'",
            name="source_kind_valid",
        ),
        CheckConstraint(
            allowed_values(
                "kind", ("date", "company_info", "company_economy", "company_stats", "diagnostic")
            ),
            name="kind_valid",
        ),
        CheckConstraint(
            allowed_values("date_quality", ("packet_date", "preceding_date", "unknown")),
            name="date_quality_valid",
        ),
        CheckConstraint(
            "date_quality <> 'packet_date' OR kind = 'date'",
            name="packet_date_kind_valid",
        ),
        CheckConstraint(
            "company_id IS NULL OR company_id BETWEEN 0 AND 14", name="company_id_valid"
        ),
        CheckConstraint("game_day IS NULL OR game_day >= 0", name="game_day_nonnegative"),
        CheckConstraint(
            "date_context_sequence IS NULL OR date_context_sequence > 0",
            name="date_context_positive",
        ),
        CheckConstraint(
            "kind <> 'date' OR (company_id IS NULL AND game_day IS NOT NULL "
            "AND date_context_sequence IS NULL AND date_quality = 'packet_date')",
            name="date_shape_valid",
        ),
        CheckConstraint(
            "kind NOT IN ('company_info', 'company_economy', 'company_stats') "
            "OR company_id IS NOT NULL",
            name="company_shape_valid",
        ),
        CheckConstraint(
            "date_quality <> 'unknown' OR (game_day IS NULL AND date_context_sequence IS NULL)",
            name="unknown_date_context_empty",
        ),
        CheckConstraint("substr(ltrim(cast(payload AS text)), 1, 1) = '{'", name="payload_object"),
        Index(
            "ix_telemetry_observations_run_received_sequence",
            "experiment_run_id",
            "received_at",
            "sequence",
        ),
        Index(
            "ix_telemetry_observations_run_company_day_sequence",
            "experiment_run_id",
            "company_id",
            "game_day",
            "sequence",
        ),
    )

    experiment_run_id: Mapped[int] = mapped_column(
        ForeignKey("live_telemetry_sessions.experiment_run_id", ondelete="CASCADE"),
        primary_key=True,
    )
    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    connection_epoch: Mapped[int] = mapped_column(Integer)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(30))
    schema_version: Mapped[int] = mapped_column(Integer)
    protocol_version: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(30))
    company_id: Mapped[int | None] = mapped_column(Integer)
    game_day: Mapped[int | None] = mapped_column(Integer)
    date_context_sequence: Mapped[int | None] = mapped_column(BigInteger)
    date_quality: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict] = mapped_column(JSONDocument)

    session: Mapped[LiveTelemetrySessionRecord] = relationship(back_populates="observations")


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
