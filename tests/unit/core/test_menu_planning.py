"""Tests for the multi-day menu (core.menu.build_menu), food availability and the target
adjustment (core.slip.apply_adjustment), on the real catalog."""

import pytest

from nutrition_bot.config import MenuConfig, NormsConfig
from nutrition_bot.core.errors import (
    InvalidMenuRequestError,
    InvalidQuantityError,
    UnknownFoodError,
)
from nutrition_bot.core.menu import build_menu, menu_food_ids
from nutrition_bot.core.models import (
    ActivityLevel,
    FoodCategory,
    FoodState,
    Goal,
    MealType,
    Profile,
    Sex,
)
from nutrition_bot.core.norms import calculate_daily_norm
from nutrition_bot.core.slip import apply_adjustment
from nutrition_bot.services.llm import FakeLLM
from tests.catalog_helpers import real_catalog

CATALOG, IDS = real_catalog()
NORM = calculate_daily_norm(
    Profile(Sex.FEMALE, 32, 168.0, 64.5, ActivityLevel.LIGHT, Goal.LOSE), NormsConfig()
)
CFG = MenuConfig()


# ---------------------------------------------------------------- availability


def test_any_product_means_every_cooked_or_ready_food() -> None:
    ids = menu_food_ids(CATALOG)
    assert ids == tuple(
        sorted(
            f.id
            for f in CATALOG.foods
            if f.state is not FoodState.RAW and f.category is not FoodCategory.DISH
        )
    )
    assert IDS["borscht"] not in ids  # ready dishes are for "I ate", not for menus
    assert IDS["rice_white_raw"] not in ids
    assert IDS["rice_white_cooked"] in ids


def test_a_raw_product_is_replaced_by_its_cooked_versions() -> None:
    assert menu_food_ids(CATALOG, [IDS["rice_white_raw"]]) == (IDS["rice_white_cooked"],)
    assert menu_food_ids(CATALOG, [IDS["egg_raw"]]) == (IDS["egg_boiled"],)


def test_ready_and_cooked_products_stand_for_themselves() -> None:
    ids = [IDS["banana"], IDS["rice_white_cooked"], IDS["banana"]]
    assert menu_food_ids(CATALOG, ids) == tuple(sorted({IDS["banana"], IDS["rice_white_cooked"]}))


def test_an_empty_list_is_not_the_same_as_any() -> None:
    assert menu_food_ids(CATALOG, []) == ()


def test_unknown_product_is_an_error() -> None:
    with pytest.raises(UnknownFoodError):
        menu_food_ids(CATALOG, [999999])


# ------------------------------------------------------------ apply_adjustment


def test_adjustment_moves_kcal_and_keeps_the_proportions() -> None:
    target = apply_adjustment(NORM, -100.0)
    assert target.kcal == pytest.approx(NORM.target.kcal - 100)
    ratio = target.kcal / NORM.target.kcal
    assert target.protein_g == pytest.approx(NORM.target.protein_g * ratio)
    assert target.fat_g == pytest.approx(NORM.target.fat_g * ratio)
    assert target.carb_g == pytest.approx(NORM.target.carb_g * ratio)


def test_adjustment_never_goes_below_the_floor() -> None:
    target = apply_adjustment(NORM, -10_000.0)
    assert target.kcal == NORM.floor_kcal
    assert target.kcal >= NORM.floor_kcal


def test_zero_adjustment_is_the_plain_target() -> None:
    assert apply_adjustment(NORM, 0.0) == NORM.target


def test_non_finite_adjustment_is_an_error() -> None:
    with pytest.raises(InvalidQuantityError):
        apply_adjustment(NORM, float("nan"))


# ------------------------------------------------------------------ build_menu


async def test_menu_has_the_requested_days_and_all_meals() -> None:
    menu = await build_menu(FakeLLM(), CATALOG, NORM, 3, menu_food_ids(CATALOG), CFG)
    assert len(menu) == 3
    for day in menu:
        assert [r.meal.meal_type for r in day] == [MealType(v) for v in CFG.meal_order]


async def test_dishes_do_not_repeat_within_a_day_and_rarely_across_days() -> None:
    """Built-in dishes are few (14), so a repeat on day 3 is possible; a real LLM adds variety."""
    menu = await build_menu(FakeLLM(), CATALOG, NORM, 3, menu_food_ids(CATALOG), CFG)
    for day in menu:
        day_names = [d.name for r in day for d in r.meal.dishes]
        assert len(day_names) == len(set(day_names))
    names = [d.name for day in menu for r in day for d in r.meal.dishes]
    assert len(set(names)) >= len(names) - 2


async def test_day_kcal_follow_the_norm() -> None:
    menu = await build_menu(FakeLLM(), CATALOG, NORM, 1, menu_food_ids(CATALOG), CFG)
    total = sum(r.nutrients.kcal for r in menu[0])
    assert total == pytest.approx(NORM.target.kcal, rel=0.12)


async def test_adjustments_lower_only_the_first_days_and_respect_the_floor() -> None:
    plain = await build_menu(FakeLLM(), CATALOG, NORM, 3, menu_food_ids(CATALOG), CFG)
    cut = await build_menu(
        FakeLLM(), CATALOG, NORM, 3, menu_food_ids(CATALOG), CFG, adjustments=[-150.0, -10_000.0]
    )
    totals = [sum(r.nutrients.kcal for r in day) for day in cut]
    reference = [sum(r.nutrients.kcal for r in day) for day in plain]
    assert totals[0] < reference[0] - 50
    assert totals[1] >= NORM.floor_kcal * 0.88  # planned at the floor, within meal tolerance
    # the third day is planned at the normal target (within the meal tolerance), not lowered
    assert totals[2] == pytest.approx(NORM.target.kcal, rel=CFG.meal_tolerance)
    assert totals[2] > totals[0]


@pytest.mark.parametrize("days", [0, 4, -1])
async def test_days_out_of_range_are_refused(days: int) -> None:
    with pytest.raises(InvalidMenuRequestError):
        await build_menu(FakeLLM(), CATALOG, NORM, days, menu_food_ids(CATALOG), CFG)
