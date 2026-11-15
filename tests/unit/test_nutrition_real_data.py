"""core.nutrition on the real foods.csv / measures.csv (loaded without a database)."""

import pytest

from nutrition_bot.core.measures import Catalog
from nutrition_bot.core.models import (
    Dish,
    DishItem,
    FoodState,
)
from nutrition_bot.core.nutrition import dish_nutrients, item_grams, raw_equivalent
from tests.catalog_helpers import real_catalog


@pytest.fixture(scope="module")
def real() -> tuple[Catalog, dict[str, int]]:
    return real_catalog()


def measure_id(catalog: Catalog, food_id: int, name: str) -> int:
    return next(m.id for m in catalog.measures_for(food_id) if m.name_ru == name)


def test_every_cooked_food_has_energy_close_to_its_raw_equivalent(
    real: tuple[Catalog, dict[str, int]],
) -> None:
    catalog, _ = real
    cooked = [f for f in catalog.foods if f.state is FoodState.COOKED]
    assert len(cooked) >= 20
    for food in cooked:
        eq = raw_equivalent(catalog, food.id, 100.0)
        assert eq.food.state is FoodState.RAW
        raw_kcal = eq.food.per_100g.kcal * eq.grams / 100
        assert raw_kcal == pytest.approx(food.per_100g.kcal, rel=0.30), food.code


def test_two_ladles_of_rice_need_about_seventy_grams_of_dry_rice(
    real: tuple[Catalog, dict[str, int]],
) -> None:
    catalog, ids = real
    rice = ids["rice_white_cooked"]
    grams = item_grams(catalog, DishItem(rice, measure_id(catalog, rice, "половник"), 2))
    eq = raw_equivalent(catalog, rice, grams)
    assert eq.food.code == "rice_white_raw"
    assert eq.grams == pytest.approx(200 / 2.8)


def test_a_realistic_lunch_has_plausible_nutrients(real: tuple[Catalog, dict[str, int]]) -> None:
    catalog, ids = real

    def item(code: str, measure: str, quantity: float) -> DishItem:
        return DishItem(ids[code], measure_id(catalog, ids[code], measure), quantity)

    dish = Dish(
        "Курица с гречкой и огурцом",
        (
            item("chicken_breast_cooked", "грудка", 1),
            item("buckwheat_cooked", "половник", 2),
            item("cucumber", "огурец", 1),
            item("sunflower_oil", "чайная ложка", 1),
        ),
    )
    n = dish_nutrients(catalog, dish)
    assert 450 <= n.kcal <= 600
    assert n.protein_g >= 50
    assert 4 * n.protein_g + 4 * n.carb_g + 9 * n.fat_g == pytest.approx(n.kcal, rel=0.10)
