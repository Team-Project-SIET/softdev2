"""Create the initial logistics schema.

Revision ID: 0001
Revises: None
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


shipment_priority = sa.Enum("low", "normal", "high", name="shipment_priority")
shipment_status = sa.Enum(
    "pending", "planned", "in_transit", "delivered", "cancelled", name="shipment_status"
)
vehicle_status = sa.Enum("available", "in_use", "maintenance", "inactive", name="vehicle_status")


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("address", sa.String(length=500), nullable=False),
        sa.Column("latitude", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("longitude", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customers")),
    )
    op.create_table(
        "vehicles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("width", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("length", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("height", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("max_weight", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("status", vehicle_status, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vehicles")),
        sa.UniqueConstraint("name", name=op.f("uq_vehicles_name")),
    )
    op.create_index(op.f("ix_vehicles_status"), "vehicles", ["status"], unique=False)
    op.create_table(
        "shipments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("delivery_date", sa.Date(), nullable=False),
        sa.Column("priority", shipment_priority, nullable=False),
        sa.Column("status", shipment_status, nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_shipments_customer_id_customers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipments")),
    )
    op.create_index(op.f("ix_shipments_customer_id"), "shipments", ["customer_id"], unique=False)
    op.create_index(
        op.f("ix_shipments_delivery_date"), "shipments", ["delivery_date"], unique=False
    )
    op.create_index(op.f("ix_shipments_status"), "shipments", ["status"], unique=False)
    op.create_table(
        "drivers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("line_user_id", sa.String(length=64), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["vehicle_id"],
            ["vehicles.id"],
            name=op.f("fk_drivers_vehicle_id_vehicles"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_drivers")),
        sa.UniqueConstraint("line_user_id", name=op.f("uq_drivers_line_user_id")),
    )
    op.create_index(op.f("ix_drivers_vehicle_id"), "drivers", ["vehicle_id"], unique=False)
    op.create_table(
        "packages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shipment_id", sa.Integer(), nullable=False),
        sa.Column("width", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("length", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("height", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("weight", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("stackable", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["shipment_id"],
            ["shipments.id"],
            name=op.f("fk_packages_shipment_id_shipments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_packages")),
    )
    op.create_index(op.f("ix_packages_shipment_id"), "packages", ["shipment_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_packages_shipment_id"), table_name="packages")
    op.drop_table("packages")
    op.drop_index(op.f("ix_drivers_vehicle_id"), table_name="drivers")
    op.drop_table("drivers")
    op.drop_index(op.f("ix_shipments_status"), table_name="shipments")
    op.drop_index(op.f("ix_shipments_delivery_date"), table_name="shipments")
    op.drop_index(op.f("ix_shipments_customer_id"), table_name="shipments")
    op.drop_table("shipments")
    op.drop_index(op.f("ix_vehicles_status"), table_name="vehicles")
    op.drop_table("vehicles")
    op.drop_table("customers")
    vehicle_status.drop(op.get_bind(), checkfirst=True)
    shipment_status.drop(op.get_bind(), checkfirst=True)
    shipment_priority.drop(op.get_bind(), checkfirst=True)
