"""Tests for the seed-file loader/validator and for the real foods.csv / measures.csv."""

import dataclasses
from collections import Counter
from pathlib import Path

import pytest

from nutrition_bot.core.models import FoodCategory
from nutrition_bot.db.seed import (
    FOOD_COLUMNS,
    DataFileError,
    FoodRow,
    MeasureRow,
    load_foods,
    load_measures,
    validate_data,
)

RICE = FoodRow(
    "rice_raw", "Рис (сухой)", "raw", "grain", None, None, 365.0, 7.1, 0.7, 80.0, 1.3, ("рис",)
)
RICE_COOKED = FoodRow(
    "rice_cooked", "Рис (варёный)", "cooked", "grain", "rice_raw", 2.8,
    130.0, 2.7, 0.3, 28.2, 0.4, ("варёный рис",),
)  # fmt: skip
APPLE = FoodRow(
    "apple", "Яблоко", "ready", "fruit", None, None, 52.0, 0.3, 0.2, 13.8, 2.4, ("яблоко",)
)
MEASURES = [
    MeasureRow("rice_raw", "стакан", 190.0),
    MeasureRow("rice_cooked", "половник", 100.0),
    MeasureRow("apple", "яблоко", 170.0),
]


def good() -> tuple[list[FoodRow], list[MeasureRow]]:
    return [RICE, RICE_COOKED, APPLE], list(MEASURES)


def problems_for(**changes: object) -> list[str]:
    """Validate the good dataset after replacing fields of the first food (rice_raw)."""
    foods, measures = good()
    foods[0] = dataclasses.replace(foods[0], **changes)  # type: ignore[arg-type]
    return validate_data(foods, measures)


def cooked_problems(**changes: object) -> list[str]:
    foods, measures = good()
    foods[1] = dataclasses.replace(foods[1], **changes)  # type: ignore[arg-type]
    return validate_data(foods, measures)


def has(problems: list[str], text: str) -> bool:
    return any(text in p for p in problems)


# --------------------------------------------------- the validator catches bugs


def test_good_dataset_has_no_problems() -> None:
    assert validate_data(*good()) == []


def test_duplicate_code_and_name_are_reported() -> None:
    foods, measures = good()
    foods.append(dataclasses.replace(APPLE, code="rice_raw", name_ru="Другое"))
    foods.append(dataclasses.replace(APPLE, code="apple2"))
    problems = validate_data(foods, measures)
    assert has(problems, "duplicate food code: rice_raw")
    assert has(problems, "duplicate food name: Яблоко")


def test_unknown_state_and_category() -> None:
    assert has(problems_for(state="boiled"), "unknown state")
    assert has(problems_for(category="candy"), "unknown category")


@pytest.mark.parametrize("field", ["kcal_100", "protein_100", "fat_100", "carb_100", "fiber_100"])
def test_negative_nutrient_is_reported(field: str) -> None:
    assert has(problems_for(**{field: -1.0}), "finite and >= 0")


def test_nan_nutrient_is_reported() -> None:
    assert has(problems_for(kcal_100=float("nan")), "finite and >= 0")


def test_macros_over_100_grams() -> None:
    assert has(problems_for(protein_100=60.0, fat_100=30.0, carb_100=30.0), "exceed 100 g")


def test_fibre_cannot_exceed_carbs() -> None:
    assert has(problems_for(fiber_100=90.0), "fibre")


@pytest.mark.parametrize("kcal", [30.0, 900.0, 36.5])  # 36.5: a dropped digit of 365
def test_kcal_must_match_macros(kcal: float) -> None:
    assert has(problems_for(kcal_100=kcal), "does not match macros")


def test_swapped_fat_and_carbs_is_caught() -> None:
    assert has(problems_for(fat_100=80.0, carb_100=0.7), "does not match macros")


def test_cooked_needs_existing_raw_food() -> None:
    assert has(cooked_problems(raw_code="nope"), "does not exist")
    assert has(cooked_problems(raw_code=None), "does not exist")


def test_cooked_cannot_point_to_ready_food() -> None:
    assert has(cooked_problems(raw_code="apple"), "is not a raw food")


@pytest.mark.parametrize("bad_yield", [None, 0.0, -1.0, 9.0])
def test_cooked_yield_must_be_sane(bad_yield: float | None) -> None:
    assert has(cooked_problems(yield_factor=bad_yield), "yield_factor must be")


def test_cooked_energy_must_match_yield() -> None:
    # 130 kcal cooked with yield 1.0 would mean cooking tripled the energy of 365 kcal raw.
    assert has(cooked_problems(yield_factor=1.0), "inconsistent with yield")


def test_raw_food_cannot_have_yield() -> None:
    assert has(problems_for(yield_factor=2.0), "only cooked foods")
    assert has(problems_for(raw_code="apple"), "only cooked foods")


def test_alias_rules() -> None:
    assert has(problems_for(aliases=()), "no aliases")
    assert has(problems_for(aliases=("рис", "рис")), "duplicate aliases")
    assert has(problems_for(aliases=("Рис",)), "lowercase")
    assert has(problems_for(aliases=(" рис",)), "lowercase")


def test_measure_rules() -> None:
    foods, measures = good()
    measures += [
        MeasureRow("ghost", "стакан", 100.0),
        MeasureRow("apple", "", 100.0),
        MeasureRow("apple", "огромное", 5000.0),
        MeasureRow("apple", "нулевое", 0.0),
        MeasureRow("apple", "яблоко", 170.0),
    ]
    problems = validate_data(foods, measures)
    assert has(problems, "ghost/стакан: unknown food")
    assert has(problems, "empty name")
    assert has(problems, "огромное: grams must be")
    assert has(problems, "нулевое: grams must be")
    assert has(problems, "duplicate measure")


def test_every_food_needs_a_measure() -> None:
    foods, measures = good()
    assert has(validate_data(foods, measures[:-1]), "food apple: has no household measure")


# ------------------------------------------------------------------ loaders


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_load_foods_rejects_wrong_columns(tmp_path: Path) -> None:
    with pytest.raises(DataFileError, match="expected columns"):
        load_foods(write(tmp_path / "f.csv", "code,name\nx,y\n"))


def test_load_foods_rejects_non_numeric_value(tmp_path: Path) -> None:
    header = ",".join(FOOD_COLUMNS)
    bad = write(tmp_path / "f.csv", f"{header}\nx,X,raw,grain,,,abc,1,1,1,1,x\n")
    with pytest.raises(DataFileError, match=r"f\.csv:2: kcal_100 is not a number"):
        load_foods(bad)


def test_load_foods_rejects_non_numeric_yield(tmp_path: Path) -> None:
    header = ",".join(FOOD_COLUMNS)
    bad = write(tmp_path / "f.csv", f"{header}\nx,X,cooked,grain,y,two,1,1,1,1,1,x\n")
    with pytest.raises(DataFileError, match="yield_factor"):
        load_foods(bad)


def test_load_measures_rejects_non_numeric_grams(tmp_path: Path) -> None:
    bad = write(tmp_path / "m.csv", "food_code,name_ru,grams\napple,яблоко,много\n")
    with pytest.raises(DataFileError, match="grams is not a number"):
        load_measures(bad)


def test_load_roundtrip_small_file(tmp_path: Path) -> None:
    header = ",".join(FOOD_COLUMNS)
    text = f'{header}\nmilk,"Молоко 3,2%",ready,dairy,,,60,2.9,3.2,4.7,0,молоко|молоко 3.2\n'
    (row,) = load_foods(write(tmp_path / "f.csv", text))
    assert row.name_ru == "Молоко 3,2%"  # comma inside a quoted field survives
    assert row.aliases == ("молоко", "молоко 3.2")
    assert row.raw_code is None
    assert row.yield_factor is None


# ---------------------------------------------------- the real data files


@pytest.fixture(scope="module")
def real() -> tuple[list[FoodRow], list[MeasureRow]]:
    return load_foods(), load_measures()


def test_real_data_is_consistent(real: tuple[list[FoodRow], list[MeasureRow]]) -> None:
    assert validate_data(*real) == []


def test_real_data_has_enough_foods_and_measures(
    real: tuple[list[FoodRow], list[MeasureRow]],
) -> None:
    foods, measures = real
    assert 150 <= len(foods) <= 500
    assert len(measures) >= len(foods)


def test_real_data_covers_every_category(real: tuple[list[FoodRow], list[MeasureRow]]) -> None:
    foods, _ = real
    categories = Counter(f.category for f in foods)
    for category in FoodCategory:
        if category is not FoodCategory.OTHER:
            assert categories[category.value] > 0, f"no foods in category {category.value}"


@pytest.mark.parametrize(
    "raw_code",
    ["rice_white_raw", "buckwheat_raw", "pasta_raw", "chicken_breast_raw", "potato_raw"],
)
def test_staples_have_a_cooked_counterpart(
    real: tuple[list[FoodRow], list[MeasureRow]], raw_code: str
) -> None:
    foods, _ = real
    assert any(f.raw_code == raw_code for f in foods)


def test_anchor_values_are_in_a_sane_range(real: tuple[list[FoodRow], list[MeasureRow]]) -> None:
    """Coarse guard against fat-finger errors in well-known products (not a source check)."""
    foods = {f.code: f for f in real[0]}
    assert 340 <= foods["rice_white_raw"].kcal_100 <= 380
    assert 110 <= foods["rice_white_cooked"].kcal_100 <= 150
    assert 100 <= foods["chicken_breast_raw"].kcal_100 <= 140
    assert 20 <= foods["chicken_breast_raw"].protein_100 <= 25
    assert 40 <= foods["milk_2_5"].kcal_100 <= 60
    assert 850 <= foods["sunflower_oil"].kcal_100 <= 900
    assert 40 <= foods["apple"].kcal_100 <= 60
    assert 220 <= foods["bread_rye"].kcal_100 <= 300


def test_ambiguous_aliases_exist_by_design(real: tuple[list[FoodRow], list[MeasureRow]]) -> None:
    """The parser must ask a clarifying question for words like "курица" or "сыр"."""
    foods, _ = real
    owners = Counter(a for f in foods for a in f.aliases)
    assert owners["курица"] >= 2
    assert owners["сыр"] >= 2
