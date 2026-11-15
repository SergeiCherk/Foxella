"""Tests for core.measures: household measure -> grams -> nutrients."""

import math

import pytest

from nutrition_bot.core.errors import (
    InvalidQuantityError,
    NutritionError,
    UnknownFoodError,
    UnknownMeasureError,
)
from nutrition_bot.core.measures import (
    Catalog,
    measure_to_grams,
    nutrients_for_grams,
    nutrients_for_measure,
)
from nutrition_bot.core.models import Food, FoodCategory, FoodState, Measure, Nutrients

RICE_RAW = Food(
    1, "rice_raw", "Рис (сухой)", FoodState.RAW, FoodCategory.GRAIN,
    Nutrients(365.0, 7.1, 0.7, 80.0, 1.3),
)  # fmt: skip
RICE_COOKED = Food(
    2, "rice_cooked", "Рис (варёный)", FoodState.COOKED, FoodCategory.GRAIN,
    Nutrients(130.0, 2.7, 0.3, 28.2, 0.4), raw_food_id=1, yield_factor=2.8,
)  # fmt: skip
LADLE = Measure(10, 2, "половник", 100.0)
CUP_COOKED = Measure(11, 2, "стакан", 165.0)
CUP_RAW = Measure(12, 1, "стакан", 190.0)


@pytest.fixture
def catalog() -> Catalog:
    return Catalog([RICE_RAW, RICE_COOKED], [LADLE, CUP_COOKED, CUP_RAW])


# ---------------------------------------------------------------- catalog


def test_get_food(catalog: Catalog) -> None:
    assert catalog.get_food(2) is RICE_COOKED


def test_unknown_food_raises_clear_error(catalog: Catalog) -> None:
    with pytest.raises(UnknownFoodError) as exc:
        catalog.get_food(999)
    assert exc.value.food_id == 999
    assert "999" in str(exc.value)
    assert isinstance(exc.value, NutritionError)


def test_get_measure_belonging_to_food(catalog: Catalog) -> None:
    assert catalog.get_measure(2, 10) is LADLE


def test_unknown_measure_raises(catalog: Catalog) -> None:
    with pytest.raises(UnknownMeasureError) as exc:
        catalog.get_measure(2, 999)
    assert exc.value.measure_id == 999
    assert exc.value.food_id == 2


def test_measure_of_another_food_is_rejected(catalog: Catalog) -> None:
    # measure 12 is "стакан" of RAW rice; it must not be usable for cooked rice
    with pytest.raises(UnknownMeasureError):
        catalog.get_measure(2, 12)


def test_get_measure_for_unknown_food_raises_food_error(catalog: Catalog) -> None:
    with pytest.raises(UnknownFoodError):
        catalog.get_measure(999, 10)


def test_measures_for_lists_only_that_foods_measures(catalog: Catalog) -> None:
    assert {m.id for m in catalog.measures_for(2)} == {10, 11}
    assert [m.id for m in catalog.measures_for(1)] == [12]


def test_measures_for_food_without_measures_is_empty() -> None:
    assert Catalog([RICE_RAW], []).measures_for(1) == []


def test_measures_for_unknown_food_raises(catalog: Catalog) -> None:
    with pytest.raises(UnknownFoodError):
        catalog.measures_for(999)


def test_foods_property(catalog: Catalog) -> None:
    assert {f.id for f in catalog.foods} == {1, 2}


# ------------------------------------------------------------ conversion


@pytest.mark.parametrize(
    ("quantity", "grams"),
    [(0, 0.0), (1, 100.0), (2, 200.0), (0.5, 50.0), (1.5, 150.0)],
)
def test_measure_to_grams(quantity: float, grams: float) -> None:
    assert measure_to_grams(LADLE, quantity) == pytest.approx(grams)


@pytest.mark.parametrize("bad", [-1, -0.001, math.nan, math.inf, -math.inf])
def test_invalid_quantity_is_rejected(bad: float) -> None:
    with pytest.raises(InvalidQuantityError):
        measure_to_grams(LADLE, bad)
    with pytest.raises(InvalidQuantityError):
        nutrients_for_grams(RICE_COOKED, bad)


def test_nutrients_for_grams_scales_from_per_100g() -> None:
    n = nutrients_for_grams(RICE_COOKED, 250.0)
    assert n.kcal == pytest.approx(325.0)
    assert n.protein_g == pytest.approx(6.75)
    assert n.fat_g == pytest.approx(0.75)
    assert n.carb_g == pytest.approx(70.5)
    assert n.fiber_g == pytest.approx(1.0)


def test_zero_grams_gives_zero_nutrients() -> None:
    assert nutrients_for_grams(RICE_COOKED, 0.0) == Nutrients(0.0, 0.0, 0.0, 0.0, 0.0)


def test_two_ladles_of_cooked_rice() -> None:
    n = nutrients_for_measure(RICE_COOKED, LADLE, 2)
    assert n.kcal == pytest.approx(260.0)  # 200 g * 130 / 100


def test_same_measure_name_means_very_different_calories_raw_vs_cooked() -> None:
    cooked = nutrients_for_measure(RICE_COOKED, CUP_COOKED, 1)
    raw = nutrients_for_measure(RICE_RAW, CUP_RAW, 1)
    assert cooked.kcal == pytest.approx(214.5)  # 165 g * 1.30
    assert raw.kcal == pytest.approx(693.5)  # 190 g * 3.65
    assert raw.kcal > 3 * cooked.kcal


def test_nutrients_for_measure_rejects_foreign_measure() -> None:
    with pytest.raises(UnknownMeasureError):
        nutrients_for_measure(RICE_COOKED, CUP_RAW, 1)


def test_macro_energy_roughly_matches_kcal() -> None:
    n = nutrients_for_measure(RICE_COOKED, CUP_COOKED, 3)
    assert 4 * n.protein_g + 4 * n.carb_g + 9 * n.fat_g == pytest.approx(n.kcal, rel=0.05)
