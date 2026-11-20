"""Per-user data: profile, pantry, adjustments and the last menu. Returns ``core`` types."""

import json
import logging
import math
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
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
from nutrition_bot.db.models import MenuORM, UserFoodORM, UserORM

logger = logging.getLogger(__name__)

Day = tuple[Meal, ...]


def menu_to_json(days: Sequence[Sequence[Meal]]) -> str:
    """Serialise a multi-day menu. Only ids, quantities and texts are stored, never nutrients."""
    payload = [
        [
            {
                "meal_type": meal.meal_type.value,
                "dishes": [
                    {
                        "name": dish.name,
                        "recipe": dish.recipe_text,
                        "items": [[i.food_id, i.measure_id, i.quantity] for i in dish.items],
                    }
                    for dish in meal.dishes
                ],
            }
            for meal in day
        ]
        for day in days
    ]
    return json.dumps(payload, ensure_ascii=False)


def menu_from_json(text: str) -> list[Day] | None:
    """Parse a stored menu; ``None`` if the text is damaged (the caller asks for a new menu)."""
    try:
        raw: Any = json.loads(text)
        return [
            tuple(
                Meal(
                    MealType(meal["meal_type"]),
                    tuple(
                        Dish(
                            str(d["name"]),
                            tuple(DishItem(int(a), int(b), float(c)) for a, b, c in d["items"]),
                            str(d["recipe"]),
                        )
                        for d in meal["dishes"]
                    ),
                )
                for meal in day
            )
            for day in raw
        ]
    except (ValueError, TypeError, KeyError):
        logger.warning("a stored menu could not be read and will be ignored")
        return None


def _adjust_from_json(text: str) -> list[float]:
    try:
        raw: Any = json.loads(text)
        values = [float(v) for v in raw]
    except (ValueError, TypeError):
        return []
    return [v for v in values if math.isfinite(v)]


class UserRepository:
    """Access to everything stored about one Telegram user."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_profile(self, telegram_id: int) -> Profile | None:
        """The saved profile, or ``None`` for a new user."""
        user = await self._session.get(UserORM, telegram_id)
        if user is None:
            return None
        return Profile(
            sex=Sex(user.sex),
            age=user.age,
            height_cm=user.height_cm,
            weight_kg=user.weight_kg,
            activity=ActivityLevel(user.activity),
            goal=Goal(user.goal),
        )

    async def save_profile(
        self, telegram_id: int, profile: Profile, accepted_at: datetime | None = None
    ) -> None:
        """Create or update the profile. Pantry and menu of an existing user are kept.

        ``accepted_at`` (when the disclaimer was confirmed) is stored only if none is yet.
        """
        user = await self._session.get(UserORM, telegram_id)
        if user is None:
            user = UserORM(telegram_id=telegram_id, pending_adjust="[]")
            self._session.add(user)
        user.sex = profile.sex.value
        user.age = profile.age
        user.height_cm = profile.height_cm
        user.weight_kg = profile.weight_kg
        user.activity = profile.activity.value
        user.goal = profile.goal.value
        if user.disclaimer_accepted_at is None:
            user.disclaimer_accepted_at = accepted_at
        await self._session.commit()

    async def has_accepted_disclaimer(self, telegram_id: int) -> bool:
        """``True`` if this person confirmed the disclaimer."""
        user = await self._session.get(UserORM, telegram_id)
        return user is not None and user.disclaimer_accepted_at is not None

    async def accept_disclaimer(self, telegram_id: int) -> None:
        """Record the confirmation now (people from before the button existed). Idempotent."""
        user = await self._session.get(UserORM, telegram_id)
        if user is not None and user.disclaimer_accepted_at is None:
            user.disclaimer_accepted_at = datetime.now(UTC)
            await self._session.commit()

    async def delete_all(self, telegram_id: int) -> bool:
        """Remove the user and, by cascade, the pantry and the menu. ``True`` if there was one."""
        user = await self._session.get(UserORM, telegram_id)
        if user is None:
            return False
        await self._session.execute(delete(UserORM).where(UserORM.telegram_id == telegram_id))
        await self._session.commit()
        return True

    async def get_food_choices(self, telegram_id: int) -> dict[str, int]:
        """Remembered answers to "which one?": options key (see ``choice_key``) -> food id."""
        user = await self._session.get(UserORM, telegram_id)
        if user is None:
            return {}
        try:
            raw = json.loads(user.food_choices or "{}")
        except ValueError:
            logger.warning("unreadable food choices of a user, ignoring them")
            return {}
        if not isinstance(raw, dict):
            return {}
        return {str(k): v for k, v in raw.items() if isinstance(v, int)}

    async def remember_food_choice(self, telegram_id: int, key: str, food_id: int) -> None:
        """Remember that for these options the person means ``food_id``."""
        user = await self._session.get(UserORM, telegram_id)
        if user is None:
            return
        choices = await self.get_food_choices(telegram_id)
        choices[key] = food_id
        user.food_choices = json.dumps(choices, sort_keys=True)
        await self._session.commit()

    async def get_restrictions(self, telegram_id: int) -> list[str]:
        """Food restriction codes ("meat", "nuts", ...); empty for none or an unknown user."""
        user = await self._session.get(UserORM, telegram_id)
        if user is None or not user.restrictions:
            return []
        return [code for code in user.restrictions.split(",") if code]

    async def set_restrictions(self, telegram_id: int, codes: Iterable[str]) -> None:
        """Replace the restrictions (kept in the given order, without repeats)."""
        user = await self._session.get(UserORM, telegram_id)
        if user is None:
            return
        user.restrictions = ",".join(dict.fromkeys(c for c in codes if c and "," not in c))
        await self._session.commit()

    async def get_pantry(self, telegram_id: int) -> list[int]:
        """Ids of the products the user listed last time (empty: none, i.e. "any")."""
        rows = await self._session.scalars(
            select(UserFoodORM.food_id)
            .where(UserFoodORM.telegram_id == telegram_id)
            .order_by(UserFoodORM.food_id)
        )
        return list(rows.all())

    async def set_pantry(self, telegram_id: int, food_ids: Iterable[int]) -> None:
        """Replace the pantry. The user must exist."""
        await self._session.execute(
            delete(UserFoodORM).where(UserFoodORM.telegram_id == telegram_id)
        )
        for food_id in sorted(set(food_ids)):
            self._session.add(UserFoodORM(telegram_id=telegram_id, food_id=food_id))
        await self._session.commit()

    async def get_adjustments(self, telegram_id: int) -> list[float]:
        """kcal changes for the next days (negative: eat a little less), oldest first."""
        user = await self._session.get(UserORM, telegram_id)
        return [] if user is None else _adjust_from_json(user.pending_adjust)

    async def set_adjustments(self, telegram_id: int, deltas: Sequence[float]) -> None:
        """Store the kcal changes for the next menu (an empty list clears them)."""
        user = await self._session.get(UserORM, telegram_id)
        if user is None:
            return
        user.pending_adjust = json.dumps([float(d) for d in deltas])
        await self._session.commit()

    async def save_menu(self, telegram_id: int, days: Sequence[Sequence[Meal]]) -> None:
        """Keep the latest menu (the previous one is replaced)."""
        menu = await self._session.get(MenuORM, telegram_id)
        if menu is None:
            menu = MenuORM(telegram_id=telegram_id, payload="")
            self._session.add(menu)
        menu.payload = menu_to_json(days)
        menu.created_at = datetime.now(UTC)  # a new menu starts today
        await self._session.commit()

    async def get_menu_created_at(self, telegram_id: int) -> datetime | None:
        """When the latest menu was made (UTC), or ``None`` if there is no menu."""
        menu = await self._session.get(MenuORM, telegram_id)
        if menu is None:
            return None
        created = menu.created_at
        return created if created.tzinfo is not None else created.replace(tzinfo=UTC)

    async def get_menu(self, telegram_id: int) -> list[Day] | None:
        """The latest menu, or ``None`` if there is none or it cannot be read."""
        menu = await self._session.get(MenuORM, telegram_id)
        return None if menu is None else menu_from_json(menu.payload)
