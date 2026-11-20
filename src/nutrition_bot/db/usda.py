"""Refresh nutrient values in ``foods.csv`` from USDA FoodData Central (SR Legacy CSV download).

``food_sources.csv`` says where each food's values come from:

- ``usda``: one SR Legacy record (``fdc_ids``), per 100 g;
- ``usda_mix``: the plain average of several records (``fdc_ids`` joined with ``;``);
- ``derived``: a cooked grain or legume, ``raw / yield_factor`` (the grain only absorbs water);
- ``label``: a Russian product without a USDA match; values stay as they are and are checked
  against product labels by hand;
- ``recipe``: a ready dish (borscht, pelmeni) computed from the foods in ``dish_recipes.csv``:
  the sum of the ingredients divided by the dish weight. ``water`` adds weight only;
  ``cooked_weight`` replaces the sum of the weights when frying or baking loses water.

Only ``kcal_100 .. fiber_100`` (and nothing else) are rewritten.
"""

import csv
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from nutrition_bot.config import DATA_DIR

SOURCES_CSV = DATA_DIR / "food_sources.csv"
SOURCE_COLUMNS = ["code", "source", "fdc_ids", "note"]
SOURCES = ("usda", "usda_mix", "derived", "label", "recipe")
RECIPES_CSV = DATA_DIR / "dish_recipes.csv"
RECIPE_COLUMNS = ["dish_code", "food_code", "grams"]
WATER = "water"  # weight without nutrients
COOKED_WEIGHT = "cooked_weight"  # the weight of the finished dish, if not the sum
FIELDS = ("kcal_100", "protein_100", "fat_100", "carb_100", "fiber_100")
# SR Legacy nutrient ids for FIELDS, in the same order.
NUTRIENT_IDS = {"1008": "kcal_100", "1003": "protein_100", "1004": "fat_100",
                "1005": "carb_100", "1079": "fiber_100"}  # fmt: skip
OPTIONAL_FIELDS = {"fiber_100"}  # SR Legacy leaves fibre out for some fish: it is 0 there

Values = dict[str, float]


class UsdaImportError(ValueError):
    """The sources file or the USDA download does not fit together."""


@dataclass(frozen=True)
class Source:
    """One line of ``food_sources.csv``."""

    code: str
    source: str
    fdc_ids: tuple[str, ...]
    note: str


@dataclass(frozen=True)
class Change:
    """One value that the import would change."""

    code: str
    field: str
    old: str
    new: str


def load_sources(path: Path = SOURCES_CSV) -> dict[str, Source]:
    """Parse ``food_sources.csv``; every line must be well formed."""
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != SOURCE_COLUMNS:
            raise UsdaImportError(f"{path.name}: expected columns {SOURCE_COLUMNS}")
        sources: dict[str, Source] = {}
        for line, raw in enumerate(reader, start=2):
            ids = tuple(i for i in raw["fdc_ids"].split(";") if i)
            src = Source(raw["code"], raw["source"], ids, raw["note"])
            problem = _source_problem(src)
            if problem or src.code in sources:
                raise UsdaImportError(f"{path.name}:{line}: {problem or 'duplicate code'}")
            sources[src.code] = src
    return sources


def _source_problem(src: Source) -> str | None:
    if src.source not in SOURCES:
        return f"unknown source {src.source!r}"
    if not all(i.isdigit() for i in src.fdc_ids):
        return "fdc_ids must be numbers"
    expected = {"usda": (1, 1), "usda_mix": (2, 9), "derived": (0, 0), "label": (0, 0),
                "recipe": (0, 0)}  # fmt: skip
    low, high = expected[src.source]
    if not low <= len(src.fdc_ids) <= high:
        return f"{src.source} needs {low}..{high} fdc_ids, got {len(src.fdc_ids)}"
    return None


Recipe = list[tuple[str, float]]


def load_recipes(path: Path = RECIPES_CSV) -> dict[str, Recipe]:
    """Parse ``dish_recipes.csv``: (food code, grams) per dish, in file order."""
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != RECIPE_COLUMNS:
            raise UsdaImportError(f"{path.name}: expected columns {RECIPE_COLUMNS}")
        recipes: dict[str, Recipe] = {}
        for line, raw in enumerate(reader, start=2):
            try:
                grams = float(raw["grams"])
            except ValueError:
                raise UsdaImportError(f"{path.name}:{line}: grams must be a number") from None
            if not grams > 0:
                raise UsdaImportError(f"{path.name}:{line}: grams must be positive")
            recipes.setdefault(raw["dish_code"], []).append((raw["food_code"], grams))
    return recipes


def recipe_values(code: str, recipe: Recipe, by_code: Mapping[str, Mapping[str, str]]) -> Values:
    """Per-100 g values of a dish: the ingredients' sum over the dish weight."""
    totals = dict.fromkeys(FIELDS, 0.0)
    weight = 0.0
    cooked: float | None = None
    for food, grams in recipe:
        if food == COOKED_WEIGHT:
            cooked = grams
            continue
        weight += grams
        if food == WATER:
            continue
        row = by_code.get(food)
        if row is None:
            raise UsdaImportError(f"{code}: unknown ingredient {food!r}")
        for field in FIELDS:
            totals[field] += float(row[field]) * grams / 100
    final = cooked if cooked is not None else weight
    if final <= 0:
        raise UsdaImportError(f"{code}: the recipe has no weight")
    return {field: total * 100 / final for field, total in totals.items()}


def read_usda(sr_dir: Path, fdc_ids: Iterable[str]) -> dict[str, Values]:
    """Per-100 g values of the requested SR Legacy records."""
    wanted = set(fdc_ids)
    found: dict[str, Values] = {}
    path = sr_dir / "food_nutrient.csv"
    if not path.is_file():
        raise UsdaImportError(f"{path} not found: download the SR Legacy CSV from fdc.nal.usda.gov")
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            field = NUTRIENT_IDS.get(row["nutrient_id"])
            if field and row["fdc_id"] in wanted:
                found.setdefault(row["fdc_id"], {})[field] = float(row["amount"])
    missing = sorted(wanted - found.keys())
    if missing:
        raise UsdaImportError(f"fdc_ids not in {sr_dir.name}: {', '.join(missing)}")
    return found


def _usda_values(code: str, ids: tuple[str, ...], usda: Mapping[str, Values]) -> Values:
    values: Values = {}
    for field in FIELDS:
        amounts = [usda[i].get(field) for i in ids]
        if any(a is None for a in amounts):
            if field not in OPTIONAL_FIELDS:
                raise UsdaImportError(f"{code}: {field} is missing in USDA record(s) {ids}")
            amounts = [a or 0.0 for a in amounts]
        values[field] = sum(a for a in amounts if a is not None) / len(amounts)
    return values


def _fmt(field: str, value: float) -> str:
    places = Decimal("1") if field == "kcal_100" else Decimal("0.1")
    return str(Decimal(repr(value)).quantize(places, rounding=ROUND_HALF_UP))


def refresh_rows(
    rows: list[dict[str, str]],
    sources: Mapping[str, Source],
    usda: Mapping[str, Values],
    recipes: Mapping[str, Recipe] | None = None,
) -> tuple[list[dict[str, str]], list[Change]]:
    """New ``foods.csv`` rows (as text) and the list of values that changed."""
    recipes = recipes or {}
    codes = [r["code"] for r in rows]
    if set(codes) != set(sources):
        extra, lacking = set(sources) - set(codes), set(codes) - set(sources)
        raise UsdaImportError(
            f"food_sources.csv and foods.csv differ: missing {sorted(lacking)}, "
            f"unknown {sorted(extra)}"
        )
    dishes = {c for c, s in sources.items() if s.source == "recipe"}
    if dishes != set(recipes):
        raise UsdaImportError(
            f"dish_recipes.csv and the recipe sources differ: without a recipe "
            f"{sorted(dishes - set(recipes))}, not a recipe source {sorted(set(recipes) - dishes)}"
        )
    for dish, recipe in recipes.items():
        nested = [food for food, _ in recipe if food in dishes]
        if nested:
            raise UsdaImportError(f"{dish}: a dish cannot be made of other dishes {nested}")
    by_code = {r["code"]: dict(r) for r in rows}
    # Derived rows use the raw row's *new* values and dishes use both, so they go last.
    rank = {"derived": 1, "recipe": 2}
    order = sorted(codes, key=lambda c: rank.get(sources[c].source, 0))
    for code in order:
        src, row = sources[code], by_code[code]
        if src.source in ("usda", "usda_mix"):
            new = {f: _fmt(f, v) for f, v in _usda_values(code, src.fdc_ids, usda).items()}
        elif src.source == "derived":
            if not row["raw_code"] or not row["yield_factor"]:
                raise UsdaImportError(f"{code}: derived needs raw_code and yield_factor")
            raw, factor = by_code[row["raw_code"]], float(row["yield_factor"])
            new = {f: _fmt(f, float(raw[f]) / factor) for f in FIELDS}
        elif src.source == "recipe":
            new = {f: _fmt(f, v) for f, v in recipe_values(code, recipes[code], by_code).items()}
        else:
            continue
        row.update(new)
    changes = [
        Change(r["code"], f, r[f], by_code[r["code"]][f])
        for r in rows
        for f in FIELDS
        if float(r[f]) != float(by_code[r["code"]][f])
    ]
    return [by_code[c] for c in codes], changes


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Columns and rows of a CSV file, as text."""
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def write_rows(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    """Write rows back in the repository's format (UTF-8, LF, minimal quoting)."""
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
