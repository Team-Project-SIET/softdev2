"""Offline verified native freight evaluation history, separate from live experiment runs."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "freight_run_history",
        sa.Column("source_digest", sa.String(64), primary_key=True),
        sa.Column("evaluation_digest", sa.String(64), nullable=False),
        sa.Column(
            "evaluation",
            sa.JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql"),
            nullable=False,
        ),
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT COUNT(*) FROM freight_run_history")).scalar():
        raise ValueError("Refuse to discard retained freight history")
    op.drop_table("freight_run_history")
