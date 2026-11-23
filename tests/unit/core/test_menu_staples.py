"""Staples (oil, sugar...) and interchangeable foods in the built-in dishes, on real data."""

import logging

import pytest

from nutrition_bot.config import MenuConfig, ShoppingConfig
from nutrition_bot.core.errors import UnknownFoodError
from nutrition_bot.core.measures import Catalog
from nutrition_bot.core.menu import (
    FALLBACK_TEMPLATES,
    MealSource,
    _resolve,
    build_menu,
    fallback_dishes,
    menu_food_ids,
    staple_food_ids,
)
from nutrition_bot.core.models import Dish, MealType
from nutrition_bot.core.norms import calculate_daily_norm
from nutrition_bot.core.shopping import build_shopping_list
from nutrition_bot.services.llm import FakeLLM
from tests.catalog_helpers import real_catalog
from tests.unit.core.test_menu_deadline import PROFILE, NormsConfig

CFG = MenuConfig()


@pytest.fixture(scope="module")
def real() -> tuple[Catalog, dict[str, int]]:
    return real_catalog()


def codes(catalog: Catalog, dish: Dish) -> set[str]:
    return {catalog.get_food(i.food_id).code for i in dish.items}


def lunch(
    catalog: Catalog, ids: dict[str, int], have: list[str], staples: bool, kcal: float = 550.0
) -> tuple[Dish, bool]:
    staple_ids = staple_food_ids(catalog, CFG.staple_codes) if staples else ()
    allowed = menu_food_ids(catalog, [ids[c] for c in have], staple_ids)
    dishes, ignored = fallback_dishes(catalog, MealType.LUNCH, kcal, allowed, CFG)
    return dishes[0], ignored


# ---------------------------------------------------------------- staples


def test_the_default_staples_exist_in_the_real_data(real: tuple[Catalog, dict[str, int]]) -> None:
    catalog, ids = real
    found = staple_food_ids(catalog, CFG.staple_codes)
    assert found == tuple(sorted(ids[c] for c in CFG.staple_codes))
    assert len(found) == len(CFG.staple_codes)


def test_unknown_staple_codes_are_skipped_with_a_warning(
    real: tuple[Catalog, dict[str, int]], caplog: pytest.LogCaptureFixture
) -> None:
    catalog, ids = real
    with caplog.at_level(logging.WARNING):
        found = staple_food_ids(catalog, ["sunflower_oil", "no_such_food"])
    assert found == (ids["sunflower_oil"],)
    assert "no_such_food" in caplog.text
    assert staple_food_ids(catalog, []) == ()


def test_staples_are_added_to_a_given_list_but_not_to_nothing(
    real: tuple[Catalog, dict[str, int]],
) -> None:
    catalog, ids = real
    oil = ids["sunflower_oil"]
    allowed = menu_food_ids(catalog, [ids["chicken_breast_raw"]], [oil])
    assert allowed == tuple(sorted({ids["chicken_breast_cooked"], oil}))
    assert menu_food_ids(catalog, [], [oil]) == (oil,)  # an explicit empty list: staples only
    assert menu_food_ids(catalog, [ids["apple"]]) == (ids["apple"],)  # no staples requested
    assert set(menu_food_ids(catalog, None, [oil])) == set(menu_food_ids(catalog))  # "any" is any


def test_an_unknown_staple_id_is_an_error(real: tuple[Catalog, dict[str, int]]) -> None:
    catalog, ids = real
    with pytest.raises(UnknownFoodError):
        menu_food_ids(catalog, [ids["apple"]], [999_999])


def test_a_lunch_from_the_users_foods_needs_no_oil_in_the_list(
    real: tuple[Catalog, dict[str, int]],
) -> None:
    catalog, ids = real
    have = ["chicken_breast_cooked", "buckwheat_cooked", "cucumber"]  # no oil listed
    dish, ignored = lunch(catalog, ids, have, staples=True)
    assert dish.name == "Курица с гречкой и огурцом"
    assert ignored is False  # before the fix this needed foreign foods
    assert codes(catalog, dish) <= set(have) | set(CFG.staple_codes)
    # without staples the same user would get a dish with foods they did not list
    _, ignored_without = lunch(catalog, ids, have, staples=False)
    assert ignored_without is True


def test_a_user_with_eggs_gets_an_omelette_from_their_foods(
    real: tuple[Catalog, dict[str, int]],
) -> None:
    """The old omelette used a raw egg, which a menu may never contain."""
    catalog, ids = real
    allowed = menu_food_ids(
        catalog,
        [ids["egg_raw"], ids["tomato"], ids["cucumber"]],
        staple_food_ids(catalog, CFG.staple_codes),
    )
    dishes, ignored = fallback_dishes(
        catalog, MealType.BREAKFAST, 300, allowed, CFG, ["Яйца с помидором", "Творог с огурцом"]
    )
    assert dishes[0].name == "Омлет с помидором и огурцом"
    assert ignored is False
    assert codes(catalog, dishes[0]) == {"egg_boiled", "tomato", "cucumber", "sunflower_oil"}


# ------------------------------------------------ interchangeable foods


@pytest.mark.parametrize(
    ("have", "expected_code"),
    [
        (["cottage_0", "cucumber", "greens_herbs"], "cottage_0"),
        (["cottage_9", "cucumber", "greens_herbs"], "cottage_9"),
        (["cottage_5", "cucumber", "greens_herbs"], "cottage_5"),
    ],
)
def test_the_users_variant_of_a_food_is_used(
    real: tuple[Catalog, dict[str, int]], have: list[str], expected_code: str
) -> None:
    catalog, ids = real
    allowed = menu_food_ids(catalog, [ids[c] for c in have])
    dishes, ignored = fallback_dishes(
        catalog, MealType.SNACK, 250, allowed, CFG, ["Творог с огурцом"]
    )
    assert dishes[0].name == "Творог с огурцом и зеленью"
    assert expected_code in codes(catalog, dishes[0])
    assert ignored is False


def test_every_alternative_of_every_template_exists_with_its_measure(
    real: tuple[Catalog, dict[str, int]],
) -> None:
    catalog, _ = real
    by_code = {f.code: f for f in catalog.foods}
    for template in FALLBACK_TEMPLATES:
        for alternatives, measure_name, quantity in template.items:
            assert quantity > 0
            for code in alternatives.split("|"):
                assert code in by_code, f"{template.name}: unknown food {code}"
                names = {m.name_ru for m in catalog.measures_for(by_code[code].id)}
                assert measure_name in names, f"{template.name}: {code} has no {measure_name}"


def test_no_template_uses_a_raw_food(real: tuple[Catalog, dict[str, int]]) -> None:
    """A dish may contain only cooked or ready foods, whatever alternative is chosen."""
    catalog, _ = real
    by_code = {f.code: f for f in catalog.foods}
    for template in FALLBACK_TEMPLATES:
        for alternatives, _, _ in template.items:
            for code in alternatives.split("|"):
                assert by_code[code].state.value != "raw", f"{template.name}: {code} is raw"


def test_the_first_alternative_is_used_when_the_user_has_none(
    real: tuple[Catalog, dict[str, int]],
) -> None:
    catalog, _ = real
    template = next(t for t in FALLBACK_TEMPLATES if t.name == "Рыба с картофелем и огурцом")
    default = _resolve(template, catalog)
    chosen = _resolve(template, catalog, allowed=[])
    assert default is not None
    assert chosen == default
    assert "pollock_cooked" in codes(catalog, default)  # the first of "pollock|cod"


def test_resolution_prefers_the_alternative_the_user_has(
    real: tuple[Catalog, dict[str, int]],
) -> None:
    catalog, ids = real
    template = next(t for t in FALLBACK_TEMPLATES if t.name == "Рыба с картофелем и огурцом")
    dish = _resolve(template, catalog, allowed=[ids["cod_cooked"]])
    assert dish is not None
    assert "cod_cooked" in codes(catalog, dish)
    assert "pollock_cooked" not in codes(catalog, dish)


@pytest.mark.parametrize(
    ("name", "cues"),
    [
        ("Рыба с картофелем и огурцом", ("духовку до 160 °C", "10–15 минут", "74 °C")),
        ("Рис с курицей и брокколи", ("3–5 минут", "вилка", "готовую куриную", "74 °C")),
        ("Омлет с помидором и огурцом", ("среднем огне", "2–3 минуты", "варёные яйца")),
    ],
)
def test_fallback_recipes_give_practical_steps_for_the_catalog_ingredients(
    name: str, cues: tuple[str, ...]
) -> None:
    template = next(t for t in FALLBACK_TEMPLATES if t.name == name)
    assert template.recipe.startswith("1. ")
    assert " 2. " in template.recipe
    for cue in cues:
        assert cue in template.recipe


# ------------------------------------------------------------ variety


@pytest.mark.parametrize(
    ("meal_type", "minimum"),
    [(MealType.BREAKFAST, 6), (MealType.LUNCH, 8), (MealType.DINNER, 9), (MealType.SNACK, 7)],
)
def test_there_are_enough_dishes_for_every_meal(meal_type: MealType, minimum: int) -> None:
    assert sum(meal_type in t.meal_types for t in FALLBACK_TEMPLATES) >= minimum


def test_template_names_are_unique() -> None:
    names = [t.name for t in FALLBACK_TEMPLATES]
    assert len(names) == len(set(names))
    assert len(names) >= 24


async def test_a_three_day_menu_without_an_llm_repeats_no_dish(
    real: tuple[Catalog, dict[str, int]],
) -> None:
    """The known limitation of 14 dishes for 12 meals is gone."""
    catalog, _ = real
    norm = calculate_daily_norm(PROFILE, NormsConfig())
    menu = await build_menu(FakeLLM(), catalog, norm, 3, menu_food_ids(catalog), CFG)
    names = [d.name for day in menu for r in day for d in r.meal.dishes]
    assert len(names) == 12
    assert len(set(names)) == 12
    assert all(r.source is MealSource.FALLBACK for day in menu for r in day)


# ------------------------------------------------------------- shopping


def test_staples_are_marked_in_the_shopping_list(real: tuple[Catalog, dict[str, int]]) -> None:
    catalog, ids = real
    dish, _ = lunch(catalog, ids, ["chicken_breast_cooked", "buckwheat_cooked", "cucumber"], True)
    from nutrition_bot.core.models import Meal

    meal = Meal(MealType.LUNCH, (dish,))
    staples = staple_food_ids(catalog, CFG.staple_codes)
    items = build_shopping_list(catalog, [[meal]], ShoppingConfig(), (), staples)
    by_code = {i.food.code: i for i in items}
    assert by_code["sunflower_oil"].is_staple is True
    assert by_code["chicken_breast_raw"].is_staple is False
    assert by_code["buckwheat_raw"].is_staple is False


def test_without_staple_ids_nothing_is_marked(real: tuple[Catalog, dict[str, int]]) -> None:
    catalog, ids = real
    dish, _ = lunch(catalog, ids, ["chicken_breast_cooked", "buckwheat_cooked", "cucumber"], True)
    from nutrition_bot.core.models import Meal

    items = build_shopping_list(catalog, [[Meal(MealType.LUNCH, (dish,))]], ShoppingConfig())
    assert not any(i.is_staple for i in items)


def test_a_staple_the_user_owns_is_left_out_entirely(real: tuple[Catalog, dict[str, int]]) -> None:
    catalog, ids = real
    dish, _ = lunch(catalog, ids, ["chicken_breast_cooked", "buckwheat_cooked", "cucumber"], True)
    from nutrition_bot.core.models import Meal

    staples = staple_food_ids(catalog, CFG.staple_codes)
    items = build_shopping_list(
        catalog,
        [[Meal(MealType.LUNCH, (dish,))]],
        ShoppingConfig(),
        [ids["sunflower_oil"]],
        staples,
    )
    assert "sunflower_oil" not in {i.food.code for i in items}
