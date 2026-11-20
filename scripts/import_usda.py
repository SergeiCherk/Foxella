"""Refresh calories and macros in foods.csv from USDA FoodData Central (SR Legacy).

Download "SR Legacy" (CSV) from https://fdc.nal.usda.gov/download-datasets and unzip it into
data/usda/ (the folder is git-ignored). Then:

    uv run python scripts/import_usda.py            # show what would change
    uv run python scripts/import_usda.py --write    # update foods.csv

Where each food's values come from is listed in src/nutrition_bot/data/food_sources.csv;
ready dishes are computed from src/nutrition_bot/data/dish_recipes.csv.
"""

import argparse
import sys
from pathlib import Path

from nutrition_bot.config import PROJECT_ROOT
from nutrition_bot.db.seed import FOODS_CSV
from nutrition_bot.db.usda import (
    UsdaImportError,
    load_recipes,
    load_sources,
    read_rows,
    read_usda,
    refresh_rows,
    write_rows,
)

DEFAULT_SR_DIR = PROJECT_ROOT / "data" / "usda" / "FoodData_Central_sr_legacy_food_csv_2018-04"


def main(argv: list[str] | None = None) -> int:
    """Print the changes; with --write, save them to foods.csv."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sr-dir", type=Path, default=DEFAULT_SR_DIR, help="unzipped SR Legacy")
    parser.add_argument("--write", action="store_true", help="update foods.csv")
    args = parser.parse_args(argv)
    try:
        sources = load_sources()
        ids = {i for s in sources.values() for i in s.fdc_ids}
        usda = read_usda(args.sr_dir, ids)
        columns, rows = read_rows(FOODS_CSV)
        new_rows, changes = refresh_rows(rows, sources, usda, load_recipes())
    except UsdaImportError as error:
        print(f"ERROR: {error}")
        return 1
    for c in changes:
        print(f"{c.code:24} {c.field:12} {c.old:>7} -> {c.new}")
    counts = {name: sum(s.source == name for s in sources.values()) for name in
              ("usda", "usda_mix", "derived", "label", "recipe")}  # fmt: skip
    print(f"{len(changes)} value(s) differ; sources: {counts}")
    if args.write and changes:
        write_rows(FOODS_CSV, columns, new_rows)
        print("foods.csv updated: run scripts/validate_data.py and pytest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
