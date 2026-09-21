"""Add delivery-aware loading plans and package placements.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

loading_status = sa.Enum("complete", "partial", "infeasible", name="loading_status")


def upgrade() -> None:
    op.create_table(
        "loading_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("route_id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("total_package_volume", sa.Numeric(38, 6), nullable=False),
        sa.Column("used_cargo_volume", sa.Numeric(38, 6), nullable=False),
        sa.Column("cargo_volume", sa.Numeric(38, 6), nullable=False),
        sa.Column("volume_utilization_percentage", sa.Numeric(5, 2), nullable=False),
        sa.Column("total_loaded_weight", sa.Numeric(12, 2), nullable=False),
        sa.Column("payload_utilization_percentage", sa.Numeric(5, 2), nullable=False),
        sa.Column("status", loading_status, nullable=False),
        sa.Column("unplaced_packages", sa.JSON(), nullable=False),
        sa.Column("source_snapshot", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["route_id"],
            ["routes.id"],
            name=op.f("fk_loading_plans_route_id_routes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_id"], ["vehicles.id"], name=op.f("fk_loading_plans_vehicle_id_vehicles")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_loading_plans")),
    )
    op.create_index(op.f("ix_loading_plans_route_id"), "loading_plans", ["route_id"])
    op.create_index(op.f("ix_loading_plans_vehicle_id"), "loading_plans", ["vehicle_id"])
    op.create_index(op.f("ix_loading_plans_status"), "loading_plans", ["status"])
    op.create_table(
        "package_placements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("loading_plan_id", sa.Integer(), nullable=False),
        sa.Column("package_id", sa.Integer(), nullable=False),
        sa.Column("x", sa.Numeric(10, 2), nullable=False),
        sa.Column("y", sa.Numeric(10, 2), nullable=False),
        sa.Column("z", sa.Numeric(10, 2), nullable=False),
        sa.Column("orientation", sa.String(3), nullable=False),
        sa.Column("width", sa.Numeric(10, 2), nullable=False),
        sa.Column("length", sa.Numeric(10, 2), nullable=False),
        sa.Column("height", sa.Numeric(10, 2), nullable=False),
        sa.Column("loading_order", sa.Integer(), nullable=False),
        sa.Column("unloading_order", sa.Integer(), nullable=False),
        sa.Column("stop_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["loading_plan_id"],
            ["loading_plans.id"],
            name=op.f("fk_package_placements_loading_plan_id_loading_plans"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["package_id"], ["packages.id"], name=op.f("fk_package_placements_package_id_packages")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_package_placements")),
        sa.UniqueConstraint("loading_plan_id", "package_id", name="uq_placements_plan_package"),
        sa.UniqueConstraint("loading_plan_id", "loading_order", name="uq_placements_plan_loading"),
        sa.UniqueConstraint(
            "loading_plan_id", "unloading_order", name="uq_placements_plan_unloading"
        ),
    )
    op.create_index(
        op.f("ix_package_placements_loading_plan_id"), "package_placements", ["loading_plan_id"]
    )
    op.create_index(op.f("ix_package_placements_package_id"), "package_placements", ["package_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_package_placements_package_id"), table_name="package_placements")
    op.drop_index(op.f("ix_package_placements_loading_plan_id"), table_name="package_placements")
    op.drop_table("package_placements")
    op.drop_index(op.f("ix_loading_plans_status"), table_name="loading_plans")
    op.drop_index(op.f("ix_loading_plans_vehicle_id"), table_name="loading_plans")
    op.drop_index(op.f("ix_loading_plans_route_id"), table_name="loading_plans")
    op.drop_table("loading_plans")
    loading_status.drop(op.get_bind(), checkfirst=True)
