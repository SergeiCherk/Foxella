"""SQLAlchemy models: food catalog (Stage 4.2) and per-user data (Stage 5).

Privacy: a user row holds only the Telegram id and the fields the norm formulas need. No name,
no phone and no message texts are stored; deleting the user row removes everything else too,
including the usage events (a fixed event name and a time, never any text).
"""

from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Explicit constraint names let Alembic alter constraints on SQLite (batch mode).
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class FoodORM(Base):
    """A product with nutrients per 100 g. Raw and cooked versions are separate rows."""

    __tablename__ = "foods"
    __table_args__ = (
        CheckConstraint("state IN ('raw', 'cooked', 'ready')", name="state_valid"),
        CheckConstraint(
            "state != 'cooked' OR (raw_food_id IS NOT NULL AND yield_factor IS NOT NULL)",
            name="cooked_has_raw",
        ),
        CheckConstraint("yield_factor IS NULL OR yield_factor > 0", name="yield_positive"),
        CheckConstraint(
            "kcal_100 >= 0 AND protein_100 >= 0 AND fat_100 >= 0"
            " AND carb_100 >= 0 AND fiber_100 >= 0",
            name="nutrients_non_negative",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name_ru: Mapped[str] = mapped_column(String(200), unique=True)
    state: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(16))
    raw_food_id: Mapped[int | None] = mapped_column(ForeignKey("foods.id"), nullable=True)
    yield_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    kcal_100: Mapped[float] = mapped_column(Float)
    protein_100: Mapped[float] = mapped_column(Float)
    fat_100: Mapped[float] = mapped_column(Float)
    carb_100: Mapped[float] = mapped_column(Float)
    fiber_100: Mapped[float] = mapped_column(Float)


class FoodAliasORM(Base):
    """A way users may write a food ("курица", "грудка"). One alias may point to many foods."""

    __tablename__ = "food_aliases"
    __table_args__ = (UniqueConstraint("food_id", "alias"), Index("ix_food_aliases_alias", "alias"))

    id: Mapped[int] = mapped_column(primary_key=True)
    food_id: Mapped[int] = mapped_column(ForeignKey("foods.id", ondelete="CASCADE"))
    alias: Mapped[str] = mapped_column(String(100))


class MeasureORM(Base):
    """A household measure of one food, with its weight in grams."""

    __tablename__ = "measures"
    __table_args__ = (
        UniqueConstraint("food_id", "name_ru"),
        CheckConstraint("grams > 0", name="grams_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    food_id: Mapped[int] = mapped_column(ForeignKey("foods.id", ondelete="CASCADE"))
    name_ru: Mapped[str] = mapped_column(String(64))
    grams: Mapped[float] = mapped_column(Float)


def _now() -> datetime:
    return datetime.now(UTC)


class UserORM(Base):
    """One person: Telegram id plus the profile that the norm calculation needs."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("sex IN ('male', 'female')", name="sex_valid"),
        CheckConstraint("goal IN ('lose', 'maintain', 'gain')", name="goal_valid"),
    )

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    sex: Mapped[str] = mapped_column(String(8))
    age: Mapped[int] = mapped_column(Integer)
    height_cm: Mapped[float] = mapped_column(Float)
    weight_kg: Mapped[float] = mapped_column(Float)
    activity: Mapped[str] = mapped_column(String(16))
    goal: Mapped[str] = mapped_column(String(16))
    # JSON list of kcal changes for the next days after eating off-plan; used by the next menu.
    pending_adjust: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # When the person pressed "Понятно" under the disclaimer; NULL for people from before it.
    disclaimer_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    # Food restrictions as comma-separated codes of ``DietConfig.rules`` ("meat,nuts").
    restrictions: Mapped[str] = mapped_column(Text, default="", server_default="")


class UserFoodORM(Base):
    """A product the user said they have (the "pantry")."""

    __tablename__ = "user_foods"

    telegram_id: Mapped[int] = mapped_column(
        ForeignKey("users.telegram_id", ondelete="CASCADE"), primary_key=True
    )
    food_id: Mapped[int] = mapped_column(ForeignKey("foods.id"), primary_key=True)


class MenuORM(Base):
    """The last menu of a user as JSON (days -> meals -> dishes -> items)."""

    __tablename__ = "user_menus"

    telegram_id: Mapped[int] = mapped_column(
        ForeignKey("users.telegram_id", ondelete="CASCADE"), primary_key=True
    )
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class UserEventORM(Base):
    """One usage event of a user for the beta statistics: a fixed name and a time, no text."""

    __tablename__ = "user_events"
    __table_args__ = (Index("ix_user_events_telegram_id", "telegram_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
