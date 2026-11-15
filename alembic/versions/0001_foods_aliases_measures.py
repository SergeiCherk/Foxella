"""foods aliases measures

Revision ID: 0001
Revises:
Create Date: 2026-11-09 00:43:55.855662

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "foods",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name_ru", sa.String(length=200), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(length=16), nullable=False),
        sa.Column("raw_food_id", sa.Integer(), nullable=True),
        sa.Column("yield_factor", sa.Float(), nullable=True),
        sa.Column("kcal_100", sa.Float(), nullable=False),
        sa.Column("protein_100", sa.Float(), nullable=False),
        sa.Column("fat_100", sa.Float(), nullable=False),
        sa.Column("carb_100", sa.Float(), nullable=False),
        sa.Column("fiber_100", sa.Float(), nullable=False),
        sa.CheckConstraint(
            "state != 'cooked' OR (raw_food_id IS NOT NULL AND yield_factor IS NOT NULL)",
            name=op.f("ck_foods_cooked_has_raw"),
        ),
        sa.CheckConstraint(
            "state IN ('raw', 'cooked', 'ready')", name=op.f("ck_foods_state_valid")
        ),
        sa.CheckConstraint(
            "kcal_100 >= 0 AND protein_100 >= 0 AND fat_100 >= 0 AND carb_100 >= 0 AND fiber_100 >= 0",
            name=op.f("ck_foods_nutrients_non_negative"),
        ),
        sa.CheckConstraint(
            "yield_factor IS NULL OR yield_factor > 0", name=op.f("ck_foods_yield_positive")
        ),
        sa.ForeignKeyConstraint(
            ["raw_food_id"], ["foods.id"], name=op.f("fk_foods_raw_food_id_foods")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_foods")),
        sa.UniqueConstraint("code", name=op.f("uq_foods_code")),
        sa.UniqueConstraint("name_ru", name=op.f("uq_foods_name_ru")),
    )
    op.create_table(
        "food_aliases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("food_id", sa.Integer(), nullable=False),
        sa.Column("alias", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(
            ["food_id"],
            ["foods.id"],
            name=op.f("fk_food_aliases_food_id_foods"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_food_aliases")),
        sa.UniqueConstraint("food_id", "alias", name=op.f("uq_food_aliases_food_id")),
    )
    with op.batch_alter_table("food_aliases", schema=None) as batch_op:
        batch_op.create_index("ix_food_aliases_alias", ["alias"], unique=False)

    op.create_table(
        "measures",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("food_id", sa.Integer(), nullable=False),
        sa.Column("name_ru", sa.String(length=64), nullable=False),
        sa.Column("grams", sa.Float(), nullable=False),
        sa.CheckConstraint("grams > 0", name=op.f("ck_measures_grams_positive")),
        sa.ForeignKeyConstraint(
            ["food_id"], ["foods.id"], name=op.f("fk_measures_food_id_foods"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_measures")),
        sa.UniqueConstraint("food_id", "name_ru", name=op.f("uq_measures_food_id")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("measures")
    with op.batch_alter_table("food_aliases", schema=None) as batch_op:
        batch_op.drop_index("ix_food_aliases_alias")

    op.drop_table("food_aliases")
    op.drop_table("foods")
