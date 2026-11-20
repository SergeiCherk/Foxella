"""Food restrictions (no meat, no nuts, ...): which foods a menu must never contain. Pure."""

from collections.abc import Iterable

from nutrition_bot.config import DietConfig
from nutrition_bot.core.measures import Catalog


def known_restrictions(codes: Iterable[str], cfg: DietConfig) -> list[str]:
    """The codes that exist in the config, in the config's order (unknown ones are dropped)."""
    wanted = set(codes)
    return [code for code in cfg.rules if code in wanted]


def forbidden_food_ids(catalog: Catalog, codes: Iterable[str], cfg: DietConfig) -> frozenset[int]:
    """Every food that one of the restrictions removes.

    A rule names categories and food codes. A cooked food goes with its raw food, so "pasta_raw"
    also removes cooked pasta.
    """
    categories: set[str] = set()
    food_codes: set[str] = set()
    for code in known_restrictions(codes, cfg):
        rule = cfg.rules[code]
        categories.update(rule.categories)
        food_codes.update(rule.codes)
    direct = {f.id for f in catalog.foods if f.category.value in categories or f.code in food_codes}
    cooked = {f.id for f in catalog.foods if f.raw_food_id is not None and f.raw_food_id in direct}
    return frozenset(direct | cooked)
