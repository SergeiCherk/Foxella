"""conversation state in the database

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-20 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema. Conversations in progress survive a restart of the bot."""
    op.create_table(
        "fsm_states",
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(length=100), nullable=True),
        sa.Column("data", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_fsm_states")),
    )
    op.create_index(op.f("ix_fsm_states_user_id"), "fsm_states", ["user_id"])
    op.create_index(op.f("ix_fsm_states_updated_at"), "fsm_states", ["updated_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_fsm_states_updated_at"), table_name="fsm_states")
    op.drop_index(op.f("ix_fsm_states_user_id"), table_name="fsm_states")
    op.drop_table("fsm_states")
