"""The menu builder must not keep the user waiting: a deadline cancels slow LLM calls."""

import asyncio
import time

import pytest

from nutrition_bot.config import MenuConfig, NormsConfig
from nutrition_bot.core.errors import LLMError
from nutrition_bot.core.menu import (
    DishRequest,
    MealSource,
    build_meal,
    build_menu,
    menu_food_ids,
    within_tolerance,
)
from nutrition_bot.core.models import (
    ActivityLevel,
    Goal,
    MealType,
    Nutrients,
    Profile,
    Sex,
)
from nutrition_bot.core.norms import calculate_daily_norm
from nutrition_bot.services.llm import FakeLLM, dishes_to_json
from tests.catalog_helpers import cooked_or_ready_ids, real_catalog

CFG = MenuConfig()
TARGET = Nutrients(600, 0, 0, 0)
PROFILE = Profile(Sex.FEMALE, 32, 168.0, 64.5, ActivityLevel.LIGHT, Goal.LOSE)


class HangingLLM:
    """Never answers: stands in for a provider that stalls."""

    def __init__(self) -> None:
        self.requests: list[DishRequest] = []

    async def generate(self, request: DishRequest) -> str:
        self.requests.append(request)
        await asyncio.sleep(3600)
        return ""


async def test_a_hanging_call_is_cancelled_at_the_deadline() -> None:
    catalog, _ = real_catalog()
    llm = HangingLLM()
    started = time.perf_counter()
    result = await build_meal(
        llm, catalog, MealType.LUNCH, TARGET, cooked_or_ready_ids(catalog), CFG,
        deadline=time.monotonic() + 0.05,
    )  # fmt: skip
    assert time.perf_counter() - started < 1.0
    assert result.source is MealSource.FALLBACK
    assert result.attempts == 1  # the hanging call counts, no second call was started
    assert result.problems == ("the time limit was reached",)
    assert len(llm.requests) == 1
    assert within_tolerance(result.nutrients.kcal, 600, CFG.meal_tolerance)


async def test_a_passed_deadline_makes_no_llm_call_at_all() -> None:
    catalog, _ = real_catalog()
    llm = FakeLLM()
    result = await build_meal(
        llm, catalog, MealType.DINNER, TARGET, cooked_or_ready_ids(catalog), CFG,
        deadline=time.monotonic() - 1,
    )  # fmt: skip
    assert result.source is MealSource.FALLBACK
    assert result.attempts == 0
    assert llm.requests == []
    assert result.problems == ("the time limit was reached",)


async def test_no_retry_is_started_after_the_deadline() -> None:
    catalog, _ = real_catalog()
    llm = FakeLLM([LLMError("busy"), "never reached"])
    times = iter([0.0, 11.0])  # first check: 10 s left; second check: deadline passed
    result = await build_meal(
        llm, catalog, MealType.LUNCH, TARGET, cooked_or_ready_ids(catalog), CFG,
        deadline=10.0, clock=lambda: next(times),
    )  # fmt: skip
    assert result.attempts == 1
    assert len(llm.requests) == 1
    assert result.source is MealSource.FALLBACK


async def test_a_far_deadline_changes_nothing_for_a_working_llm() -> None:
    catalog, ids = real_catalog()
    from nutrition_bot.db.seed import load_foods  # noqa: F401  (real data is used via helpers)

    fallback = await build_meal(
        FakeLLM(), catalog, MealType.LUNCH, TARGET, cooked_or_ready_ids(catalog), CFG
    )
    answer = dishes_to_json(list(fallback.meal.dishes))
    result = await build_meal(
        FakeLLM([answer]), catalog, MealType.LUNCH, TARGET, cooked_or_ready_ids(catalog), CFG,
        deadline=time.monotonic() + 60,
    )  # fmt: skip
    assert result.source is MealSource.LLM
    assert result.attempts == 1
    assert ids  # the catalog is the real one


async def test_a_whole_menu_with_a_stalled_provider_ends_at_the_time_limit() -> None:
    catalog, _ = real_catalog()
    norm = calculate_daily_norm(PROFILE, NormsConfig())
    llm = HangingLLM()
    cfg = MenuConfig(build_timeout_s=0.1)
    started = time.perf_counter()
    menu = await build_menu(llm, catalog, norm, 3, menu_food_ids(catalog, None), cfg)
    assert time.perf_counter() - started < 2.0

    assert len(menu) == 3
    assert all(len(day) == 4 for day in menu)
    assert all(r.source is MealSource.FALLBACK for day in menu for r in day)
    assert len(llm.requests) == 1  # one stalled call, then the deadline had passed for the rest
    for day in menu:
        kcal = sum(r.nutrients.kcal for r in day)
        assert within_tolerance(kcal, norm.target.kcal, cfg.meal_tolerance)


@pytest.mark.parametrize("timeout", [0.0, -5.0])
async def test_a_zero_or_negative_time_limit_gives_a_fully_built_in_menu(timeout: float) -> None:
    catalog, _ = real_catalog()
    norm = calculate_daily_norm(PROFILE, NormsConfig())
    llm = FakeLLM()
    menu = await build_menu(
        llm, catalog, norm, 1, menu_food_ids(catalog, None), MenuConfig(build_timeout_s=timeout)
    )
    assert llm.requests == []
    assert all(r.source is MealSource.FALLBACK for r in menu[0])
