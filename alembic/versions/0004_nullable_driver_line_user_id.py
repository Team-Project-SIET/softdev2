"""Allow drivers without LINE enrollment.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("drivers") as batch_op:
        batch_op.alter_column("line_user_id", existing_type=sa.String(length=64), nullable=True)


def downgrade() -> None:
    connection = op.get_bind()
    missing = connection.scalar(sa.text("SELECT COUNT(*) FROM drivers WHERE line_user_id IS NULL"))
    if missing:
        raise RuntimeError("assign LINE user IDs to all drivers before downgrading 0004")
    with op.batch_alter_table("drivers") as batch_op:
        batch_op.alter_column("line_user_id", existing_type=sa.String(length=64), nullable=False)
