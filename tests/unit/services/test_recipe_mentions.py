"""services.recipe_mentions on the real aliases, and every built-in recipe passes the checks."""

import pytest

from nutrition_bot.core.menu import FALLBACK_TEMPLATES, _resolve
from nutrition_bot.core.recipe_check import recipe_food_problems, text_problems
from nutrition_bot.db.seed import load_foods
from nutrition_bot.services.recipe_mentions import AliasMentionFinder
from tests.catalog_helpers import real_catalog

CATALOG, IDS = real_catalog()


def _aliases() -> dict[str, list[int]]:
    aliases: dict[str, list[int]] = {}
    for row in load_foods():
        for alias in row.aliases:
            aliases.setdefault(alias, []).append(IDS[row.code])
    return aliases


FINDER = AliasMentionFinder(_aliases())


def found(text: str) -> list[tuple[str, bool]]:
    return [(m.words, m.after_number) for m in FINDER.find(text)]


def ids_of(text: str) -> list[frozenset[int]]:
    return [m.food_ids for m in FINDER.find(text)]


def test_word_forms_are_understood() -> None:
    assert found("Полейте сметаной и посыпьте сыром.") == [("сметаной", False), ("сыром", False)]
    assert IDS["sour_cream_15"] in ids_of("полейте сметаной")[0]


def test_the_longest_alias_wins() -> None:
    (butter,) = ids_of("Обжарьте на сливочном масле.")
    assert butter == frozenset({IDS["butter"]})


def test_a_longer_match_starting_inside_wins() -> None:
    (turkey,) = ids_of("Обжарьте или запеките грудку индейки.")
    assert IDS["turkey_breast_raw"] in turkey


@pytest.mark.parametrize("text", ["Взбейте 2 яйца.", "Взбейте два яйца.", "Добавьте пол яблока."])
def test_a_number_before_a_food_is_noticed(text: str) -> None:
    assert found(text)[-1][1] is True


def test_similar_words_are_not_foods() -> None:
    assert found("Подавайте сырое и рисуйте узор.") == []
    assert found("") == []


@pytest.mark.parametrize("template", FALLBACK_TEMPLATES, ids=lambda t: t.name)
def test_every_built_in_recipe_passes_the_checks(template: object) -> None:
    """Our own recipes follow the rules we set for the model."""
    dish = _resolve(template, CATALOG)  # type: ignore[arg-type]
    assert dish is not None
    items = [i.food_id for i in dish.items]
    assert text_problems("d", dish.name, dish.recipe_text) == []
    assert recipe_food_problems("d", dish.recipe_text, items, CATALOG, FINDER) == []
