"""Add persisted route plans and ordered stops.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


route_status = sa.Enum(
    "planned",
    "in_progress",
    "completed",
    "cancelled",
    name="route_status",
)


def upgrade() -> None:
    op.create_table(
        "routes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=True),
        sa.Column("total_distance", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("total_weight", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("status", route_status, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["driver_id"],
            ["drivers.id"],
            name=op.f("fk_routes_driver_id_drivers"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_id"],
            ["vehicles.id"],
            name=op.f("fk_routes_vehicle_id_vehicles"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_routes")),
    )
    op.create_index(op.f("ix_routes_driver_id"), "routes", ["driver_id"], unique=False)
    op.create_index(op.f("ix_routes_status"), "routes", ["status"], unique=False)
    op.create_index(op.f("ix_routes_vehicle_id"), "routes", ["vehicle_id"], unique=False)
    op.create_table(
        "route_stops",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("route_id", sa.Integer(), nullable=False),
        sa.Column("shipment_id", sa.Integer(), nullable=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("stop_order", sa.Integer(), nullable=False),
        sa.Column("distance_from_previous", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("is_depot", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_route_stops_customer_id_customers"),
        ),
        sa.ForeignKeyConstraint(
            ["route_id"],
            ["routes.id"],
            name=op.f("fk_route_stops_route_id_routes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["shipment_id"],
            ["shipments.id"],
            name=op.f("fk_route_stops_shipment_id_shipments"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_route_stops")),
        sa.UniqueConstraint("route_id", "shipment_id", name="uq_route_stops_route_shipment"),
        sa.UniqueConstraint("route_id", "stop_order", name="uq_route_stops_route_order"),
    )
    op.create_index(
        op.f("ix_route_stops_customer_id"), "route_stops", ["customer_id"], unique=False
    )
    op.create_index(op.f("ix_route_stops_route_id"), "route_stops", ["route_id"], unique=False)
    op.create_index(
        op.f("ix_route_stops_shipment_id"), "route_stops", ["shipment_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_route_stops_shipment_id"), table_name="route_stops")
    op.drop_index(op.f("ix_route_stops_route_id"), table_name="route_stops")
    op.drop_index(op.f("ix_route_stops_customer_id"), table_name="route_stops")
    op.drop_table("route_stops")
    op.drop_index(op.f("ix_routes_vehicle_id"), table_name="routes")
    op.drop_index(op.f("ix_routes_status"), table_name="routes")
    op.drop_index(op.f("ix_routes_driver_id"), table_name="routes")
    op.drop_table("routes")
    route_status.drop(op.get_bind(), checkfirst=True)
