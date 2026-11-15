"""Tests for core.shopping. Expected numbers were computed by hand (see comments)."""

import pytest

from nutrition_bot.config import ShoppingConfig
from nutrition_bot.core.errors import UnknownFoodError
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
from nutrition_bot.core.shopping import build_shopping_list
from tests.catalog_helpers import real_catalog


def food(id_: int, code: str, state: FoodState, cat: FoodCategory, **kw: object) -> Food:
    return Food(id_, code, code, state, cat, Nutrients(100, 1, 1, 1, 1), **kw)  # type: ignore[arg-type]


RICE_RAW = food(1, "rice_raw", FoodState.RAW, FoodCategory.GRAIN)
RICE = food(2, "rice", FoodState.COOKED, FoodCategory.GRAIN, raw_food_id=1, yield_factor=2.8)
CHICKEN_RAW = food(3, "chicken_raw", FoodState.RAW, FoodCategory.MEAT)
CHICKEN = food(4, "chicken", FoodState.COOKED, FoodCategory.MEAT, raw_food_id=3, yield_factor=0.75)
BROCCOLI = food(5, "broccoli", FoodState.READY, FoodCategory.VEGETABLE)
OIL = food(6, "oil", FoodState.READY, FoodCategory.FAT)
PASTA_RAW = food(7, "pasta_raw", FoodState.RAW, FoodCategory.GRAIN)  # has no measures
PASTA = food(8, "pasta", FoodState.COOKED, FoodCategory.GRAIN, raw_food_id=7, yield_factor=2.0)
APPLE = food(9, "apple", FoodState.READY, FoodCategory.FRUIT)
EGG = food(10, "egg", FoodState.READY, FoodCategory.EGG)

MEASURES = [
    Measure(20, 2, "половник", 100.0),  # cooked rice
    Measure(21, 1, "стакан", 190.0),  # dry rice
    Measure(22, 4, "грудка", 150.0),  # cooked chicken
    Measure(23, 3, "грудка", 200.0),  # raw chicken: large
    Measure(24, 3, "кусок", 50.0),  # raw chicken: small
    Measure(25, 5, "стакан", 95.0),  # broccoli cup
    Measure(26, 5, "кочан", 300.0),  # broccoli head
    Measure(27, 6, "столовая ложка", 14.0),
    Measure(28, 8, "половник", 100.0),  # cooked pasta
    Measure(29, 9, "яблоко", 180.0),
    Measure(30, 10, "яйцо", 50.0),
]
CATALOG = Catalog(
    [RICE_RAW, RICE, CHICKEN_RAW, CHICKEN, BROCCOLI, OIL, PASTA_RAW, PASTA, APPLE, EGG], MEASURES
)
CFG = ShoppingConfig()


def meal(*items: tuple[int, int, float]) -> Meal:
    """One meal; each item is (food id, measure id, quantity)."""
    return Meal(MealType.LUNCH, (Dish("d", tuple(DishItem(f, m, q) for f, m, q in items)),))


def by_code(lines: tuple) -> dict:  # type: ignore[type-arg]
    return {line.food.code: line for line in lines}


def test_no_menus_give_an_empty_list() -> None:
    assert build_shopping_list(CATALOG, [], CFG) == ()
    assert build_shopping_list(CATALOG, [[]], CFG) == ()
    assert build_shopping_list(CATALOG, [[meal()]], CFG) == ()


def test_cooked_food_becomes_raw_food() -> None:
    # 2 ladles = 200 g cooked rice -> 200 / 2.8 = 71.43 g dry rice
    lines = build_shopping_list(CATALOG, [[meal((2, 20, 2.0))]], CFG)
    assert len(lines) == 1
    assert lines[0].food.code == "rice_raw"
    assert lines[0].grams == pytest.approx(200 / 2.8)


def test_small_need_rounds_up_to_half_a_measure() -> None:
    # 71.4 g of dry rice and the only measure is a 190 g cup -> 0.376 -> 0.5 cup
    line = build_shopping_list(CATALOG, [[meal((2, 20, 2.0))]], CFG)[0]
    assert line.measure is not None
    assert line.measure.name_ru == "стакан"
    assert line.quantity == 0.5


def test_amounts_are_summed_over_meals_and_days() -> None:
    day = [meal((4, 22, 1.0)), meal((4, 22, 1.0))]  # 2 breasts cooked = 300 g -> 400 g raw
    lines = build_shopping_list(CATALOG, [day, day], CFG)
    assert lines[0].grams == pytest.approx(800.0)


def test_biggest_measure_that_fits_is_chosen() -> None:
    # 150 g cooked chicken -> 200 g raw: the 200 g "грудка" fits exactly, quantity 1
    line = build_shopping_list(CATALOG, [[meal((4, 22, 1.0))]], CFG)[0]
    assert line.measure is not None
    assert (line.measure.name_ru, line.quantity) == ("грудка", 1.0)
    # 100 g raw chicken -> only the 50 g piece fits: 2 pieces
    small = build_shopping_list(CATALOG, [[meal((4, 22, 0.5))]], CFG)[0]
    assert small.measure is not None
    assert (small.measure.name_ru, small.quantity) == ("кусок", 2.0)


def test_amount_is_rounded_up_and_never_below_the_need() -> None:
    # 2.7 cups = 256.5 g broccoli: the 95 g cup fits (the 300 g head does not): 2.7 -> 3 cups
    line = build_shopping_list(CATALOG, [[meal((5, 25, 2.7))]], CFG)[0]
    assert line.measure is not None
    assert line.quantity == 3.0
    assert line.quantity * line.measure.grams >= line.grams


def test_quantity_step_comes_from_config() -> None:
    cfg = ShoppingConfig(quantity_step=0.25)
    line = build_shopping_list(CATALOG, [[meal((2, 20, 2.0))]], cfg)[0]
    assert line.quantity == 0.5  # 0.376 rounded up to a quarter
    line = build_shopping_list(CATALOG, [[meal((2, 20, 1.2))]], cfg)[0]
    assert line.quantity == 0.25  # 120 g / 2.8 = 42.9 g = 0.226 cup -> one quarter


def test_whole_pieces_are_rounded_up_to_whole_numbers() -> None:
    # 125 g of eggs = 2.5 pieces: a half-step would say 2.5, but one cannot buy half an egg.
    line = build_shopping_list(CATALOG, [[meal((10, 30, 2.5))]], CFG)[0]
    assert line.quantity == 3.0
    # 1.2 apples -> 2 (not 1.5)
    line = build_shopping_list(CATALOG, [[meal((9, 29, 1.2))]], CFG)[0]
    assert line.quantity == 2.0


def test_whole_pieces_exact_count_is_not_bumped_up() -> None:
    line = build_shopping_list(CATALOG, [[meal((10, 30, 2.0))]], CFG)[0]
    assert line.quantity == 2.0


def test_whole_pieces_follow_the_config_list() -> None:
    cfg = ShoppingConfig(whole_measures=())
    line = build_shopping_list(CATALOG, [[meal((10, 30, 2.5))]], cfg)[0]
    assert line.quantity == 2.5


def test_exact_multiple_is_not_bumped_up() -> None:
    # 190 g of dry rice is exactly one cup; 2.8 * 190 = 532 g cooked = 5.32 ladles
    line = build_shopping_list(CATALOG, [[meal((2, 20, 5.32))]], CFG)[0]
    assert line.quantity == 1.0


def test_owned_products_are_left_out_in_either_state() -> None:
    menus = [[meal((2, 20, 2.0), (5, 25, 2.0), (4, 22, 1.0))]]
    assert {x.food.code for x in build_shopping_list(CATALOG, menus, CFG)} == {
        "rice_raw",
        "broccoli",
        "chicken_raw",
    }
    owned_cooked = build_shopping_list(CATALOG, menus, CFG, owned_food_ids=[2])
    assert "rice_raw" not in by_code(owned_cooked)
    owned_raw = build_shopping_list(CATALOG, menus, CFG, owned_food_ids=[3, 5])
    assert set(by_code(owned_raw)) == {"rice_raw"}


def test_everything_owned_gives_an_empty_list() -> None:
    menus = [[meal((2, 20, 2.0), (5, 25, 2.0))]]
    assert build_shopping_list(CATALOG, menus, CFG, owned_food_ids=[1, 5]) == ()


def test_zero_quantity_lines_are_skipped() -> None:
    assert build_shopping_list(CATALOG, [[meal((5, 25, 0.0))]], CFG) == ()


def test_food_without_any_measure_has_no_amount() -> None:
    # cooked pasta has a ladle, but its raw food has no measures at all
    line = build_shopping_list(CATALOG, [[meal((8, 28, 3.0))]], CFG)[0]
    assert line.food.code == "pasta_raw"
    assert (line.measure, line.quantity) == (None, 0.0)
    assert line.grams == pytest.approx(150.0)


def test_lines_follow_category_order_then_name() -> None:
    menus = [[meal((6, 27, 1.0), (2, 20, 2.0), (5, 25, 1.0), (9, 29, 1.0), (4, 22, 1.0))]]
    codes = [x.food.code for x in build_shopping_list(CATALOG, menus, CFG)]
    assert codes == ["broccoli", "apple", "chicken_raw", "rice_raw", "oil"]


def test_unlisted_category_goes_last() -> None:
    cfg = ShoppingConfig(category_order=("vegetable",))
    menus = [[meal((6, 27, 1.0), (5, 25, 1.0))]]
    assert [x.food.code for x in build_shopping_list(CATALOG, menus, cfg)] == ["broccoli", "oil"]


def test_unknown_owned_food_is_an_error() -> None:
    with pytest.raises(UnknownFoodError):
        build_shopping_list(CATALOG, [[meal((5, 25, 1.0))]], CFG, owned_food_ids=[999])


def test_category_order_lists_every_category_once() -> None:
    assert sorted(CFG.category_order) == sorted(c.value for c in FoodCategory)


def test_every_real_food_can_be_bought_in_household_measures() -> None:
    catalog, _ = real_catalog()
    checked = 0
    for f in catalog.foods:
        for measure in catalog.measures_for(f.id):
            dish = Dish("d", (DishItem(f.id, measure.id, 1.0),))
            lines = build_shopping_list(catalog, [[Meal(MealType.LUNCH, (dish,))]], CFG)
            assert len(lines) == 1, f.code
            line = lines[0]
            assert line.measure is not None, f.code
            assert line.quantity > 0, f.code
            assert line.quantity * line.measure.grams >= line.grams - 1e-6, f.code
            checked += 1
    assert checked >= 100
