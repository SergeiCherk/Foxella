"""Food restrictions: forbidden foods never reach a menu, from the model or our own dishes."""

import json
from itertools import combinations

import pytest

from nutrition_bot.config import DietConfig, MenuConfig, NormsConfig
from nutrition_bot.core.diet import forbidden_food_ids, known_restrictions
from nutrition_bot.core.errors import InvalidLLMResponseError, MenuUnavailableError
from nutrition_bot.core.menu import DishRules, build_menu, menu_food_ids, parse_dishes
from nutrition_bot.core.models import ActivityLevel, Goal, Profile, Sex
from nutrition_bot.core.norms import calculate_daily_norm
from nutrition_bot.services.llm import FakeLLM
from tests.catalog_helpers import real_catalog

CATALOG, IDS = real_catalog()
CFG = DietConfig()
PROFILE = Profile(Sex.FEMALE, 32, 168.0, 64.5, ActivityLevel.LIGHT, Goal.LOSE)


def forbidden(*codes: str) -> frozenset[int]:
    return forbidden_food_ids(CATALOG, codes, CFG)


def test_every_rule_names_existing_categories_and_foods() -> None:
    categories = {f.category.value for f in CATALOG.foods}
    for code, rule in CFG.rules.items():
        assert set(rule.categories) <= categories, code
        assert set(rule.codes) <= set(IDS), code


def test_meat_removes_raw_cooked_and_ready_meat() -> None:
    gone = forbidden("meat")
    for code in ("chicken_breast_raw", "chicken_breast_cooked", "ham", "doctor_sausage"):
        assert IDS[code] in gone
    assert IDS["salmon_cooked"] not in gone


def test_a_raw_food_takes_its_cooked_versions_along() -> None:
    gone = forbidden("gluten")
    assert {IDS["pasta_raw"], IDS["pasta_cooked"], IDS["bread_rye"]} <= gone
    assert IDS["buckwheat_cooked"] not in gone  # buckwheat has no gluten


def test_nuts_are_not_seeds_and_dairy_includes_butter() -> None:
    assert IDS["walnuts"] in forbidden("nuts")
    assert IDS["sunflower_seeds"] not in forbidden("nuts")
    assert IDS["butter"] in forbidden("dairy")
    assert IDS["mayonnaise"] in forbidden("eggs")


def test_unknown_codes_are_ignored() -> None:
    assert forbidden("chocolate", "") == frozenset()
    assert known_restrictions(["nuts", "x", "meat"], CFG) == ["meat", "nuts"]


def test_allowed_foods_never_include_forbidden_ones_not_even_staples() -> None:
    gone = forbidden("dairy")
    staples = (IDS["butter"], IDS["sunflower_oil"])
    for pantry in (None, [IDS["cottage_5"], IDS["apple"]]):
        allowed = menu_food_ids(CATALOG, pantry, staples, gone)
        assert not set(allowed) & gone
        assert IDS["sunflower_oil"] in allowed


def test_the_model_cannot_mention_a_forbidden_food_in_a_recipe() -> None:
    from tests.unit.services.test_recipe_mentions import FINDER

    answer = json.dumps(
        {"dishes": [{"name": "Паста", "recipe": "Посыпьте пасту сыром.",
                     "items": [{"food_id": IDS["pasta_cooked"],
                                "measure_id": CATALOG.measures_for(IDS["pasta_cooked"])[0].id,
                                "quantity": 1}]}]},
        ensure_ascii=False,
    )  # fmt: skip
    rules = DishRules(FINDER, forbidden("dairy"))
    with pytest.raises(InvalidLLMResponseError) as error:
        parse_dishes(answer, CATALOG, [IDS["pasta_cooked"]], MenuConfig(), rules)
    assert any("does not eat" in p for p in error.value.problems)


def test_hidden_sour_cream_is_sent_back_to_the_model() -> None:
    from tests.unit.services.test_recipe_mentions import FINDER

    potato = IDS["potato_boiled"]
    answer = json.dumps(
        {"dishes": [{"name": "Картофель", "recipe": "Полейте картофель сметаной.",
                     "items": [{"food_id": potato,
                                "measure_id": CATALOG.measures_for(potato)[0].id,
                                "quantity": 2}]}]},
        ensure_ascii=False,
    )  # fmt: skip
    with pytest.raises(InvalidLLMResponseError) as error:
        parse_dishes(answer, CATALOG, [potato], MenuConfig(), DishRules(FINDER))
    assert any("«сметаной», but it is not in items" in p for p in error.value.problems)


EVERY_COMBINATION = [c for k in range(1, len(CFG.rules) + 1) for c in combinations(CFG.rules, k)]


@pytest.mark.parametrize("codes", EVERY_COMBINATION, ids="+".join)
async def test_any_restrictions_give_a_three_day_menu_without_forbidden_foods(
    codes: tuple[str, ...],
) -> None:
    """Only our own dishes here (no model). They used to take any food when short, and before
    the four restriction-free dishes several restrictions together gave no menu at all."""
    gone = forbidden(*codes)
    norm = calculate_daily_norm(PROFILE, NormsConfig())
    allowed = menu_food_ids(CATALOG, None, (), gone)
    menu = await build_menu(
        FakeLLM(), CATALOG, norm, 3, allowed, MenuConfig(), rules=DishRules(None, gone)
    )
    used = {i.food_id for day in menu for r in day for d in r.meal.dishes for i in d.items}
    assert used
    assert not used & gone


def test_a_meal_without_any_possible_dish_is_reported() -> None:
    from nutrition_bot.core.menu import fallback_dishes
    from nutrition_bot.core.models import MealType

    everything = frozenset(f.id for f in CATALOG.foods)
    with pytest.raises(MenuUnavailableError):
        fallback_dishes(CATALOG, MealType.LUNCH, 500, [], MenuConfig(), (), everything)
