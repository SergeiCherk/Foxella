"""Nutrients of dishes, meals and days, and raw vs cooked weight. Pure functions."""

import math
from collections.abc import Iterable
from dataclasses import dataclass

from nutrition_bot.core.errors import InconsistentFoodError
from nutrition_bot.core.measures import Catalog, measure_to_grams, nutrients_for_measure
from nutrition_bot.core.models import Dish, DishItem, Food, FoodState, Meal, Nutrients

ZERO = Nutrients(0.0, 0.0, 0.0, 0.0, 0.0)


@dataclass(frozen=True, slots=True)
class RawEquivalent:
    """The raw food and weight that a given weight of a food corresponds to."""

    food: Food
    grams: float


def sum_nutrients(parts: Iterable[Nutrients]) -> Nutrients:
    """Add nutrients together. An empty input gives zeros."""
    items = list(parts)
    return Nutrients(
        kcal=math.fsum(p.kcal for p in items),
        protein_g=math.fsum(p.protein_g for p in items),
        fat_g=math.fsum(p.fat_g for p in items),
        carb_g=math.fsum(p.carb_g for p in items),
        fiber_g=math.fsum(p.fiber_g for p in items),
    )


def item_grams(catalog: Catalog, item: DishItem) -> float:
    """Weight in grams of a dish item, in the state of its food (cooked stays cooked)."""
    measure = catalog.get_measure(item.food_id, item.measure_id)
    return measure_to_grams(measure, item.quantity)


def item_nutrients(catalog: Catalog, item: DishItem) -> Nutrients:
    """Nutrients of one dish item; raises for an unknown food, foreign measure or bad quantity."""
    food = catalog.get_food(item.food_id)
    measure = catalog.get_measure(item.food_id, item.measure_id)
    return nutrients_for_measure(food, measure, item.quantity)


def dish_nutrients(catalog: Catalog, dish: Dish) -> Nutrients:
    """Total nutrients of a dish (the sum of its items)."""
    return sum_nutrients(item_nutrients(catalog, item) for item in dish.items)


def meal_nutrients(catalog: Catalog, meal: Meal) -> Nutrients:
    """Total nutrients of a meal (the sum of its dishes)."""
    return sum_nutrients(dish_nutrients(catalog, dish) for dish in meal.dishes)


def day_nutrients(catalog: Catalog, meals: Iterable[Meal]) -> Nutrients:
    """Total nutrients of a day (the sum of its meals)."""
    return sum_nutrients(meal_nutrients(catalog, meal) for meal in meals)


def raw_equivalent(catalog: Catalog, food_id: int, grams: float) -> RawEquivalent:
    """Convert a weight of a food to the raw food you have to buy.

    A cooked food is divided by its ``yield_factor`` (cooked grams per raw gram) and mapped to
    its raw food: 280 g of cooked rice with yield 2.8 means 100 g of dry rice. Raw and ready
    foods are returned unchanged.
    """
    food = catalog.get_food(food_id)
    if food.state is not FoodState.COOKED:
        return RawEquivalent(food, grams)
    if food.raw_food_id is None or food.yield_factor is None or food.yield_factor <= 0:
        raise InconsistentFoodError(food.id, "cooked food needs a raw food and a positive yield")
    raw = catalog.get_food(food.raw_food_id)
    if raw.state is not FoodState.RAW:
        raise InconsistentFoodError(food.id, f"raw_food_id {raw.id} does not point to a raw food")
    return RawEquivalent(raw, grams / food.yield_factor)
