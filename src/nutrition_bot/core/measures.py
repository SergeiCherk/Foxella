"""Household measures -> grams -> nutrients. Pure functions and an in-memory catalog."""

import math
from collections.abc import Collection, Iterable

from nutrition_bot.core.errors import (
    InvalidQuantityError,
    UnknownFoodError,
    UnknownMeasureError,
)
from nutrition_bot.core.models import Food, Measure, Nutrients

GRAMS_PER_100 = 100.0


class Catalog:
    """Foods and their household measures, indexed for fast lookup."""

    def __init__(self, foods: Iterable[Food], measures: Iterable[Measure]) -> None:
        self._foods: dict[int, Food] = {f.id: f for f in foods}
        self._measures: dict[int, Measure] = {m.id: m for m in measures}
        self._by_food: dict[int, list[Measure]] = {}
        for measure in self._measures.values():
            self._by_food.setdefault(measure.food_id, []).append(measure)

    def get_food(self, food_id: int) -> Food:
        """Return the food or raise ``UnknownFoodError``."""
        try:
            return self._foods[food_id]
        except KeyError:
            raise UnknownFoodError(food_id) from None

    def get_measure(self, food_id: int, measure_id: int) -> Measure:
        """Return a measure that belongs to the food, else raise ``UnknownMeasureError``."""
        self.get_food(food_id)
        measure = self._measures.get(measure_id)
        if measure is None or measure.food_id != food_id:
            raise UnknownMeasureError(measure_id, food_id)
        return measure

    def measures_for(self, food_id: int) -> list[Measure]:
        """All measures of a food (empty list if it has none); raises for an unknown food."""
        self.get_food(food_id)
        return list(self._by_food.get(food_id, []))

    @property
    def foods(self) -> list[Food]:
        """All foods in the catalog."""
        return list(self._foods.values())


def _check_quantity(quantity: float) -> None:
    if not math.isfinite(quantity) or quantity < 0:
        raise InvalidQuantityError(quantity)


def step_for(measure: Measure, step: float, whole_measures: Collection[str]) -> float:
    """Rounding step for a measure: 1 for whole pieces (eggs, tomatoes), else the given ``step``."""
    return 1.0 if measure.name_ru in whole_measures else step


def measure_to_grams(measure: Measure, quantity: float) -> float:
    """Grams in ``quantity`` household measures (fractions such as 0.5 are allowed)."""
    _check_quantity(quantity)
    return measure.grams * quantity


def nutrients_for_grams(food: Food, grams: float) -> Nutrients:
    """Nutrients of ``grams`` of the food, scaled from its per-100 g values."""
    _check_quantity(grams)
    k = grams / GRAMS_PER_100
    n = food.per_100g
    return Nutrients(
        kcal=n.kcal * k,
        protein_g=n.protein_g * k,
        fat_g=n.fat_g * k,
        carb_g=n.carb_g * k,
        fiber_g=n.fiber_g * k,
    )


def nutrients_for_measure(food: Food, measure: Measure, quantity: float) -> Nutrients:
    """Nutrients of ``quantity`` household measures of a food (measure -> grams -> nutrients)."""
    if measure.food_id != food.id:
        raise UnknownMeasureError(measure.id, food.id)
    return nutrients_for_grams(food, measure_to_grams(measure, quantity))
