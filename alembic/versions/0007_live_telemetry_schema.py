"""Add live telemetry storage without changing existing experiment history.

Revision ID: 0007
Revises: 0006

Downgrading deliberately deletes live telemetry sessions and observations. It
retains all pre-T02 experiment, simulation and metric data.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONDocument = sa.JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql")


def ck(table: str, name: str, expression: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(expression, name=op.f(f"ck_{table}_{name}"))


def upgrade() -> None:
    with op.batch_alter_table("experiment_runs") as batch_op:
        batch_op.add_column(
            sa.Column("execution_mode", sa.String(20), nullable=False, server_default="batch")
        )
        batch_op.add_column(sa.Column("failure_code", sa.String(40), nullable=True))
        batch_op.add_column(sa.Column("execution_metadata", JSONDocument, nullable=True))
        batch_op.create_check_constraint(
            op.f("ck_experiment_runs_execution_mode_valid"),
            "execution_mode IN ('batch', 'live')",
        )
        batch_op.create_check_constraint(
            op.f("ck_experiment_runs_failure_code_valid"),
            "failure_code IS NULL OR failure_code IN ("
            "'startup_failure', 'authentication_failure', 'protocol_failure', "
            "'observer_lost', 'persistence_failure', 'unexpected_shutdown', 'timeout', "
            "'cancelled', 'finalization_failure', 'cleanup_failure')",
        )
        batch_op.create_check_constraint(
            op.f("ck_experiment_runs_execution_metadata_object"),
            "execution_metadata IS NULL OR "
            "substr(ltrim(cast(execution_metadata AS text)), 1, 1) = '{'",
        )

    op.create_table(
        "live_telemetry_sessions",
        sa.Column("experiment_run_id", sa.Integer(), nullable=False),
        sa.Column("telemetry_status", sa.String(20), nullable=False),
        sa.Column("protocol_version", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("negotiated_subscriptions", JSONDocument, nullable=True),
        sa.Column("connection_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("received_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("persisted_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("unknown_packet_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("gap_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dropped_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("last_observed_sequence", sa.BigInteger(), nullable=True),
        sa.Column("last_observed_day", sa.Integer(), nullable=True),
        sa.Column("final_persisted_sequence", sa.BigInteger(), nullable=True),
        sa.Column("process_exit_code", sa.Integer(), nullable=True),
        sa.Column("terminal_reason", sa.String(40), nullable=True),
        sa.Column("error_summary", sa.String(1024), nullable=True),
        sa.PrimaryKeyConstraint("experiment_run_id", name=op.f("pk_live_telemetry_sessions")),
        sa.ForeignKeyConstraint(
            ["experiment_run_id"],
            ["experiment_runs.id"],
            name=op.f("fk_live_telemetry_sessions_experiment_run_id_experiment_runs"),
            ondelete="CASCADE",
        ),
        ck(
            "live_telemetry_sessions",
            "telemetry_status_valid",
            "telemetry_status IN ('pending', 'recording', 'complete', 'incomplete', 'failed')",
        ),
        ck(
            "live_telemetry_sessions",
            "counts_nonnegative",
            "connection_count >= 0 AND received_count >= 0 AND persisted_count >= 0 "
            "AND unknown_packet_count >= 0 AND gap_count >= 0 AND dropped_count >= 0",
        ),
        ck(
            "live_telemetry_sessions",
            "last_sequence_positive",
            "last_observed_sequence IS NULL OR last_observed_sequence > 0",
        ),
        ck(
            "live_telemetry_sessions",
            "final_sequence_positive",
            "final_persisted_sequence IS NULL OR final_persisted_sequence > 0",
        ),
        ck(
            "live_telemetry_sessions",
            "last_day_nonnegative",
            "last_observed_day IS NULL OR last_observed_day >= 0",
        ),
        ck("live_telemetry_sessions", "error_summary_bounded", "length(error_summary) <= 1024"),
    )
    op.create_table(
        "telemetry_observations",
        sa.Column("experiment_run_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("connection_epoch", sa.Integer(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("protocol_version", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=True),
        sa.Column("game_day", sa.Integer(), nullable=True),
        sa.Column("date_context_sequence", sa.BigInteger(), nullable=True),
        sa.Column("date_quality", sa.String(20), nullable=False),
        sa.Column("payload", JSONDocument, nullable=False),
        sa.PrimaryKeyConstraint(
            "experiment_run_id", "sequence", name=op.f("pk_telemetry_observations")
        ),
        sa.ForeignKeyConstraint(
            ["experiment_run_id"],
            ["live_telemetry_sessions.experiment_run_id"],
            name=op.f("fk_telemetry_observations_experiment_run_id_live_telemetry_sessions"),
            ondelete="CASCADE",
        ),
        ck("telemetry_observations", "sequence_positive", "sequence > 0"),
        ck("telemetry_observations", "schema_version_positive", "schema_version > 0"),
        ck("telemetry_observations", "epoch_nonnegative", "connection_epoch >= 0"),
        ck(
            "telemetry_observations",
            "measurement_epoch_positive",
            "kind = 'diagnostic' OR connection_epoch > 0",
        ),
        ck("telemetry_observations", "source_valid", "source IN ('openttd_admin', 'live_runtime')"),
        ck(
            "telemetry_observations",
            "source_kind_valid",
            "kind = 'diagnostic' OR source = 'openttd_admin'",
        ),
        ck(
            "telemetry_observations",
            "kind_valid",
            "kind IN ('date', 'company_info', 'company_economy', 'company_stats', 'diagnostic')",
        ),
        ck(
            "telemetry_observations",
            "date_quality_valid",
            "date_quality IN ('packet_date', 'preceding_date', 'unknown')",
        ),
        ck(
            "telemetry_observations",
            "packet_date_kind_valid",
            "date_quality <> 'packet_date' OR kind = 'date'",
        ),
        ck(
            "telemetry_observations",
            "company_id_valid",
            "company_id IS NULL OR company_id BETWEEN 0 AND 14",
        ),
        ck("telemetry_observations", "game_day_nonnegative", "game_day IS NULL OR game_day >= 0"),
        ck(
            "telemetry_observations",
            "date_context_positive",
            "date_context_sequence IS NULL OR date_context_sequence > 0",
        ),
        ck(
            "telemetry_observations",
            "date_shape_valid",
            "kind <> 'date' OR (company_id IS NULL AND game_day IS NOT NULL "
            "AND date_context_sequence IS NULL AND date_quality = 'packet_date')",
        ),
        ck(
            "telemetry_observations",
            "company_shape_valid",
            "kind NOT IN ('company_info', 'company_economy', 'company_stats') "
            "OR company_id IS NOT NULL",
        ),
        ck(
            "telemetry_observations",
            "unknown_date_context_empty",
            "date_quality <> 'unknown' OR (game_day IS NULL AND date_context_sequence IS NULL)",
        ),
        ck(
            "telemetry_observations",
            "payload_object",
            "substr(ltrim(cast(payload AS text)), 1, 1) = '{'",
        ),
    )
    op.create_index(
        "ix_telemetry_observations_run_received_sequence",
        "telemetry_observations",
        ["experiment_run_id", "received_at", "sequence"],
    )
    op.create_index(
        "ix_telemetry_observations_run_company_day_sequence",
        "telemetry_observations",
        ["experiment_run_id", "company_id", "game_day", "sequence"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_telemetry_observations_run_company_day_sequence", table_name="telemetry_observations"
    )
    op.drop_index(
        "ix_telemetry_observations_run_received_sequence", table_name="telemetry_observations"
    )
    op.drop_table("telemetry_observations")
    op.drop_table("live_telemetry_sessions")
    with op.batch_alter_table("experiment_runs") as batch_op:
        batch_op.drop_constraint(
            op.f("ck_experiment_runs_execution_metadata_object"), type_="check"
        )
        batch_op.drop_constraint(op.f("ck_experiment_runs_failure_code_valid"), type_="check")
        batch_op.drop_constraint(op.f("ck_experiment_runs_execution_mode_valid"), type_="check")
        batch_op.drop_column("execution_metadata")
        batch_op.drop_column("failure_code")
        batch_op.drop_column("execution_mode")
