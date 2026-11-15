"""UserRepository against a real SQLite file with the real schema."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nutrition_bot.core.models import (
    ActivityLevel,
    Dish,
    DishItem,
    Goal,
    Meal,
    MealType,
    Profile,
    Sex,
)
from nutrition_bot.db.models import Base, MenuORM, UserFoodORM, UserORM
from nutrition_bot.db.repositories.foods import FoodRepository
from nutrition_bot.db.repositories.users import UserRepository, menu_from_json, menu_to_json
from nutrition_bot.db.seed import load_foods, load_measures
from nutrition_bot.db.session import create_engine, create_session_factory

PROFILE = Profile(Sex.MALE, 41, 181.5, 82.0, ActivityLevel.MODERATE, Goal.GAIN)
MENU = [
    (
        Meal(
            MealType.BREAKFAST,
            (Dish("Каша", (DishItem(1, 2, 1.5), DishItem(3, 4, 0.25)), "Сварите кашу."),),
        ),
    ),
    (Meal(MealType.DINNER, (Dish("Рыба", (DishItem(5, 6, 2.0),), ""),)),),
]


@pytest.fixture
async def session(tmp_path: Path) -> AsyncIterator[AsyncSession]:
    engine = create_engine(f"sqlite+aiosqlite:///{(tmp_path / 'u.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as db:
        await FoodRepository(db).seed(load_foods(), load_measures())
        yield db
    await engine.dispose()


async def count(session: AsyncSession, model: type) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def test_unknown_user_has_nothing(session: AsyncSession) -> None:
    repo = UserRepository(session)
    assert await repo.get_profile(7) is None
    assert await repo.get_menu(7) is None
    assert await repo.get_pantry(7) == []
    assert await repo.get_adjustments(7) == []
    assert await repo.delete_all(7) is False
    await repo.set_adjustments(7, [1.0])  # silently ignored: there is no such user


async def test_profile_roundtrip_and_update(session: AsyncSession) -> None:
    repo = UserRepository(session)
    await repo.save_profile(5_000_000_000, PROFILE)  # ids above 32 bits are normal in Telegram
    assert await repo.get_profile(5_000_000_000) == PROFILE
    changed = Profile(Sex.MALE, 42, 181.5, 79.0, ActivityLevel.HIGH, Goal.LOSE)
    await repo.save_profile(5_000_000_000, changed)
    assert await repo.get_profile(5_000_000_000) == changed
    assert await count(session, UserORM) == 1


async def test_updating_the_profile_keeps_pantry_and_menu(session: AsyncSession) -> None:
    repo = UserRepository(session)
    await repo.save_profile(1, PROFILE)
    await repo.set_pantry(1, [1, 2])
    await repo.save_menu(1, MENU)
    await repo.save_profile(
        1, Profile(Sex.MALE, 41, 181.5, 80.0, ActivityLevel.MODERATE, Goal.GAIN)
    )
    assert await repo.get_pantry(1) == [1, 2]
    assert await repo.get_menu(1) == MENU


async def test_pantry_is_replaced_and_deduplicated(session: AsyncSession) -> None:
    repo = UserRepository(session)
    await repo.save_profile(1, PROFILE)
    await repo.set_pantry(1, [3, 1, 3, 2])
    assert await repo.get_pantry(1) == [1, 2, 3]
    await repo.set_pantry(1, [9])
    assert await repo.get_pantry(1) == [9]
    await repo.set_pantry(1, [])
    assert await repo.get_pantry(1) == []


async def test_adjustments_roundtrip(session: AsyncSession) -> None:
    repo = UserRepository(session)
    await repo.save_profile(1, PROFILE)
    assert await repo.get_adjustments(1) == []
    await repo.set_adjustments(1, [-100.0, -50.5, 0.0])
    assert await repo.get_adjustments(1) == [-100.0, -50.5, 0.0]
    await repo.set_adjustments(1, [])
    assert await repo.get_adjustments(1) == []


@pytest.mark.parametrize("junk", ["nope", '{"a": 1}', '["x"]', "[1, null]", "[1e999]"])
async def test_damaged_adjustments_read_as_empty_or_finite(
    session: AsyncSession, junk: str
) -> None:
    repo = UserRepository(session)
    await repo.save_profile(1, PROFILE)
    user = await session.get(UserORM, 1)
    assert user is not None
    user.pending_adjust = junk
    await session.commit()
    assert all(abs(v) < 1e9 for v in await repo.get_adjustments(1))


async def test_menu_roundtrip_and_replace(session: AsyncSession) -> None:
    repo = UserRepository(session)
    await repo.save_profile(1, PROFILE)
    await repo.save_menu(1, MENU)
    assert await repo.get_menu(1) == MENU
    await repo.save_menu(1, MENU[:1])
    assert await repo.get_menu(1) == MENU[:1]
    assert await count(session, MenuORM) == 1


async def test_damaged_menu_reads_as_none(session: AsyncSession) -> None:
    repo = UserRepository(session)
    await repo.save_profile(1, PROFILE)
    await repo.save_menu(1, MENU)
    menu = await session.get(MenuORM, 1)
    assert menu is not None
    menu.payload = "{broken"
    await session.commit()
    assert await repo.get_menu(1) is None


@pytest.mark.parametrize(
    "text", ["", "null", "5", '[[{"meal_type": "brunch", "dishes": []}]]', '[[{"dishes": []}]]']
)
def test_menu_from_json_rejects_bad_payloads(text: str) -> None:
    assert menu_from_json(text) is None


def test_menu_json_keeps_ids_and_texts_but_no_nutrients() -> None:
    text = menu_to_json(MENU)
    assert "kcal" not in text
    assert "Сварите кашу." in text
    assert menu_from_json(text) == MENU


async def test_delete_removes_everything_of_that_user_only(session: AsyncSession) -> None:
    repo = UserRepository(session)
    for user_id in (1, 2):
        await repo.save_profile(user_id, PROFILE)
        await repo.set_pantry(user_id, [1, 2])
        await repo.save_menu(user_id, MENU)
    assert await repo.delete_all(1) is True
    assert await repo.get_profile(1) is None
    assert await repo.get_pantry(1) == []
    assert await repo.get_menu(1) is None
    assert await repo.get_profile(2) == PROFILE
    assert await repo.get_pantry(2) == [1, 2]
    assert await count(session, UserORM) == 1
    assert await count(session, UserFoodORM) == 2
    assert await count(session, MenuORM) == 1


async def test_aliases_are_loaded_with_all_meanings(session: AsyncSession) -> None:
    aliases = await FoodRepository(session).load_aliases()
    assert len(aliases["творог"]) == 3
    assert len(aliases["гречка"]) == 1
    assert all(ids == tuple(sorted(ids)) for ids in aliases.values())
