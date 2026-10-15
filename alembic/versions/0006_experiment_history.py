"""Add experiment and simulation history.

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "experiment_scenarios",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("identifier", sa.String(120), nullable=False),
        sa.Column("version", sa.String(80), nullable=False),
        sa.Column("openttd_config", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_experiment_scenarios")),
        sa.UniqueConstraint(
            "identifier", "version", name=op.f("uq_experiment_scenarios_identifier")
        ),
    )
    op.create_table(
        "planning_strategies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("identifier", sa.String(120), nullable=False),
        sa.Column("version", sa.String(80), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_planning_strategies")),
        sa.UniqueConstraint(
            "identifier", "version", name=op.f("uq_planning_strategies_identifier")
        ),
    )
    op.create_table(
        "experiment_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scenario_id", sa.Integer(), nullable=False),
        sa.Column("strategy_id", sa.Integer(), nullable=False),
        sa.Column("strategy_configuration", sa.JSON(), nullable=False),
        sa.Column("ai_configuration", sa.JSON(), nullable=False),
        sa.Column("openttd_version", sa.String(40), nullable=False),
        sa.Column("opengfx_version", sa.String(40), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("raw_artifact_reference", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["scenario_id"],
            ["experiment_scenarios.id"],
            name=op.f("fk_experiment_runs_scenario_id_experiment_scenarios"),
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["planning_strategies.id"],
            name=op.f("fk_experiment_runs_strategy_id_planning_strategies"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_experiment_runs")),
    )
    op.create_table(
        "simulation_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("experiment_run_id", sa.Integer(), nullable=False),
        sa.Column("simulation_date", sa.Date(), nullable=False),
        sa.Column("savegame_version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["experiment_run_id"],
            ["experiment_runs.id"],
            name=op.f("fk_simulation_runs_experiment_run_id_experiment_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_simulation_runs")),
        sa.UniqueConstraint("experiment_run_id", name=op.f("uq_simulation_runs_experiment_run_id")),
    )
    op.create_table(
        "experiment_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("simulation_run_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("value", sa.Numeric(24, 4), nullable=False),
        sa.Column("unit", sa.String(40), nullable=False),
        sa.ForeignKeyConstraint(
            ["simulation_run_id"],
            ["simulation_runs.id"],
            name=op.f("fk_experiment_metrics_simulation_run_id_simulation_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_experiment_metrics")),
        sa.UniqueConstraint(
            "simulation_run_id", "name", name=op.f("uq_experiment_metrics_simulation_run_id")
        ),
    )


def downgrade() -> None:
    op.drop_table("experiment_metrics")
    op.drop_table("simulation_runs")
    op.drop_table("experiment_runs")
    op.drop_table("planning_strategies")
    op.drop_table("experiment_scenarios")
