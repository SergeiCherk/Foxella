"""remembered food choices

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-20 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema. Answers to "which one?" as JSON; existing people have none."""
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("food_choices", sa.Text(), nullable=False, server_default="{}"))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("users") as batch:
        batch.drop_column("food_choices")
