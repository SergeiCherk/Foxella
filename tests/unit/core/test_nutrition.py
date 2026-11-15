"""Tests for core.nutrition. Reference sums were computed by hand (see comments)."""

import pytest

from nutrition_bot.core.errors import (
    InconsistentFoodError,
    InvalidQuantityError,
    UnknownFoodError,
    UnknownMeasureError,
)
from nutrition_bot.core.measures import Catalog
from nutrition_bot.core.models import (
    Dish,
    DishItem,
    Food,
    FoodCategory,
    FoodState,
    Meal,
    MealType,
    Measure,
    Nutrients,
)
from nutrition_bot.core.nutrition import (
    ZERO,
    day_nutrients,
    dish_nutrients,
    item_grams,
    item_nutrients,
    meal_nutrients,
    raw_equivalent,
    sum_nutrients,
)


def food(
    id_: int,
    code: str,
    state: FoodState,
    category: FoodCategory,
    n: tuple[float, ...],
    **kw: object,
) -> Food:
    return Food(id_, code, code, state, category, Nutrients(*n), **kw)  # type: ignore[arg-type]


RICE_RAW = food(1, "rice_raw", FoodState.RAW, FoodCategory.GRAIN, (365, 7.1, 0.7, 80.0, 1.3))
RICE = food(
    2, "rice", FoodState.COOKED, FoodCategory.GRAIN, (130, 2.7, 0.3, 28.2, 0.4),
    raw_food_id=1, yield_factor=2.8,
)  # fmt: skip
CHICKEN_RAW = food(3, "chicken_raw", FoodState.RAW, FoodCategory.MEAT, (120, 22.5, 2.6, 0, 0))
CHICKEN = food(
    4, "chicken", FoodState.COOKED, FoodCategory.MEAT, (165, 31.0, 3.6, 0, 0),
    raw_food_id=3, yield_factor=0.75,
)  # fmt: skip
BROCCOLI = food(5, "broccoli", FoodState.READY, FoodCategory.VEGETABLE, (34, 2.8, 0.4, 6.6, 2.6))
OIL = food(6, "olive_oil", FoodState.READY, FoodCategory.FAT, (884, 0, 100.0, 0, 0))

LADLE = Measure(20, 2, "половник", 100.0)  # cooked rice
BREAST = Measure(21, 4, "грудка", 150.0)  # cooked chicken breast
CUP_BROCCOLI = Measure(22, 5, "стакан", 95.0)
TBSP_OIL = Measure(23, 6, "столовая ложка", 14.0)
CUP_RICE_RAW = Measure(24, 1, "стакан", 190.0)

CATALOG = Catalog(
    [RICE_RAW, RICE, CHICKEN_RAW, CHICKEN, BROCCOLI, OIL],
    [LADLE, BREAST, CUP_BROCCOLI, TBSP_OIL, CUP_RICE_RAW],
)

# Chicken 1 breast (150 g cooked): 247.5 kcal, P 46.5, F 5.4, C 0
# Rice 2 ladles (200 g cooked):    260 kcal,   P 5.4,  F 0.6, C 56.4, fibre 0.8
# Broccoli 1 cup (95 g):           32.3 kcal,  P 2.66, F 0.38, C 6.27, fibre 2.47
# Olive oil 0.5 tbsp (7 g):        61.88 kcal, F 7.0
CHICKEN_ITEM = DishItem(4, 21, 1)
RICE_ITEM = DishItem(2, 20, 2)
BROCCOLI_ITEM = DishItem(5, 22, 1)
OIL_ITEM = DishItem(6, 23, 0.5)

DISH = Dish("Курица с рисом и брокколи", (CHICKEN_ITEM, RICE_ITEM, BROCCOLI_ITEM, OIL_ITEM))
DISH_TOTAL = Nutrients(601.68, 54.56, 13.38, 62.67, 3.27)


def assert_nutrients(actual: Nutrients, expected: Nutrients) -> None:
    assert actual.kcal == pytest.approx(expected.kcal)
    assert actual.protein_g == pytest.approx(expected.protein_g)
    assert actual.fat_g == pytest.approx(expected.fat_g)
    assert actual.carb_g == pytest.approx(expected.carb_g)
    assert actual.fiber_g == pytest.approx(expected.fiber_g)


# ------------------------------------------------------------------ items


def test_item_grams_uses_the_measure_weight() -> None:
    assert item_grams(CATALOG, RICE_ITEM) == pytest.approx(200.0)
    assert item_grams(CATALOG, OIL_ITEM) == pytest.approx(7.0)


def test_item_nutrients() -> None:
    assert_nutrients(item_nutrients(CATALOG, CHICKEN_ITEM), Nutrients(247.5, 46.5, 5.4, 0, 0))
    assert_nutrients(item_nutrients(CATALOG, RICE_ITEM), Nutrients(260, 5.4, 0.6, 56.4, 0.8))


def test_item_with_unknown_food_or_measure_raises() -> None:
    with pytest.raises(UnknownFoodError):
        item_nutrients(CATALOG, DishItem(999, 20, 1))
    with pytest.raises(UnknownMeasureError):
        item_nutrients(CATALOG, DishItem(2, 999, 1))
    with pytest.raises(UnknownMeasureError):
        item_grams(CATALOG, DishItem(2, 24, 1))  # measure 24 belongs to RAW rice


def test_item_with_bad_quantity_raises() -> None:
    with pytest.raises(InvalidQuantityError):
        item_nutrients(CATALOG, DishItem(2, 20, -1))
    with pytest.raises(InvalidQuantityError):
        item_nutrients(CATALOG, DishItem(2, 20, float("nan")))


# ------------------------------------------------------ dish / meal / day


def test_dish_is_the_sum_of_its_items() -> None:
    assert_nutrients(dish_nutrients(CATALOG, DISH), DISH_TOTAL)


def test_dish_macro_energy_matches_kcal() -> None:
    n = dish_nutrients(CATALOG, DISH)
    assert 4 * n.protein_g + 4 * n.carb_g + 9 * n.fat_g == pytest.approx(n.kcal, rel=0.03)


def test_empty_dish_is_zero() -> None:
    assert dish_nutrients(CATALOG, Dish("Пусто", ())) == ZERO


def test_meal_and_day_sum_up_and_scale() -> None:
    snack = Dish("Брокколи", (BROCCOLI_ITEM,))
    lunch = Meal(MealType.LUNCH, (DISH, snack))
    dinner = Meal(MealType.DINNER, (DISH,))
    assert_nutrients(
        meal_nutrients(CATALOG, lunch),
        Nutrients(601.68 + 32.3, 54.56 + 2.66, 13.38 + 0.38, 62.67 + 6.27, 3.27 + 2.47),
    )
    day = day_nutrients(CATALOG, [lunch, dinner])
    assert day.kcal == pytest.approx(601.68 * 2 + 32.3)


def test_day_without_meals_is_zero() -> None:
    assert day_nutrients(CATALOG, []) == ZERO


def test_doubling_the_quantity_doubles_the_nutrients() -> None:
    single = item_nutrients(CATALOG, RICE_ITEM)
    double = item_nutrients(CATALOG, DishItem(2, 20, 4))
    assert double.kcal == pytest.approx(2 * single.kcal)
    assert double.fiber_g == pytest.approx(2 * single.fiber_g)


def test_sum_nutrients_of_nothing_and_of_two() -> None:
    assert sum_nutrients([]) == ZERO
    total = sum_nutrients([Nutrients(1, 2, 3, 4, 5), Nutrients(10, 20, 30, 40, 50)])
    assert total == Nutrients(11, 22, 33, 44, 55)


# --------------------------------------------------- raw vs cooked weight


def test_cooked_rice_converts_to_dry_rice() -> None:
    result = raw_equivalent(CATALOG, 2, 280.0)  # yield 2.8
    assert result.food is RICE_RAW
    assert result.grams == pytest.approx(100.0)


def test_cooked_chicken_converts_to_more_raw_chicken() -> None:
    result = raw_equivalent(CATALOG, 4, 150.0)  # yield 0.75: meat loses water
    assert result.food is CHICKEN_RAW
    assert result.grams == pytest.approx(200.0)


@pytest.mark.parametrize("food_id", [1, 3, 5, 6])
def test_raw_and_ready_foods_are_returned_unchanged(food_id: int) -> None:
    result = raw_equivalent(CATALOG, food_id, 123.0)
    assert result.food is CATALOG.get_food(food_id)
    assert result.grams == 123.0


def test_raw_equivalent_of_unknown_food_raises() -> None:
    with pytest.raises(UnknownFoodError):
        raw_equivalent(CATALOG, 999, 100.0)


def test_cooked_food_energy_matches_its_raw_equivalent() -> None:
    """150 g of cooked chicken and the 200 g of raw chicken it came from have similar energy."""
    cooked = item_nutrients(CATALOG, CHICKEN_ITEM).kcal  # 247.5
    eq = raw_equivalent(CATALOG, 4, item_grams(CATALOG, CHICKEN_ITEM))
    raw_kcal = eq.food.per_100g.kcal * eq.grams / 100  # 240
    assert cooked == pytest.approx(raw_kcal, rel=0.05)


def test_the_same_dish_weight_means_different_calories_raw_vs_cooked() -> None:
    """Why raw and cooked are separate foods: 200 g of dry rice is not 200 g of boiled rice."""
    boiled = item_nutrients(CATALOG, DishItem(2, 20, 2)).kcal  # 200 g cooked
    dry = 200.0 * RICE_RAW.per_100g.kcal / 100
    assert dry > 2.5 * boiled


@pytest.mark.parametrize(
    "broken",
    [
        food(7, "no_link", FoodState.COOKED, FoodCategory.GRAIN, (100, 1, 1, 20, 1)),
        food(
            8, "no_yield", FoodState.COOKED, FoodCategory.GRAIN, (100, 1, 1, 20, 1),
            raw_food_id=1,
        ),
        food(
            9, "zero_yield", FoodState.COOKED, FoodCategory.GRAIN, (100, 1, 1, 20, 1),
            raw_food_id=1, yield_factor=0.0,
        ),
        food(
            10, "ready_as_raw", FoodState.COOKED, FoodCategory.GRAIN, (100, 1, 1, 20, 1),
            raw_food_id=5, yield_factor=2.0,
        ),
    ],
    ids=["no_link", "no_yield", "zero_yield", "points_to_ready_food"],
)  # fmt: skip
def test_broken_cooked_food_raises_inconsistent_error(broken: Food) -> None:
    catalog = Catalog([RICE_RAW, BROCCOLI, broken], [])
    with pytest.raises(InconsistentFoodError) as exc:
        raw_equivalent(catalog, broken.id, 100.0)
    assert exc.value.food_id == broken.id
