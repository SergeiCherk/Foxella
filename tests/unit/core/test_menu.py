"""Tests for core.menu on a tiny hand-made catalog (numbers were computed by hand).

Foods (per 100 g): chicken, cooked 165 kcal; rice, cooked 130 kcal; broccoli 34 kcal; oil 884 kcal.
Measures: chicken "грудка" 150 g (247.5 kcal), rice "половник" 100 g (130 kcal),
broccoli "стакан" 95 g (32.3 kcal), oil "столовая ложка" 14 g (123.76 kcal).
"""

import json

import pytest

from nutrition_bot.config import MenuConfig
from nutrition_bot.core.errors import (
    InvalidLLMResponseError,
    InvalidMenuRequestError,
    LLMError,
    MenuUnavailableError,
)
from nutrition_bot.core.measures import Catalog
from nutrition_bot.core.menu import (
    MealSource,
    build_day,
    build_meal,
    fallback_dishes,
    fit_portions,
    meal_targets,
    parse_dishes,
    within_tolerance,
)
from nutrition_bot.core.models import (
    Dish,
    DishItem,
    Food,
    FoodCategory,
    FoodState,
    MealType,
    Measure,
    Nutrients,
)
from nutrition_bot.core.nutrition import dish_nutrients
from nutrition_bot.services.llm import FakeLLM, dishes_to_json
from tests.catalog_helpers import cooked_or_ready_ids, real_catalog

CFG = MenuConfig()


def food(id_: int, code: str, state: FoodState, category: FoodCategory, kcal: float) -> Food:
    return Food(id_, code, code, state, category, Nutrients(kcal, 1.0, 1.0, 1.0, 0.0))


RICE_RAW = food(1, "rice_raw", FoodState.RAW, FoodCategory.GRAIN, 365)
RICE = food(2, "rice", FoodState.COOKED, FoodCategory.GRAIN, 130)
CHICKEN = food(4, "chicken", FoodState.COOKED, FoodCategory.MEAT, 165)
BROCCOLI = food(5, "broccoli", FoodState.READY, FoodCategory.VEGETABLE, 34)
OIL = food(6, "oil", FoodState.READY, FoodCategory.FAT, 884)
EGG = food(7, "egg", FoodState.READY, FoodCategory.EGG, 150)

LADLE = Measure(20, 2, "половник", 100.0)
BREAST = Measure(21, 4, "грудка", 150.0)
CUP = Measure(22, 5, "стакан", 95.0)
TBSP = Measure(23, 6, "столовая ложка", 14.0)
RAW_CUP = Measure(24, 1, "стакан", 190.0)
EGG_PIECE = Measure(25, 7, "яйцо", 50.0)  # 75 kcal; a whole-piece measure

CATALOG = Catalog(
    [RICE_RAW, RICE, CHICKEN, BROCCOLI, OIL, EGG],
    [LADLE, BREAST, CUP, TBSP, RAW_CUP, EGG_PIECE],
)
ALLOWED = (2, 4, 5, 6)  # cooked or ready foods only; raw rice (1) is not allowed

CHICKEN_RICE = Dish(
    "Курица с рисом",
    (DishItem(4, 21, 1), DishItem(2, 20, 2)),  # 247.5 + 260 = 507.5 kcal
    "Отварите рис и запеките курицу.",
)
OIL_HALF = Dish("Масло", (DishItem(6, 23, 0.5),), "Просто масло.")  # 61.88 kcal
EGG_OIL = Dish(
    "Яйцо с маслом",
    (DishItem(7, 25, 1), DishItem(6, 23, 0.5)),  # 75 + 61.88 = 136.88 kcal
    "Пожарьте яйцо на масле.",
)
EGGS_RICE = Dish(
    "Яйца с рисом",
    (DishItem(7, 25, 2), DishItem(2, 20, 3)),  # 150 + 390 = 540 kcal
    "Отварите яйца и рис.",
)


def raw_json(*dishes: Dish) -> str:
    return dishes_to_json(dishes)


def kcal(dishes: list[Dish]) -> float:
    return sum(dish_nutrients(CATALOG, d).kcal for d in dishes)


def problems_of(raw: str) -> list[str]:
    with pytest.raises(InvalidLLMResponseError) as exc:
        parse_dishes(raw, CATALOG, ALLOWED, CFG)
    return exc.value.problems


def has(problems: list[str], text: str) -> bool:
    return any(text in p for p in problems)


def payload(**changes: object) -> str:
    """Valid single-dish JSON with some fields of the dish replaced."""
    dish: dict[str, object] = {
        "name": "Курица с рисом",
        "recipe": "Отварите рис и запеките курицу.",
        "items": [{"food_id": 4, "measure_id": 21, "quantity": 1}],
    }
    dish.update(changes)
    return json.dumps({"dishes": [dish]}, ensure_ascii=False)


# ------------------------------------------------------------ meal targets


def test_meal_targets_split_by_shares() -> None:
    day = Nutrients(2000, 150, 60, 200, 25)
    types = [MealType.BREAKFAST, MealType.LUNCH, MealType.DINNER, MealType.SNACK]
    targets = meal_targets(day, types, CFG)
    assert [round(targets[t].kcal) for t in types] == [500, 700, 600, 200]
    assert targets[MealType.LUNCH].protein_g == pytest.approx(150 * 0.35)
    assert sum(t.kcal for t in targets.values()) == pytest.approx(2000)


def test_meal_targets_renormalise_for_fewer_meals() -> None:
    targets = meal_targets(Nutrients(2000, 0, 0, 0), [MealType.LUNCH, MealType.DINNER], CFG)
    assert targets[MealType.LUNCH].kcal == pytest.approx(2000 * 35 / 65)
    assert sum(t.kcal for t in targets.values()) == pytest.approx(2000)


def test_meal_targets_reject_bad_requests() -> None:
    day = Nutrients(2000, 0, 0, 0)
    with pytest.raises(InvalidMenuRequestError):
        meal_targets(day, [], CFG)
    with pytest.raises(InvalidMenuRequestError):
        meal_targets(day, [MealType.LUNCH, MealType.LUNCH], CFG)
    with pytest.raises(InvalidMenuRequestError):
        meal_targets(day, [MealType.LUNCH], MenuConfig(meal_shares={"breakfast": 1.0}))


# ----------------------------------------------------------------- parsing


def test_valid_answer_is_parsed() -> None:
    dishes = parse_dishes(raw_json(CHICKEN_RICE), CATALOG, ALLOWED, CFG)
    assert dishes == [CHICKEN_RICE]


def test_fenced_json_and_chatter_around_json_are_accepted() -> None:
    body = raw_json(CHICKEN_RICE)
    assert parse_dishes(f"```json\n{body}\n```", CATALOG, ALLOWED, CFG) == [CHICKEN_RICE]
    assert parse_dishes(f"Вот блюдо:\n{body}\nПриятного!", CATALOG, ALLOWED, CFG) == [CHICKEN_RICE]


def test_integer_valued_floats_and_whitespace_are_tolerated() -> None:
    raw = payload(
        name="  Курица  ",
        items=[{"food_id": 4.0, "measure_id": 21.0, "quantity": 1.5}],
    )
    (dish,) = parse_dishes(raw, CATALOG, ALLOWED, CFG)
    assert dish.name == "Курица"
    assert dish.items == (DishItem(4, 21, 1.5),)


@pytest.mark.parametrize("raw", ["", "not json at all", "{broken", "[1, 2]", '"text"', "null"])
def test_garbage_is_rejected(raw: str) -> None:
    assert problems_of(raw)


def test_missing_or_empty_dishes() -> None:
    assert has(problems_of("{}"), "'dishes' must be a non-empty list")
    assert has(problems_of('{"dishes": []}'), "non-empty list")
    assert has(problems_of('{"dishes": "x"}'), "non-empty list")


def test_too_many_dishes() -> None:
    four = json.loads(raw_json(CHICKEN_RICE))["dishes"] * 4
    assert has(problems_of(json.dumps({"dishes": four}, ensure_ascii=False)), "at most 3 dishes")


def test_dish_must_be_an_object() -> None:
    assert has(problems_of('{"dishes": ["soup"]}'), "dish 1: must be an object")


@pytest.mark.parametrize("name", ["", "   ", None, 5, "я" * 101])
def test_bad_dish_names(name: object) -> None:
    assert has(problems_of(payload(name=name)), "name must be")


@pytest.mark.parametrize("recipe", ["", None, 7, "я" * 1501])
def test_bad_recipes(recipe: object) -> None:
    assert has(problems_of(payload(recipe=recipe)), "recipe must be")


@pytest.mark.parametrize(
    "recipe", ["Это блюдо на 500 ккал", "Калорийность: низкая", "about 300 kcal"]
)
def test_recipe_must_not_mention_calories(recipe: str) -> None:
    assert has(problems_of(payload(recipe=recipe)), "must not mention calories")


@pytest.mark.parametrize(
    "items", [None, [], "x", [{"food_id": 4, "measure_id": 21, "quantity": 1}] * 11]
)
def test_bad_item_lists(items: object) -> None:
    assert has(problems_of(payload(items=items)), "items must be a list")


def item(**changes: object) -> list[dict[str, object]]:
    entry: dict[str, object] = {"food_id": 4, "measure_id": 21, "quantity": 1}
    entry.update(changes)
    return [entry]


def test_unknown_food_and_foreign_measure_and_unknown_measure() -> None:
    assert has(problems_of(payload(items=item(food_id=999))), "unknown food_id 999")
    assert has(problems_of(payload(items=item(measure_id=20))), "does not belong to food_id 4")
    assert has(problems_of(payload(items=item(measure_id=999))), "does not belong to food_id 4")


def test_raw_food_is_not_allowed_even_though_it_exists() -> None:
    raw = payload(items=item(food_id=1, measure_id=24))
    assert has(problems_of(raw), "not in the allowed list")


@pytest.mark.parametrize("quantity", [0, -1, 21, "2", None, True, float("inf")])
def test_bad_quantities(quantity: object) -> None:
    raw = payload(items=item(quantity=quantity)).replace("Infinity", "1e999")
    assert has(problems_of(raw), "quantity must be")


@pytest.mark.parametrize("key", ["food_id", "measure_id"])
@pytest.mark.parametrize("value", ["4", None, True, 1.5])
def test_ids_must_be_integers(key: str, value: object) -> None:
    assert has(problems_of(payload(items=item(**{key: value}))), f"{key} must be an integer")


def test_item_must_be_an_object() -> None:
    assert has(problems_of(payload(items=[5])), "item 1: must be an object")


def test_same_food_twice_in_a_dish() -> None:
    items = item() + item(quantity=2)
    assert has(problems_of(payload(items=items)), "same food appears twice")


def test_duplicate_dish_names() -> None:
    entries = json.loads(raw_json(CHICKEN_RICE))["dishes"] * 2
    raw = json.dumps({"dishes": entries}, ensure_ascii=False)
    assert has(problems_of(raw), "duplicate dish name")


def test_all_problems_are_reported_at_once_but_capped() -> None:
    entries = [{"name": "", "recipe": "", "items": []} for _ in range(3)]
    problems = problems_of(json.dumps({"dishes": entries}))
    assert len(problems) == 8  # MAX_PROBLEMS: 3 dishes * 3 problems, capped
    assert has(problems, "dish 1")
    assert has(problems, "dish 2")


# ----------------------------------------------------------- tolerance/fit


@pytest.mark.parametrize(
    ("value", "ok"),
    [(500, True), (550, True), (450, True), (550.5, False), (449.5, False)],
)
def test_tolerance_boundary_is_inclusive(value: float, ok: bool) -> None:
    assert within_tolerance(value, 500, 0.10) is ok


def test_dish_already_on_target_keeps_its_quantities() -> None:
    fitted, reason = fit_portions(CATALOG, [CHICKEN_RICE], 500, CFG)
    assert reason == ""
    assert fitted == [CHICKEN_RICE]  # 507.5 kcal, scale 0.985 rounds back to 1 and 2


def test_portions_are_scaled_and_rounded_to_half_measures() -> None:
    fitted, _ = fit_portions(CATALOG, [CHICKEN_RICE], 700, CFG)
    assert fitted is not None
    assert [i.quantity for i in fitted[0].items] == [1.5, 3.0]
    assert kcal(fitted) == pytest.approx(761.25)
    assert within_tolerance(kcal(fitted), 700, CFG.meal_tolerance)


def test_scaling_down() -> None:
    fitted, _ = fit_portions(CATALOG, [CHICKEN_RICE], 300, CFG)  # scale 0.591
    assert fitted is not None
    assert within_tolerance(kcal(fitted), 300, CFG.meal_tolerance)
    assert all(i.quantity >= 0.5 for i in fitted[0].items)


def test_finer_step_is_used_when_half_measures_are_too_coarse() -> None:
    # 0.5 tbsp of oil, target 90 kcal: step 0.5 gives 0.5 (31 % off), step 0.25 gives 0.75.
    fitted, _ = fit_portions(CATALOG, [OIL_HALF], 90, CFG)
    assert fitted is not None
    assert fitted[0].items[0].quantity == 0.75


def test_whole_pieces_are_never_fractional() -> None:
    # Target 400 kcal: scale 0.741 -> 1.48 eggs and 2.22 ladles. The rice is rounded to a half
    # (2.0), the eggs to a whole number (1), never to 1.5 or 1.25.
    fitted, _ = fit_portions(CATALOG, [EGGS_RICE], 400, CFG)
    assert fitted is not None
    eggs, rice = fitted[0].items
    assert eggs.quantity == 1.0
    assert rice.quantity % 0.25 == 0
    assert within_tolerance(kcal(fitted), 400, CFG.meal_tolerance)


def test_whole_pieces_keep_at_least_one_piece() -> None:
    fitted, _ = fit_portions(CATALOG, [EGGS_RICE], 300, CFG)  # scale 0.556 -> 1.11 eggs
    assert fitted is not None
    assert fitted[0].items[0].quantity >= 1.0
    assert fitted[0].items[0].quantity == int(fitted[0].items[0].quantity)


def test_the_rest_of_the_meal_makes_up_for_whole_pieces() -> None:
    # Target 190 kcal, scale 1.388. The egg stays 1 (75 kcal). With one common factor the oil would
    # be 0.5 or 0.75 tbsp (137 or 168 kcal in total, both below the 171 kcal limit); so the oil is
    # re-scaled to fill the remaining 115 kcal (factor 1.86) and becomes 1 tbsp (198.8 kcal).
    fitted, reason = fit_portions(CATALOG, [EGG_OIL], 190, CFG)
    assert reason == ""
    assert fitted is not None
    assert [i.quantity for i in fitted[0].items] == [1.0, 1.0]
    assert within_tolerance(kcal(fitted), 190, CFG.meal_tolerance)


def test_whole_pieces_use_the_config_list() -> None:
    # With an empty list the egg is rounded like any other measure (to halves, then quarters).
    cfg = MenuConfig(whole_measures=())
    fitted, _ = fit_portions(CATALOG, [EGGS_RICE], 400, cfg)
    assert fitted is not None
    assert fitted[0].items[0].quantity == 1.5


def test_a_dish_far_from_the_target_is_rejected_with_a_reason() -> None:
    fitted, reason = fit_portions(CATALOG, [OIL_HALF], 40, CFG)  # scale 0.65 is in range ...
    assert fitted is None  # ... but 0.5 and 0.25 steps both miss the +-10 % window
    assert "rounded" in reason
    fitted, reason = fit_portions(CATALOG, [CHICKEN_RICE], 5000, CFG)
    assert fitted is None
    assert "totals 508 kcal" in reason
    assert "5000" in reason


def test_scale_limits_and_wide_mode() -> None:
    assert fit_portions(CATALOG, [CHICKEN_RICE], 1200, CFG)[0] is None  # scale 2.36 > 2.0
    wide, _ = fit_portions(CATALOG, [CHICKEN_RICE], 1200, CFG, wide=True)  # allowed up to 3.0
    assert wide is not None
    assert within_tolerance(kcal(wide), 1200, CFG.meal_tolerance)


def test_a_dish_without_calories_cannot_be_fitted() -> None:
    fitted, reason = fit_portions(CATALOG, [Dish("Пусто", (), "")], 500, CFG)
    assert fitted is None
    assert "no calories" in reason


# ------------------------------------------------------- build_meal (LLM)

TARGET = Nutrients(500, 40, 15, 60, 5)


async def build(fake: FakeLLM, cfg: MenuConfig = CFG, avoid: tuple[str, ...] = ()):  # type: ignore[no-untyped-def]
    return await build_meal(fake, CATALOG, MealType.LUNCH, TARGET, ALLOWED, cfg, avoid)


async def test_good_answer_is_used_on_the_first_attempt() -> None:
    fake = FakeLLM([raw_json(CHICKEN_RICE)])
    result = await build(fake)
    assert result.source is MealSource.LLM
    assert result.attempts == 1
    assert result.problems == ()
    assert result.meal.dishes == (CHICKEN_RICE,)
    assert result.nutrients.kcal == pytest.approx(507.5)  # computed by code, not by the model
    assert len(fake.requests) == 1
    assert fake.requests[0].target_kcal == 500
    assert fake.requests[0].feedback == ()


async def test_portions_are_fitted_to_the_target() -> None:
    bigger = Dish("Чуть больше", (DishItem(4, 21, 1.5), DishItem(2, 20, 3)), "Запеките и отварите.")
    result = await build(FakeLLM([raw_json(bigger)]))  # 761 kcal -> scale 0.66, still acceptable
    assert result.source is MealSource.LLM
    assert result.attempts == 1
    assert within_tolerance(result.nutrients.kcal, 500, CFG.meal_tolerance)
    assert result.meal.dishes[0].items != bigger.items  # quantities were changed by the code


async def test_invalid_answer_is_retried_with_feedback() -> None:
    fake = FakeLLM(["это не JSON", raw_json(CHICKEN_RICE)])
    result = await build(fake)
    assert result.source is MealSource.LLM
    assert result.attempts == 2
    assert fake.requests[0].feedback == ()
    assert fake.requests[1].feedback == ("response is not valid JSON",)


async def test_unusable_portions_trigger_a_retry_with_a_reason() -> None:
    huge = Dish("Гора еды", (DishItem(4, 21, 5), DishItem(2, 20, 6)), "Запеките и отварите.")
    fake = FakeLLM([raw_json(huge), raw_json(CHICKEN_RICE)])
    result = await build(fake)
    assert result.attempts == 2
    assert "kcal is needed" in fake.requests[1].feedback[0]


async def test_transport_error_is_retried_without_feedback() -> None:
    fake = FakeLLM([LLMError("timeout"), raw_json(CHICKEN_RICE)])
    result = await build(fake)
    assert result.source is MealSource.LLM
    assert result.attempts == 2
    assert fake.requests[1].feedback == ()


async def test_repeated_dish_name_is_rejected() -> None:
    other = Dish("Курица с брокколи", (DishItem(4, 21, 1), DishItem(5, 22, 1)), "Запеките.")
    fake = FakeLLM([raw_json(CHICKEN_RICE), raw_json(other)])
    result = await build(fake, avoid=("курица с рисом",))  # case-insensitive
    assert result.attempts == 2
    assert result.meal.dishes[0].name == "Курица с брокколи"
    assert "already used" in fake.requests[1].feedback[0]


async def test_after_all_attempts_a_fallback_dish_is_used() -> None:
    fake = FakeLLM(["bad", "still bad", "{}"])
    result = await build_with_real_fallback(fake)
    assert result.source is MealSource.FALLBACK
    assert result.attempts == 3  # 1 + max_llm_retries
    assert len(fake.requests) == 3
    assert result.problems == ("'dishes' must be a non-empty list",)


async def build_with_real_fallback(fake: FakeLLM):  # type: ignore[no-untyped-def]
    catalog, _ = real_catalog()
    return await build_meal(
        fake, catalog, MealType.LUNCH, Nutrients(600, 0, 0, 0), cooked_or_ready_ids(catalog), CFG
    )


async def test_llm_down_means_exactly_max_attempts_then_fallback() -> None:
    fake = FakeLLM()  # raises LLMError on every call
    result = await build_with_real_fallback(fake)
    assert result.source is MealSource.FALLBACK
    assert result.attempts == 3
    assert result.problems == ("the language model was unavailable",)


async def test_max_llm_retries_zero_means_a_single_call() -> None:
    fake = FakeLLM(["bad", "never used"])
    cfg = MenuConfig(max_llm_retries=0)
    catalog, _ = real_catalog()
    result = await build_meal(
        fake, catalog, MealType.DINNER, Nutrients(600, 0, 0, 0), cooked_or_ready_ids(catalog), cfg
    )
    assert result.attempts == 1
    assert len(fake.requests) == 1
    assert result.source is MealSource.FALLBACK


# ---------------------------------------------------------- fallback logic


def test_fallback_without_any_matching_template_in_catalog_raises() -> None:
    with pytest.raises(MenuUnavailableError):
        fallback_dishes(CATALOG, MealType.LUNCH, 500, ALLOWED, CFG)


async def test_build_day_without_meals_is_rejected() -> None:
    with pytest.raises(InvalidMenuRequestError):
        await build_day(FakeLLM(), CATALOG, Nutrients(2000, 0, 0, 0), [], ALLOWED, CFG)
