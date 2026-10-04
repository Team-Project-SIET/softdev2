"""Explicit plan-run attribution; historical external AI strategies keep their meaning.

Downgrade refuses while plan runs exist, preserving their evidence and history.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

OLD_FAILURES = (
    "'startup_failure', 'authentication_failure', 'protocol_failure', 'observer_lost', "
    "'persistence_failure', 'unexpected_shutdown', 'timeout', 'cancelled', "
    "'finalization_failure', 'cleanup_failure'"
)


def upgrade():
    with op.batch_alter_table("experiment_runs") as batch:
        batch.alter_column("strategy_id", existing_type=sa.Integer(), nullable=True)
        batch.add_column(
            sa.Column("input_kind", sa.String(20), nullable=False, server_default="external_ai")
        )
        batch.create_check_constraint(
            op.f("ck_experiment_runs_input_kind_valid"),
            "(input_kind = 'external_ai' AND strategy_id IS NOT NULL) OR "
            "(input_kind = 'execution_plan' AND strategy_id IS NULL AND execution_mode = 'live')",
        )
        batch.drop_constraint(op.f("ck_experiment_runs_failure_code_valid"), type_="check")
        batch.create_check_constraint(
            op.f("ck_experiment_runs_failure_code_valid"),
            f"failure_code IS NULL OR failure_code IN ({OLD_FAILURES}, "
            "'plan_transport_failure', 'plan_setup_failure', 'partial_execution')",
        )
    op.create_table(
        "plan_evaluations",
        sa.Column(
            "experiment_run_id",
            sa.Integer(),
            sa.ForeignKey("experiment_runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("plan_hash", sa.String(64), nullable=False),
        sa.Column("world_fingerprint", sa.String(64), nullable=False),
        sa.Column("strategy_identifier", sa.String(120), nullable=False),
        sa.Column("strategy_version", sa.String(80), nullable=False),
        sa.Column(
            "provenance",
            sa.JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql"),
            nullable=False,
        ),
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM experiment_runs WHERE input_kind = 'execution_plan'")
    ):
        raise RuntimeError("P07 downgrade requires explicit archival/removal of plan runs")
    op.drop_table("plan_evaluations")
    with op.batch_alter_table("experiment_runs") as batch:
        batch.drop_constraint(op.f("ck_experiment_runs_input_kind_valid"), type_="check")
        batch.drop_column("input_kind")
        batch.alter_column("strategy_id", existing_type=sa.Integer(), nullable=False)
        batch.drop_constraint(op.f("ck_experiment_runs_failure_code_valid"), type_="check")
        batch.create_check_constraint(
            op.f("ck_experiment_runs_failure_code_valid"),
            f"failure_code IS NULL OR failure_code IN ({OLD_FAILURES})",
        )
