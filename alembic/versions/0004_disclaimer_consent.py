"""disclaimer consent

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-19 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema. Existing people stay NULL: they never pressed the button."""
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column("disclaimer_accepted_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("users") as batch:
        batch.drop_column("disclaimer_accepted_at")
