"""Add route distance and weight column comments to existing databases.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "routes",
        "total_distance",
        existing_type=sa.Numeric(precision=12, scale=3),
        existing_nullable=False,
        comment="Kilometers",
    )
    op.alter_column(
        "routes",
        "total_weight",
        existing_type=sa.Numeric(precision=12, scale=3),
        existing_nullable=False,
        comment="Kilograms",
    )
    op.alter_column(
        "route_stops",
        "distance_from_previous",
        existing_type=sa.Numeric(precision=12, scale=3),
        existing_nullable=False,
        comment="Kilometers",
    )


def downgrade() -> None:
    raise NotImplementedError("0005 is a forward-only migration")
