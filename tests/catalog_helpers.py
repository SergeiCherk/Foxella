"""Helpers that build a core Catalog from the real CSV files, without a database."""

from nutrition_bot.core.measures import Catalog
from nutrition_bot.core.models import FoodState
from nutrition_bot.db.seed import catalog_from_rows, load_foods, load_measures


def real_catalog() -> tuple[Catalog, dict[str, int]]:
    """The catalog built from the shipped foods.csv and measures.csv."""
    return catalog_from_rows(load_foods(), load_measures())


def cooked_or_ready_ids(catalog: Catalog) -> tuple[int, ...]:
    """Ids a dish may use: everything that is not a raw (uncooked) food."""
    return tuple(f.id for f in catalog.foods if f.state is not FoodState.RAW)
