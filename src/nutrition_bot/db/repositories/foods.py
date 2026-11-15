"""Food catalog repository: seeding from CSV rows and loading the core ``Catalog``."""

from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from nutrition_bot.core.measures import Catalog
from nutrition_bot.core.models import Food, FoodCategory, FoodState, Measure, Nutrients
from nutrition_bot.db.models import FoodAliasORM, FoodORM, MeasureORM
from nutrition_bot.db.seed import FoodRow, MeasureRow


def _to_food(orm: FoodORM) -> Food:
    return Food(
        id=orm.id,
        code=orm.code,
        name_ru=orm.name_ru,
        state=FoodState(orm.state),
        category=FoodCategory(orm.category),
        per_100g=Nutrients(
            kcal=orm.kcal_100,
            protein_g=orm.protein_100,
            fat_g=orm.fat_100,
            carb_g=orm.carb_100,
            fiber_g=orm.fiber_100,
        ),
        raw_food_id=orm.raw_food_id,
        yield_factor=orm.yield_factor,
    )


def _apply(orm: FoodORM, row: FoodRow, raw_food_id: int | None) -> None:
    orm.name_ru = row.name_ru
    orm.state = row.state
    orm.category = row.category
    orm.raw_food_id = raw_food_id
    orm.yield_factor = row.yield_factor
    orm.kcal_100 = row.kcal_100
    orm.protein_100 = row.protein_100
    orm.fat_100 = row.fat_100
    orm.carb_100 = row.carb_100
    orm.fiber_100 = row.fiber_100


class FoodRepository:
    """Access to foods, aliases and measures. Returns ``core`` types, never ORM objects."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def seed(self, foods: Sequence[FoodRow], measures: Sequence[MeasureRow]) -> None:
        """Insert or update foods, aliases and measures (idempotent, never deletes foods).

        Foods are matched by ``code`` and measures by (food, name), so ids that other tables
        refer to stay stable across re-seeding.
        """
        session = self._session
        existing = {f.code: f for f in (await session.scalars(select(FoodORM))).all()}

        # Raw and ready foods first: cooked foods need the id of their raw food.
        for phase_rows in (
            [r for r in foods if r.state != "cooked"],
            [r for r in foods if r.state == "cooked"],
        ):
            for row in phase_rows:
                orm = existing.get(row.code)
                if orm is None:
                    orm = FoodORM(code=row.code)
                    existing[row.code] = orm
                    session.add(orm)
                raw_id = existing[row.raw_code].id if row.raw_code else None
                _apply(orm, row, raw_id)
            await session.flush()

        ids = [existing[r.code].id for r in foods]
        await session.execute(delete(FoodAliasORM).where(FoodAliasORM.food_id.in_(ids)))
        for row in foods:
            for alias in dict.fromkeys(row.aliases):
                session.add(FoodAliasORM(food_id=existing[row.code].id, alias=alias))

        known = {
            (m.food_id, m.name_ru): m for m in (await session.scalars(select(MeasureORM))).all()
        }
        for m in measures:
            food_id = existing[m.food_code].id
            current = known.get((food_id, m.name_ru))
            if current is None:
                session.add(MeasureORM(food_id=food_id, name_ru=m.name_ru, grams=m.grams))
            else:
                current.grams = m.grams
        await session.commit()

    async def load_catalog(self) -> Catalog:
        """Load every food and measure into an in-memory ``Catalog``."""
        foods = (await self._session.scalars(select(FoodORM).order_by(FoodORM.id))).all()
        measures = (await self._session.scalars(select(MeasureORM).order_by(MeasureORM.id))).all()
        return Catalog(
            [_to_food(f) for f in foods],
            [Measure(m.id, m.food_id, m.name_ru, m.grams) for m in measures],
        )

    async def load_aliases(self) -> dict[str, tuple[int, ...]]:
        """Every alias with the ids of the foods it may mean (one alias can mean several)."""
        rows = await self._session.execute(
            select(FoodAliasORM.alias, FoodAliasORM.food_id).order_by(FoodAliasORM.food_id)
        )
        found: dict[str, list[int]] = {}
        for alias, food_id in rows.all():
            found.setdefault(alias, []).append(food_id)
        return {alias: tuple(ids) for alias, ids in found.items()}
