"""A whole day in one model call: meals checked one by one, only failing meals asked again."""

import json

import pytest

from nutrition_bot.config import MenuConfig, NormsConfig
from nutrition_bot.core.errors import InvalidLLMResponseError
from nutrition_bot.core.menu import (
    MealSource,
    build_day,
    fallback_dishes,
    meal_targets,
    menu_food_ids,
    split_day_answer,
)
from nutrition_bot.core.models import ActivityLevel, Goal, MealType, Profile, Sex
from nutrition_bot.core.norms import calculate_daily_norm
from nutrition_bot.services.llm import FakeLLM, build_day_prompt, day_system_prompt, dishes_to_json
from tests.catalog_helpers import real_catalog

CATALOG, IDS = real_catalog()
CFG = MenuConfig()
MEALS = [MealType(m) for m in CFG.meal_order]
NORM = calculate_daily_norm(
    Profile(Sex.FEMALE, 32, 168.0, 64.5, ActivityLevel.LIGHT, Goal.LOSE), NormsConfig()
)
ALLOWED = menu_food_ids(CATALOG)
TARGETS = meal_targets(NORM.target, MEALS, CFG)


def meal_json(meal: MealType, avoid: list[str]) -> dict[str, object]:
    dishes, _ = fallback_dishes(CATALOG, meal, TARGETS[meal].kcal, ALLOWED, CFG, avoid)
    avoid += [d.name for d in dishes]
    return {"meal": meal.value, "dishes": json.loads(dishes_to_json(dishes))["dishes"]}


def day_answer(*, broken: MealType | None = None) -> str:
    avoid: list[str] = []
    meals = [meal_json(m, avoid) for m in MEALS]
    for meal in meals:
        if meal["meal"] == (broken.value if broken else None):
            meal["dishes"] = [{"name": "Пусто", "recipe": "Нет.", "items": []}]
    return json.dumps({"meals": meals}, ensure_ascii=False)


async def test_one_call_gives_the_whole_day() -> None:
    llm = FakeLLM(days=[day_answer()])
    results = await build_day(llm, CATALOG, NORM.target, MEALS, ALLOWED, CFG)
    assert [r.source for r in results] == [MealSource.LLM] * 4
    assert len(llm.day_requests) == 1
    assert llm.requests == []  # no meal had to be asked for on its own
    assert [m for m, _ in llm.day_requests[0].meals] == MEALS


async def test_only_the_failing_meal_is_asked_again_with_its_problems() -> None:
    llm = FakeLLM(days=[day_answer(broken=MealType.LUNCH)])
    results = await build_day(llm, CATALOG, NORM.target, MEALS, ALLOWED, CFG)
    assert [r.meal.meal_type for r in results] == MEALS
    lunch_requests = [r for r in llm.requests if r.meal_type is MealType.LUNCH]
    assert len(lunch_requests) == len(llm.requests) >= 1
    assert any("items must be" in p for p in lunch_requests[0].feedback)
    assert results[0].source is MealSource.LLM
    assert results[1].source is MealSource.FALLBACK  # the fake has no single-meal answers


async def test_an_unusable_day_answer_falls_back_to_meals_one_by_one() -> None:
    llm = FakeLLM(days=["not json"])
    results = await build_day(llm, CATALOG, NORM.target, MEALS, ALLOWED, CFG)
    assert len(results) == 4
    assert {r.meal_type for r in llm.requests} == set(MEALS)


async def test_day_requests_can_be_switched_off() -> None:
    llm = FakeLLM(days=[day_answer()])
    await build_day(
        llm, CATALOG, NORM.target, MEALS, ALLOWED, CFG.model_copy(update={"day_requests": False})
    )
    assert llm.day_requests == []


def test_the_day_answer_is_split_per_meal() -> None:
    raw = json.dumps(
        {"meals": [{"meal": "lunch", "dishes": []}, {"meal": "lunch", "dishes": [1]},
                   {"meal": "brunch", "dishes": []}, "junk"]}
    )  # fmt: skip
    parts = split_day_answer(raw, MEALS)
    assert list(parts) == [MealType.LUNCH]  # the repeat, the unknown meal and junk are dropped
    assert json.loads(parts[MealType.LUNCH]) == {"dishes": []}
    with pytest.raises(InvalidLLMResponseError):
        split_day_answer('{"dishes": []}', MEALS)


def test_the_day_prompt_names_every_meal_with_its_kcal() -> None:
    from nutrition_bot.core.menu import DayRequest

    request = DayRequest(
        ((MealType.BREAKFAST, 400.0), (MealType.LUNCH, 650.0)), (IDS["pasta_cooked"],), ("Омлет",)
    )
    system, user = build_day_prompt(request, CATALOG)
    assert system == day_system_prompt()
    assert '"meals"' in system
    assert '{"dishes": [' not in system.split("Правила:")[0].split("Формат:")[1][:12]
    assert "названия разные во всём дне" in system
    assert "breakfast (завтрак) примерно 400 ккал" in user
    assert "lunch (обед) примерно 650 ккал" in user
    assert "Не повторять блюда: Омлет" in user
