"""Loading and validating the seed files ``foods.csv`` and ``measures.csv``.

The validator is the safety net for hand-collected data: it cannot prove a number is right,
but it catches typos, impossible values and broken raw/cooked links.
"""

import csv
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from nutrition_bot.config import DATA_DIR
from nutrition_bot.core.measures import Catalog
from nutrition_bot.core.models import Food, FoodCategory, FoodState, Measure, Nutrients

FOODS_CSV = DATA_DIR / "foods.csv"
MEASURES_CSV = DATA_DIR / "measures.csv"

# Validation thresholds (data sanity checks, not product formulas).
MACRO_SUM_TOLERANCE_G = 0.5  # protein + fat + carbs may not exceed 100 g by more than this
ATWATER_MIN_TOLERANCE_KCAL = 20.0  # kcal vs 4P + 4C + 9F: absolute slack ...
ATWATER_REL_TOLERANCE = 0.12  # ... or this share of the Atwater value, whichever is larger
# Alcohol gives 7 kcal/g and is not a macro, so drinks cannot match 4P + 4C + 9F.
ATWATER_EXEMPT = frozenset({"beer", "wine_red", "wine_white", "vodka"})
MAX_YIELD_FACTOR = 8.0  # cooked grams per raw gram (oats absorb the most water)
ENERGY_RATIO_RANGE = (0.75, 1.25)  # kcal_cooked * yield / kcal_raw must stay in this range
MAX_MEASURE_GRAMS = 1000.0

FOOD_COLUMNS = [
    "code",
    "name_ru",
    "state",
    "category",
    "raw_code",
    "yield_factor",
    "kcal_100",
    "protein_100",
    "fat_100",
    "carb_100",
    "fiber_100",
    "aliases",
]
MEASURE_COLUMNS = ["food_code", "name_ru", "grams"]


class DataFileError(Exception):
    """A seed file is malformed (missing column, non-numeric value)."""


@dataclass(frozen=True, slots=True)
class FoodRow:
    """One line of ``foods.csv``."""

    code: str
    name_ru: str
    state: str
    category: str
    raw_code: str | None
    yield_factor: float | None
    kcal_100: float
    protein_100: float
    fat_100: float
    carb_100: float
    fiber_100: float
    aliases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MeasureRow:
    """One line of ``measures.csv``."""

    food_code: str
    name_ru: str
    grams: float


def _read(path: Path, columns: list[str]) -> list[tuple[int, dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != columns:
            raise DataFileError(f"{path.name}: expected columns {columns}, got {reader.fieldnames}")
        return [(line, row) for line, row in enumerate(reader, start=2)]


def _number(path: Path, line: int, column: str, value: str) -> float:
    try:
        return float(value)
    except ValueError:
        raise DataFileError(f"{path.name}:{line}: {column} is not a number: {value!r}") from None


def load_foods(path: Path = FOODS_CSV) -> list[FoodRow]:
    """Parse ``foods.csv`` into rows. Raises ``DataFileError`` on malformed input."""
    rows: list[FoodRow] = []
    for line, raw in _read(path, FOOD_COLUMNS):
        num = {c: _number(path, line, c, raw[c]) for c in FOOD_COLUMNS[6:11]}
        yield_text = raw["yield_factor"].strip()
        yield_factor = _number(path, line, "yield_factor", yield_text) if yield_text else None
        rows.append(
            FoodRow(
                code=raw["code"].strip(),
                name_ru=raw["name_ru"].strip(),
                state=raw["state"].strip(),
                category=raw["category"].strip(),
                raw_code=raw["raw_code"].strip() or None,
                yield_factor=yield_factor,
                kcal_100=num["kcal_100"],
                protein_100=num["protein_100"],
                fat_100=num["fat_100"],
                carb_100=num["carb_100"],
                fiber_100=num["fiber_100"],
                aliases=tuple(a for a in raw["aliases"].split("|") if a),
            )
        )
    return rows


def load_measures(path: Path = MEASURES_CSV) -> list[MeasureRow]:
    """Parse ``measures.csv`` into rows. Raises ``DataFileError`` on malformed input."""
    return [
        MeasureRow(
            food_code=raw["food_code"].strip(),
            name_ru=raw["name_ru"].strip(),
            grams=_number(path, line, "grams", raw["grams"]),
        )
        for line, raw in _read(path, MEASURE_COLUMNS)
    ]


def _check_food(food: FoodRow, by_code: dict[str, FoodRow]) -> list[str]:
    who = f"food {food.code}"
    problems: list[str] = []
    if food.state not in {s.value for s in FoodState}:
        problems.append(f"{who}: unknown state {food.state!r}")
    if food.category not in {c.value for c in FoodCategory}:
        problems.append(f"{who}: unknown category {food.category!r}")

    values = [food.kcal_100, food.protein_100, food.fat_100, food.carb_100, food.fiber_100]
    if any(not math.isfinite(v) or v < 0 for v in values):
        problems.append(f"{who}: nutrients must be finite and >= 0")
        return problems  # the checks below would only produce noise
    if food.protein_100 + food.fat_100 + food.carb_100 > 100 + MACRO_SUM_TOLERANCE_G:
        problems.append(f"{who}: protein + fat + carbs exceed 100 g")
    if food.fiber_100 > food.carb_100 + MACRO_SUM_TOLERANCE_G:
        problems.append(f"{who}: fibre ({food.fiber_100}) exceeds carbs ({food.carb_100})")

    atwater = 4 * food.protein_100 + 4 * food.carb_100 + 9 * food.fat_100
    slack = max(ATWATER_MIN_TOLERANCE_KCAL, ATWATER_REL_TOLERANCE * atwater)
    if food.code not in ATWATER_EXEMPT and abs(food.kcal_100 - atwater) > slack:
        problems.append(f"{who}: kcal {food.kcal_100} does not match macros (about {atwater:.0f})")

    if food.state == "cooked":
        problems += _check_cooked(food, by_code)
    elif food.raw_code is not None or food.yield_factor is not None:
        problems.append(f"{who}: only cooked foods may have raw_code / yield_factor")

    if not food.aliases:
        problems.append(f"{who}: has no aliases")
    if len(set(food.aliases)) != len(food.aliases):
        problems.append(f"{who}: duplicate aliases")
    if any(a != a.strip().lower() for a in food.aliases):
        problems.append(f"{who}: aliases must be lowercase and trimmed")
    return problems


def _check_cooked(food: FoodRow, by_code: dict[str, FoodRow]) -> list[str]:
    who = f"food {food.code}"
    raw = by_code.get(food.raw_code or "")
    if raw is None:
        return [f"{who}: raw_code {food.raw_code!r} does not exist"]
    if raw.state != "raw":
        return [f"{who}: raw_code {raw.code} is not a raw food"]
    if food.yield_factor is None or not 0 < food.yield_factor <= MAX_YIELD_FACTOR:
        return [f"{who}: yield_factor must be in (0, {MAX_YIELD_FACTOR}]"]
    low, high = ENERGY_RATIO_RANGE
    ratio = food.kcal_100 * food.yield_factor / raw.kcal_100 if raw.kcal_100 else 0.0
    if not low <= ratio <= high:
        return [f"{who}: energy of cooked vs raw is inconsistent with yield (ratio {ratio:.2f})"]
    return []


def validate_data(foods: list[FoodRow], measures: list[MeasureRow]) -> list[str]:
    """Return a list of human-readable problems; an empty list means the data is consistent."""
    problems: list[str] = []
    for field, label in (("code", "code"), ("name_ru", "name")):
        counts = Counter(getattr(f, field) for f in foods)
        problems += [f"duplicate food {label}: {v}" for v, n in counts.items() if n > 1]

    by_code = {f.code: f for f in foods}
    for food in foods:
        problems += _check_food(food, by_code)

    seen: set[tuple[str, str]] = set()
    for m in measures:
        who = f"measure {m.food_code}/{m.name_ru}"
        if m.food_code not in by_code:
            problems.append(f"{who}: unknown food")
        if not m.name_ru:
            problems.append(f"{who}: empty name")
        if not math.isfinite(m.grams) or not 0 < m.grams <= MAX_MEASURE_GRAMS:
            problems.append(f"{who}: grams must be in (0, {MAX_MEASURE_GRAMS:g}]")
        if (m.food_code, m.name_ru) in seen:
            problems.append(f"{who}: duplicate measure")
        seen.add((m.food_code, m.name_ru))

    with_measures = {m.food_code for m in measures}
    problems += [
        f"food {f.code}: has no household measure" for f in foods if f.code not in with_measures
    ]
    return problems


def catalog_from_rows(
    foods: list[FoodRow], measures: list[MeasureRow]
) -> tuple[Catalog, dict[str, int]]:
    """Build a core ``Catalog`` straight from the CSV rows (no database). Also returns code -> id.

    Ids are the 1-based row numbers; they match the database ids only on a freshly seeded DB,
    so use this for tools and tests, not for data that is stored.
    """
    ids = {row.code: i for i, row in enumerate(foods, start=1)}
    core_foods = [
        Food(
            id=ids[r.code],
            code=r.code,
            name_ru=r.name_ru,
            state=FoodState(r.state),
            category=FoodCategory(r.category),
            per_100g=Nutrients(r.kcal_100, r.protein_100, r.fat_100, r.carb_100, r.fiber_100),
            raw_food_id=ids[r.raw_code] if r.raw_code else None,
            yield_factor=r.yield_factor,
        )
        for r in foods
    ]
    core_measures = [
        Measure(i, ids[m.food_code], m.name_ru, m.grams) for i, m in enumerate(measures, start=1)
    ]
    return Catalog(core_foods, core_measures), ids
