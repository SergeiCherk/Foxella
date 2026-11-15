"""What is missing in the diet: vegetables and fruit, protein, fibre. Pure functions, no I/O.

Hints carry no numbers on purpose: the bot never shows grams, and the thresholds are tuned in
``BalanceConfig``. Two checks exist: one for a planned day of meals and one for the plain list
of products the user has (the pantry).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from nutrition_bot.config import BalanceConfig
from nutrition_bot.core.measures import Catalog
from nutrition_bot.core.models import FoodCategory, Meal, MealType, Nutrients
from nutrition_bot.core.nutrition import item_grams, meal_nutrients, sum_nutrients


class HintKind(StrEnum):
    """What the user is short of."""

    VEG_FRUIT = "veg_fruit"  # vegetables and fruit (potatoes do not count)
    PROTEIN_MEAL = "protein_meal"  # one main meal has little protein; see ``meal_type``
    PROTEIN_DAY = "protein_day"  # the whole day (or the pantry) has little protein
    FIBER = "fiber"  # little fibre although vegetables and fruit look fine


@dataclass(frozen=True, slots=True)
class BalanceHint:
    """One suggestion. ``meal_type`` is set only for ``PROTEIN_MEAL``."""

    kind: HintKind
    meal_type: MealType | None = None


def _veg_fruit_grams(catalog: Catalog, meals: Iterable[Meal], config: BalanceConfig) -> float:
    categories = {FoodCategory(value) for value in config.veg_fruit_categories}
    total = 0.0
    for meal in meals:
        for dish in meal.dishes:
            for item in dish.items:
                if catalog.get_food(item.food_id).category in categories:
                    total += item_grams(catalog, item)
    return total


def fiber_target_g(planned_kcal: float, config: BalanceConfig) -> float:
    """Fibre bar for a day: the WHO value, scaled down proportionally below the reference kcal."""
    share = min(1.0, max(planned_kcal, 0.0) / config.fiber_reference_kcal)
    return config.fiber_min_g * share


def analyze_day(
    catalog: Catalog,
    meals: Sequence[Meal],
    target: Nutrients,
    config: BalanceConfig,
) -> tuple[BalanceHint, ...]:
    """Hints for one planned day. An empty day has nothing to analyse and gives no hints.

    Order: protein, then vegetables and fruit, then fibre. The fibre hint appears only when the
    vegetable hint does not, because "eat more vegetables" already covers a fibre shortage.
    """
    if not meals:
        return ()
    hints: list[BalanceHint] = []

    checked = set(config.protein_checked_meals)
    per_meal = [
        BalanceHint(HintKind.PROTEIN_MEAL, meal.meal_type)
        for meal in meals
        if meal.meal_type.value in checked
        and meal_nutrients(catalog, meal).protein_g < config.protein_min_per_meal_g
    ]
    hints.extend(per_meal)
    day = sum_nutrients(meal_nutrients(catalog, meal) for meal in meals)
    if not per_meal and day.protein_g < target.protein_g * config.protein_day_min_share:
        hints.append(BalanceHint(HintKind.PROTEIN_DAY))

    veg_short = _veg_fruit_grams(catalog, meals, config) < config.veg_fruit_min_g
    if veg_short:
        hints.append(BalanceHint(HintKind.VEG_FRUIT))
    elif day.fiber_g < fiber_target_g(target.kcal, config):
        hints.append(BalanceHint(HintKind.FIBER))
    return tuple(hints)


def pantry_hints(
    catalog: Catalog,
    food_ids: Iterable[int],
    config: BalanceConfig,
) -> tuple[BalanceHint, ...]:
    """Hints for the products the user listed. An empty list gives no hints.

    Looks only at kinds of food present, not at amounts: is there a protein source, any
    vegetables or fruit, any fibre-rich food. Raises ``UnknownFoodError`` for an unknown id.
    """
    foods = [catalog.get_food(food_id) for food_id in set(food_ids)]
    if not foods:
        return ()
    protein_cats = {FoodCategory(v) for v in config.protein_source_categories}
    veg_cats = {FoodCategory(v) for v in config.veg_fruit_categories}

    hints: list[BalanceHint] = []
    if not any(f.category in protein_cats for f in foods):
        hints.append(BalanceHint(HintKind.PROTEIN_DAY))
    if not any(f.category in veg_cats for f in foods):
        hints.append(BalanceHint(HintKind.VEG_FRUIT))
    elif not any(f.per_100g.fiber_g >= config.fiber_source_min_per_100g for f in foods):
        hints.append(BalanceHint(HintKind.FIBER))
    return tuple(hints)
