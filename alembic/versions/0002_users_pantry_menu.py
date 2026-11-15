"""users pantry menu

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-12 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "users",
        sa.Column("telegram_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("sex", sa.String(length=8), nullable=False),
        sa.Column("age", sa.Integer(), nullable=False),
        sa.Column("height_cm", sa.Float(), nullable=False),
        sa.Column("weight_kg", sa.Float(), nullable=False),
        sa.Column("activity", sa.String(length=16), nullable=False),
        sa.Column("goal", sa.String(length=16), nullable=False),
        sa.Column("pending_adjust", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "goal IN ('lose', 'maintain', 'gain')", name=op.f("ck_users_goal_valid")
        ),
        sa.CheckConstraint("sex IN ('male', 'female')", name=op.f("ck_users_sex_valid")),
        sa.PrimaryKeyConstraint("telegram_id", name=op.f("pk_users")),
    )
    op.create_table(
        "user_foods",
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("food_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["food_id"], ["foods.id"], name=op.f("fk_user_foods_food_id_foods")
        ),
        sa.ForeignKeyConstraint(
            ["telegram_id"],
            ["users.telegram_id"],
            name=op.f("fk_user_foods_telegram_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("telegram_id", "food_id", name=op.f("pk_user_foods")),
    )
    op.create_table(
        "user_menus",
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["telegram_id"],
            ["users.telegram_id"],
            name=op.f("fk_user_menus_telegram_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("telegram_id", name=op.f("pk_user_menus")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("user_menus")
    op.drop_table("user_foods")
    op.drop_table("users")
