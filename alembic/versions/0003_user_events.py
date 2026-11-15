"""user events

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-15 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "user_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["telegram_id"],
            ["users.telegram_id"],
            name=op.f("fk_user_events_telegram_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_events")),
    )
    op.create_index("ix_user_events_telegram_id", "user_events", ["telegram_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_user_events_telegram_id", table_name="user_events")
    op.drop_table("user_events")
