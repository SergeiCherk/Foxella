"""Integration tests: seeding the real CSV files into SQLite and loading the core Catalog."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from nutrition_bot.core.measures import nutrients_for_measure
from nutrition_bot.core.models import FoodState
from nutrition_bot.db.models import FoodAliasORM, FoodORM, MeasureORM
from nutrition_bot.db.repositories.foods import FoodRepository
from nutrition_bot.db.seed import (
    FoodRow,
    MeasureRow,
    load_foods,
    load_measures,
    validate_data,
)
from nutrition_bot.db.session import create_engine, create_session_factory

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def db_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A fresh SQLite file with all migrations applied (sync fixture: Alembic runs its own loop)."""
    url = f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    command.upgrade(cfg, "head")
    return url


@pytest.fixture
async def session(db_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_engine(db_url)
    async with create_session_factory(engine)() as s:
        yield s
    await engine.dispose()


@pytest.fixture(scope="module")
def foods() -> list[FoodRow]:
    return load_foods()


@pytest.fixture(scope="module")
def measures() -> list[MeasureRow]:
    return load_measures()


async def count(session: AsyncSession, model: type) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def test_seed_and_load_catalog(
    session: AsyncSession, foods: list[FoodRow], measures: list[MeasureRow]
) -> None:
    repo = FoodRepository(session)
    await repo.seed(foods, measures)
    catalog = await repo.load_catalog()
    assert len(catalog.foods) == len(foods)
    assert await count(session, MeasureORM) == len(measures)
    assert all(catalog.measures_for(f.id) for f in catalog.foods)  # every food has a measure


async def test_two_ladles_of_rice_end_to_end(
    session: AsyncSession, foods: list[FoodRow], measures: list[MeasureRow]
) -> None:
    repo = FoodRepository(session)
    await repo.seed(foods, measures)
    catalog = await repo.load_catalog()

    rice = next(f for f in catalog.foods if f.code == "rice_white_cooked")
    ladle = next(m for m in catalog.measures_for(rice.id) if m.name_ru == "половник")
    result = nutrients_for_measure(rice, ladle, 2)
    assert result.kcal == pytest.approx(260.0)  # 200 g * 130 kcal / 100 g
    assert result.protein_g == pytest.approx(5.0)  # 200 g * 2.5 g (7.1 g dry / yield 2.8)


async def test_cooked_foods_are_linked_to_raw_foods(
    session: AsyncSession, foods: list[FoodRow], measures: list[MeasureRow]
) -> None:
    repo = FoodRepository(session)
    await repo.seed(foods, measures)
    catalog = await repo.load_catalog()
    cooked = [f for f in catalog.foods if f.state is FoodState.COOKED]
    assert len(cooked) >= 20
    for food in cooked:
        assert food.raw_food_id is not None
        assert food.yield_factor is not None
        assert catalog.get_food(food.raw_food_id).state is FoodState.RAW


async def test_seeding_twice_is_idempotent_and_keeps_ids(
    session: AsyncSession, foods: list[FoodRow], measures: list[MeasureRow]
) -> None:
    repo = FoodRepository(session)
    await repo.seed(foods, measures)
    before = {f.code: f.id for f in (await repo.load_catalog()).foods}
    counts = [await count(session, m) for m in (FoodORM, FoodAliasORM, MeasureORM)]

    await repo.seed(foods, measures)

    assert {f.code: f.id for f in (await repo.load_catalog()).foods} == before
    assert [await count(session, m) for m in (FoodORM, FoodAliasORM, MeasureORM)] == counts


async def test_reseeding_updates_changed_values(
    session: AsyncSession, foods: list[FoodRow], measures: list[MeasureRow]
) -> None:
    repo = FoodRepository(session)
    await repo.seed(foods, measures)
    changed = [
        MeasureRow(m.food_code, m.name_ru, 123.0)
        if (m.food_code, m.name_ru) == ("rice_white_cooked", "половник")
        else m
        for m in measures
    ]
    await repo.seed(foods, changed)
    row = (
        await session.execute(
            select(MeasureORM.grams)
            .join(FoodORM)
            .where(FoodORM.code == "rice_white_cooked", MeasureORM.name_ru == "половник")
        )
    ).scalar_one()
    assert row == 123.0


async def test_ambiguous_alias_points_to_several_foods(
    session: AsyncSession, foods: list[FoodRow], measures: list[MeasureRow]
) -> None:
    await FoodRepository(session).seed(foods, measures)
    owners = (
        await session.execute(select(FoodAliasORM.food_id).where(FoodAliasORM.alias == "курица"))
    ).all()
    assert len(owners) >= 2


async def test_deleting_a_food_cascades_to_aliases_and_measures(
    session: AsyncSession, foods: list[FoodRow], measures: list[MeasureRow]
) -> None:
    await FoodRepository(session).seed(foods, measures)
    food = (
        await session.execute(select(FoodORM).where(FoodORM.code == "rice_white_cooked"))
    ).scalar_one()
    food_id = food.id
    assert (
        await session.execute(select(func.count()).where(MeasureORM.food_id == food_id))
    ).scalar_one() > 0

    await session.delete(food)
    await session.commit()

    for model in (MeasureORM, FoodAliasORM):
        left = await session.execute(select(func.count()).where(model.food_id == food_id))
        assert left.scalar_one() == 0


async def test_database_rejects_cooked_food_without_raw_link(session: AsyncSession) -> None:
    session.add(
        FoodORM(
            code="bad", name_ru="Плохой", state="cooked", category="grain",
            kcal_100=100, protein_100=1, fat_100=1, carb_100=20, fiber_100=1,
        )
    )  # fmt: skip
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_database_rejects_measure_of_unknown_food(session: AsyncSession) -> None:
    session.add(MeasureORM(food_id=424242, name_ru="стакан", grams=100.0))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_database_rejects_non_positive_grams_and_duplicate_measures(
    session: AsyncSession, foods: list[FoodRow], measures: list[MeasureRow]
) -> None:
    await FoodRepository(session).seed(foods, measures)
    food_id = (await session.execute(select(FoodORM.id).limit(1))).scalar_one()

    session.add(MeasureORM(food_id=food_id, name_ru="нулевая", grams=0.0))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()

    existing = (
        await session.execute(select(MeasureORM).where(MeasureORM.food_id == food_id).limit(1))
    ).scalar_one()
    session.add(MeasureORM(food_id=food_id, name_ru=existing.name_ru, grams=50.0))
    with pytest.raises(IntegrityError):
        await session.commit()


def test_seed_files_pass_validation_before_seeding(
    foods: list[FoodRow], measures: list[MeasureRow]
) -> None:
    assert validate_data(foods, measures) == []
