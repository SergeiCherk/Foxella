"""core.menu on the real catalog: fallback dishes, availability and whole days (no network)."""

import pytest

from nutrition_bot.config import MenuConfig
from nutrition_bot.core.measures import Catalog
from nutrition_bot.core.menu import (
    FALLBACK_TEMPLATES,
    MealSource,
    _resolve,
    build_day,
    fallback_dishes,
    within_tolerance,
)
from nutrition_bot.core.models import Dish, MealType, Nutrients
from nutrition_bot.core.nutrition import dish_nutrients
from nutrition_bot.services.llm import FakeLLM, dishes_to_json
from tests.catalog_helpers import cooked_or_ready_ids, real_catalog

CFG = MenuConfig()
ALL_MEALS = [MealType.BREAKFAST, MealType.LUNCH, MealType.DINNER, MealType.SNACK]


@pytest.fixture(scope="module")
def real() -> tuple[Catalog, dict[str, int]]:
    return real_catalog()


def kcal(catalog: Catalog, dishes: list[Dish]) -> float:
    return sum(dish_nutrients(catalog, d).kcal for d in dishes)


# ------------------------------------------------------------- templates


def test_every_fallback_template_exists_in_the_real_data(
    real: tuple[Catalog, dict[str, int]],
) -> None:
    catalog, _ = real
    for template in FALLBACK_TEMPLATES:
        assert _resolve(template, catalog) is not None, template.name


def test_fallback_template_names_are_unique_and_recipes_have_no_calories() -> None:
    names = [t.name for t in FALLBACK_TEMPLATES]
    assert len(names) == len(set(names))
    for template in FALLBACK_TEMPLATES:
        assert "ккал" not in template.recipe.lower()
        assert 20 <= len(template.recipe) <= 400


@pytest.mark.parametrize(
    ("meal_type", "minimum"),
    [(MealType.BREAKFAST, 3), (MealType.LUNCH, 5), (MealType.DINNER, 5), (MealType.SNACK, 4)],
)
def test_every_meal_type_has_enough_variety(meal_type: MealType, minimum: int) -> None:
    assert sum(meal_type in t.meal_types for t in FALLBACK_TEMPLATES) >= minimum


def test_templates_have_plausible_energy(real: tuple[Catalog, dict[str, int]]) -> None:
    catalog, _ = real
    for template in FALLBACK_TEMPLATES:
        dish = _resolve(template, catalog)
        assert dish is not None
        assert 100 <= dish_nutrients(catalog, dish).kcal <= 700, template.name


# ----------------------------------------------- fitting across the range

WINDOWS = {
    MealType.BREAKFAST: range(250, 1001, 50),
    MealType.LUNCH: range(300, 1401, 50),
    MealType.DINNER: range(300, 1401, 50),
    MealType.SNACK: range(100, 501, 25),
}


@pytest.mark.parametrize(
    ("meal_type", "target"),
    [(mt, t) for mt, targets in WINDOWS.items() for t in targets],
)
def test_fallback_hits_the_target_across_realistic_sizes(
    real: tuple[Catalog, dict[str, int]], meal_type: MealType, target: int
) -> None:
    catalog, _ = real
    dishes, _ = fallback_dishes(catalog, meal_type, target, cooked_or_ready_ids(catalog), CFG)
    assert within_tolerance(kcal(catalog, dishes), target, CFG.meal_tolerance)


# ---------------------------------------------------------- availability


def test_dishes_made_of_the_users_foods_come_first(real: tuple[Catalog, dict[str, int]]) -> None:
    catalog, ids = real
    mine = tuple(
        ids[c] for c in ("chicken_breast_cooked", "buckwheat_cooked", "cucumber", "sunflower_oil")
    )
    dishes, ignored = fallback_dishes(catalog, MealType.LUNCH, 600, mine, CFG)
    assert dishes[0].name == "Курица с гречкой и огурцом"
    assert ignored is False
    assert {i.food_id for i in dishes[0].items} <= set(mine)


def test_dishes_with_other_foods_are_used_when_nothing_matches(
    real: tuple[Catalog, dict[str, int]],
) -> None:
    catalog, ids = real
    dishes, ignored = fallback_dishes(catalog, MealType.LUNCH, 600, (ids["apple"],), CFG)
    assert ignored is True
    assert dishes


def test_a_small_pantry_still_gets_a_snack(real: tuple[Catalog, dict[str, int]]) -> None:
    catalog, ids = real
    mine = (ids["apple"], ids["almonds"])
    dishes, ignored = fallback_dishes(catalog, MealType.SNACK, 200, mine, CFG)
    assert dishes[0].name == "Яблоко с миндалём"
    assert ignored is False


def test_already_used_dishes_are_chosen_last(real: tuple[Catalog, dict[str, int]]) -> None:
    catalog, _ = real
    allowed = cooked_or_ready_ids(catalog)
    first, _ = fallback_dishes(catalog, MealType.LUNCH, 600, allowed, CFG)
    second, _ = fallback_dishes(catalog, MealType.LUNCH, 600, allowed, CFG, [first[0].name])
    third, _ = fallback_dishes(
        catalog, MealType.LUNCH, 600, allowed, CFG, [first[0].name, second[0].name]
    )
    assert len({first[0].name, second[0].name, third[0].name}) == 3


def test_when_every_dish_was_used_one_is_still_returned(
    real: tuple[Catalog, dict[str, int]],
) -> None:
    catalog, _ = real
    every_snack = [t.name for t in FALLBACK_TEMPLATES if MealType.SNACK in t.meal_types]
    dishes, _ = fallback_dishes(
        catalog, MealType.SNACK, 200, cooked_or_ready_ids(catalog), CFG, every_snack
    )
    assert dishes


# ------------------------------------------------------------ whole days

DAY = Nutrients(2000, 130, 65, 230, 30)


async def test_a_day_without_a_working_llm_still_matches_the_norm(
    real: tuple[Catalog, dict[str, int]],
) -> None:
    catalog, _ = real
    fake = FakeLLM()  # always unavailable
    results = await build_day(fake, catalog, DAY, ALL_MEALS, cooked_or_ready_ids(catalog), CFG)

    assert [r.meal.meal_type for r in results] == ALL_MEALS
    assert all(r.source is MealSource.FALLBACK for r in results)
    assert all(r.attempts == 3 for r in results)
    assert len(fake.requests) == 12  # 3 attempts * 4 meals, never more

    targets = [500, 700, 600, 200]
    for result, target in zip(results, targets, strict=True):
        assert within_tolerance(result.nutrients.kcal, target, CFG.meal_tolerance)
    total = sum(r.nutrients.kcal for r in results)
    assert within_tolerance(total, 2000, CFG.meal_tolerance)

    names = [d.name for r in results for d in r.meal.dishes]
    assert len(names) == len(set(names))  # no dish repeated within the day


async def test_a_day_with_a_working_llm_uses_its_dishes_and_avoids_repeats(
    real: tuple[Catalog, dict[str, int]],
) -> None:
    catalog, _ = real
    by_name = {t.name: _resolve(t, catalog) for t in FALLBACK_TEMPLATES}
    answers = [
        "Овсянка с бананом и орехами",
        "Курица с гречкой и огурцом",
        "Треска с рисом и брокколи",
        "Яблоко с миндалём",
    ]
    fake = FakeLLM([dishes_to_json([d]) for n in answers if (d := by_name[n]) is not None])
    results = await build_day(fake, catalog, DAY, ALL_MEALS, cooked_or_ready_ids(catalog), CFG)

    assert all(r.source is MealSource.LLM for r in results)
    assert all(r.attempts == 1 for r in results)
    assert [r.meal.dishes[0].name for r in results] == answers
    assert fake.requests[0].avoid_dish_names == ()
    assert fake.requests[3].avoid_dish_names == tuple(answers[:3])  # earlier dishes of the day
    assert within_tolerance(sum(r.nutrients.kcal for r in results), 2000, CFG.meal_tolerance)


async def test_day_with_three_meals_and_a_different_target(
    real: tuple[Catalog, dict[str, int]],
) -> None:
    catalog, _ = real
    meals = [MealType.BREAKFAST, MealType.LUNCH, MealType.DINNER]
    results = await build_day(
        FakeLLM(), catalog, Nutrients(1500, 0, 0, 0), meals, cooked_or_ready_ids(catalog), CFG
    )
    assert within_tolerance(sum(r.nutrients.kcal for r in results), 1500, CFG.meal_tolerance)
