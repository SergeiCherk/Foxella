"""Tests for core.balance. Food values are small round numbers so sums can be checked by hand."""

import pytest

from nutrition_bot.config import BalanceConfig
from nutrition_bot.core.balance import (
    BalanceHint,
    HintKind,
    analyze_day,
    fiber_target_g,
    pantry_hints,
)
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


def food(id_: int, code: str, state: FoodState, cat: FoodCategory, n: tuple[float, ...]) -> Food:
    return Food(id_, code, code, state, cat, Nutrients(*n))


# n = (kcal, protein, fat, carb, fiber) per 100 g
RICE = food(1, "rice", FoodState.COOKED, FoodCategory.GRAIN, (130, 2.7, 0.3, 28.2, 0.4))
CHICKEN = food(2, "chicken", FoodState.COOKED, FoodCategory.MEAT, (165, 30.0, 3.6, 0, 0))
BROCCOLI = food(3, "broccoli", FoodState.READY, FoodCategory.VEGETABLE, (34, 2.8, 0.4, 6.6, 2.6))
APPLE = food(4, "apple", FoodState.READY, FoodCategory.FRUIT, (52, 0.3, 0.2, 14.0, 2.4))
POTATO = food(5, "potato", FoodState.READY, FoodCategory.STARCH, (80, 2.0, 0.1, 17.0, 1.8))
BEANS = food(6, "beans", FoodState.READY, FoodCategory.LEGUME, (120, 7.0, 0.5, 20.0, 6.0))
EGG = food(7, "egg", FoodState.READY, FoodCategory.EGG, (150, 12.5, 10.0, 1.0, 0))
CUCUMBER = food(8, "cucumber", FoodState.READY, FoodCategory.VEGETABLE, (15, 0.7, 0.1, 3.0, 0.7))

# One measure per food; the id is 100 + food id.
MEASURES = [
    Measure(101, 1, "половник", 100.0),
    Measure(102, 2, "грудка", 150.0),
    Measure(103, 3, "стакан", 100.0),
    Measure(104, 4, "яблоко", 200.0),
    Measure(105, 5, "картофелина", 100.0),
    Measure(106, 6, "половник", 100.0),
    Measure(107, 7, "яйцо", 50.0),
    Measure(108, 8, "огурец", 100.0),
]
CATALOG = Catalog([RICE, CHICKEN, BROCCOLI, APPLE, POTATO, BEANS, EGG, CUCUMBER], MEASURES)
CFG = BalanceConfig()


def meal(meal_type: MealType, *items: tuple[int, float]) -> Meal:
    """A meal with one dish; each item is (food id, number of household measures)."""
    dish_items = tuple(DishItem(food_id, 100 + food_id, qty) for food_id, qty in items)
    return Meal(meal_type, (Dish("d", dish_items),))


def target(kcal: float = 1000.0, protein_g: float = 100.0) -> Nutrients:
    return Nutrients(kcal, protein_g, 30.0, 100.0)


def good_day() -> list[Meal]:
    """Protein >= 20 g in each main meal; 500 g vegetables and fruit; 17.7 g fibre."""
    return [
        meal(MealType.BREAKFAST, (7, 4)),  # 4 eggs = 25 g protein
        meal(MealType.LUNCH, (2, 1), (3, 3), (6, 1)),  # chicken 45 g, broccoli 300 g, beans
        meal(MealType.DINNER, (2, 1), (4, 1)),  # chicken 45 g, apple 200 g
    ]


def kinds(hints: tuple[BalanceHint, ...]) -> list[HintKind]:
    return [h.kind for h in hints]


# ---------- analyze_day ----------


def test_empty_day_has_nothing_to_analyse() -> None:
    assert analyze_day(CATALOG, [], target(), CFG) == ()


def test_balanced_day_gives_no_hints() -> None:
    assert analyze_day(CATALOG, good_day(), target(), CFG) == ()


def test_low_protein_meal_is_named() -> None:
    meals = good_day()
    meals[2] = meal(MealType.DINNER, (1, 2), (3, 3))  # rice and broccoli, about 11 g protein
    hints = analyze_day(CATALOG, meals, target(), CFG)
    assert hints == (BalanceHint(HintKind.PROTEIN_MEAL, MealType.DINNER),)


def test_snack_is_exempt_from_the_per_meal_protein_rule() -> None:
    meals = [*good_day(), meal(MealType.SNACK, (4, 1))]  # a snack of one apple
    assert analyze_day(CATALOG, meals, target(), CFG) == ()


def test_each_low_protein_meal_gets_its_own_hint() -> None:
    meals = [
        meal(MealType.BREAKFAST, (4, 1)),
        meal(MealType.LUNCH, (1, 1)),
        meal(MealType.DINNER, (2, 1), (3, 5), (4, 1)),
    ]
    hints = analyze_day(CATALOG, meals, target(), CFG)
    assert [h.meal_type for h in hints if h.kind is HintKind.PROTEIN_MEAL] == [
        MealType.BREAKFAST,
        MealType.LUNCH,
    ]


def test_low_protein_day_when_every_meal_passes_alone() -> None:
    hints = analyze_day(CATALOG, good_day(), target(protein_g=200.0), CFG)  # ~120 g vs 160 g bar
    assert kinds(hints) == [HintKind.PROTEIN_DAY]
    assert hints[0].meal_type is None


def test_day_protein_hint_is_skipped_when_a_meal_hint_already_exists() -> None:
    meals = [meal(MealType.BREAKFAST, (4, 1)), meal(MealType.LUNCH, (4, 1))]
    hints = analyze_day(CATALOG, meals, target(protein_g=200.0), CFG)
    assert HintKind.PROTEIN_DAY not in kinds(hints)
    assert HintKind.PROTEIN_MEAL in kinds(hints)


def test_few_vegetables_and_fruit() -> None:
    meals = [
        meal(MealType.BREAKFAST, (7, 4)),
        meal(MealType.LUNCH, (2, 1), (3, 1)),  # 100 g of vegetables
        meal(MealType.DINNER, (2, 1), (4, 1)),  # 200 g of fruit
    ]
    assert kinds(analyze_day(CATALOG, meals, target(), CFG)) == [HintKind.VEG_FRUIT]


def test_vegetable_and_fruit_bar_is_inclusive() -> None:
    meals = [
        meal(MealType.BREAKFAST, (7, 4)),
        meal(MealType.LUNCH, (2, 1), (8, 2), (6, 1)),  # 200 g cucumber
        meal(MealType.DINNER, (2, 1), (4, 1)),  # 200 g apple -> exactly 400 g
    ]
    cfg = BalanceConfig(fiber_min_g=0.0)
    assert analyze_day(CATALOG, meals, target(), cfg) == ()


def test_potatoes_do_not_count_as_vegetables() -> None:
    meals = [
        meal(MealType.BREAKFAST, (7, 4)),
        meal(MealType.LUNCH, (2, 1), (5, 6)),  # 600 g of potato
        meal(MealType.DINNER, (2, 1)),
    ]
    assert HintKind.VEG_FRUIT in kinds(analyze_day(CATALOG, meals, target(), CFG))


def test_fibre_hint_when_vegetables_are_fine_but_fibre_is_low() -> None:
    meals = [
        meal(MealType.BREAKFAST, (7, 4)),
        meal(MealType.LUNCH, (2, 1), (8, 5)),  # 500 g cucumber: 3.5 g fibre
        meal(MealType.DINNER, (2, 1)),
    ]
    assert kinds(analyze_day(CATALOG, meals, target(kcal=2000.0), CFG)) == [HintKind.FIBER]


def test_fibre_hint_is_not_repeated_next_to_the_vegetable_hint() -> None:
    meals = [meal(MealType.BREAKFAST, (7, 4)), meal(MealType.LUNCH, (2, 1), (1, 1))]
    found = kinds(analyze_day(CATALOG, meals, target(kcal=2000.0), CFG))
    assert HintKind.VEG_FRUIT in found
    assert HintKind.FIBER not in found


def test_low_calorie_plan_uses_a_lower_fibre_bar() -> None:
    # 17.7 g of fibre: enough for a 1000 kcal plan (bar 12.5 g), not for a 2000 kcal one (25 g).
    assert analyze_day(CATALOG, good_day(), target(kcal=1000.0), CFG) == ()
    assert kinds(analyze_day(CATALOG, good_day(), target(kcal=2000.0), CFG)) == [HintKind.FIBER]


def test_thresholds_come_from_config() -> None:
    strict = BalanceConfig(protein_min_per_meal_g=70.0)
    hints = analyze_day(CATALOG, good_day(), target(), strict)
    assert {h.meal_type for h in hints if h.kind is HintKind.PROTEIN_MEAL} == {
        MealType.BREAKFAST,
        MealType.LUNCH,
        MealType.DINNER,
    }


def test_unknown_food_is_an_error() -> None:
    bad = Meal(MealType.LUNCH, (Dish("d", (DishItem(999, 1, 1.0),)),))
    with pytest.raises(UnknownFoodError):
        analyze_day(CATALOG, [bad], target(), CFG)


@pytest.mark.parametrize(
    ("kcal", "expected"),
    [(2000, 25.0), (1000, 12.5), (1200, 15.0), (3000, 25.0), (0, 0.0), (-50, 0.0)],
)
def test_fiber_target_scales_below_the_reference_energy(kcal: float, expected: float) -> None:
    assert fiber_target_g(kcal, CFG) == pytest.approx(expected)


# ---------- pantry_hints ----------


def test_empty_pantry_gives_no_hints() -> None:
    assert pantry_hints(CATALOG, [], CFG) == ()


def test_full_pantry_gives_no_hints() -> None:
    assert pantry_hints(CATALOG, [1, 2, 3, 4, 6, 7], CFG) == ()


def test_pantry_without_protein_or_fibre_sources() -> None:
    hints = pantry_hints(CATALOG, [1, 3, 4], CFG)  # rice, broccoli, apple
    assert kinds(hints) == [HintKind.PROTEIN_DAY, HintKind.FIBER]


def test_pantry_without_vegetables_or_fruit() -> None:
    hints = pantry_hints(CATALOG, [1, 2], CFG)  # rice, chicken
    assert kinds(hints) == [HintKind.VEG_FRUIT]


def test_pantry_potatoes_are_not_vegetables() -> None:
    assert HintKind.VEG_FRUIT in kinds(pantry_hints(CATALOG, [2, 5], CFG))


def test_pantry_ignores_duplicate_ids() -> None:
    assert pantry_hints(CATALOG, [2, 2, 3, 3, 6], CFG) == ()


def test_pantry_unknown_food_is_an_error() -> None:
    with pytest.raises(UnknownFoodError):
        pantry_hints(CATALOG, [1, 999], CFG)
