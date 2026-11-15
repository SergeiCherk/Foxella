"""Shopping list built from menus. Pure functions, no I/O.

Everything the menus need is summed, cooked foods are converted to the raw food you actually
buy (280 g of cooked rice -> 100 g of dry rice), and the amount is expressed in household
measures rounded up (whole pieces such as eggs to whole numbers), so the user never sees grams.
"""

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from nutrition_bot.config import ShoppingConfig
from nutrition_bot.core.measures import Catalog, step_for
from nutrition_bot.core.models import Food, Meal, Measure
from nutrition_bot.core.nutrition import item_grams, raw_equivalent

EPS = 1e-9


@dataclass(frozen=True, slots=True)
class ShoppingItem:
    """One line of the list: ``quantity`` household ``measure`` units of ``food``.

    ``grams`` is the exact need, kept for internal use and tests; handlers do not show it.
    ``measure`` is ``None`` only for a food without any household measure (then ``quantity``
    is 0 and the handler should phrase the line without an amount).
    """

    food: Food
    grams: float
    measure: Measure | None
    quantity: float
    is_staple: bool = False  # oil, sugar and the like: "check what you have at home"


def _pick_measure(measures: list[Measure], grams: float) -> Measure | None:
    """The biggest measure that still fits into the need, else the smallest one."""
    if not measures:
        return None
    ordered = sorted(measures, key=lambda m: (m.grams, m.id))
    fitting = [m for m in ordered if m.grams <= grams + EPS]
    return fitting[-1] if fitting else ordered[0]


def _round_up(quantity: float, step: float) -> float:
    return math.ceil(quantity / step - EPS) * step


def _category_rank(food: Food, config: ShoppingConfig) -> int:
    order = config.category_order
    value = food.category.value
    return order.index(value) if value in order else len(order)


def build_shopping_list(
    catalog: Catalog,
    days: Iterable[Iterable[Meal]],
    config: ShoppingConfig,
    owned_food_ids: Iterable[int] = (),
    staple_food_ids: Iterable[int] = (),
) -> tuple[ShoppingItem, ...]:
    """Sum the menus of several days into a list of what to buy.

    ``owned_food_ids`` are products the user already has: they are left out (a cooked food and
    its raw food count as the same product). ``staple_food_ids`` are foods that most kitchens
    have; their lines are marked ``is_staple`` so they can be shown as "check at home". Empty
    menus give an empty list. Raises the usual catalog errors for an unknown food or measure.
    """
    owned = {raw_equivalent(catalog, food_id, 0.0).food.id for food_id in owned_food_ids}
    staples = {raw_equivalent(catalog, food_id, 0.0).food.id for food_id in staple_food_ids}
    needed: dict[int, list[float]] = defaultdict(list)
    foods: dict[int, Food] = {}
    for day in days:
        for meal in day:
            for dish in meal.dishes:
                for item in dish.items:
                    raw = raw_equivalent(catalog, item.food_id, item_grams(catalog, item))
                    needed[raw.food.id].append(raw.grams)
                    foods[raw.food.id] = raw.food

    lines: list[ShoppingItem] = []
    for food_id, parts in needed.items():
        grams = math.fsum(parts)
        if food_id in owned or grams <= 0:
            continue
        food = foods[food_id]
        measure = _pick_measure(catalog.measures_for(food_id), grams)
        quantity = (
            0.0
            if measure is None
            else _round_up(
                grams / measure.grams,
                step_for(measure, config.quantity_step, config.whole_measures),
            )
        )
        lines.append(ShoppingItem(food, grams, measure, quantity, food_id in staples))
    lines.sort(key=lambda line: (_category_rank(line.food, config), line.food.name_ru))
    return tuple(lines)
