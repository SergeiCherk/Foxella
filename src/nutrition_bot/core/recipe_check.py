"""Checks of the words the language model writes: dish names and recipe texts. Pure functions.

The numbers of a dish come only from its items. A recipe must therefore not

- mention a calorie-dense food that is not in the items ("полейте сметаной" with no sour cream
  in the dish): those calories would never be counted;
- repeat amounts ("2 яйца", "100 г"): the program scales the portions, the text would lie;
- carry links, @accounts, e-mails or phone numbers: a menu is not a place for advertising.

Finding foods in free Russian text needs word forms ("сметаной" is "сметана"), which the
services layer knows; it is passed in as a ``MentionFinder``.
"""

import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Protocol

from nutrition_bot.core.errors import UnknownFoodError
from nutrition_bot.core.measures import Catalog

CALORIE_WORDS = re.compile(r"ккал|калор|kcal", re.IGNORECASE)
CONTACTS = re.compile(
    r"https?://|www\.|t\.me/|@[a-z0-9_]{3,}|[\w.+-]+@[\w-]+\.[a-z]{2,}"
    r"|\b[\w-]+\.(?:ru|com|net|org|рф|io|me|su|info|online|site|app|by|kz|ua)\b"
    r"|\+?\d[\d\s().-]{8,}\d",
    re.IGNORECASE,
)
# A number followed by a unit or a household measure: "100 г", "2 ст. ложки", "1,5 стакана".
AMOUNTS = re.compile(
    r"\d+(?:[.,/]\d+)?\s*(?:г|гр|грамм\w*|кг|мл|л|литр\w*|шт\w*|ст\.|ч\.|ложк\w*|ложек"
    r"|стакан\w*|половник\w*|кус\w*|ломтик\w*|горст\w*|пуч\w*|банк\w*|пачк\w*|%)(?![а-яё])",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class Mention:
    """A food named in a text: the words as written, the foods they may mean, and whether a
    number stands right before them ("2 яйца")."""

    words: str
    food_ids: frozenset[int]
    after_number: bool = False


class MentionFinder(Protocol):
    """Finds the foods a Russian text names (implemented in ``services``)."""

    def find(self, text: str) -> Sequence[Mention]:
        """All food mentions, in order."""
        ...


def text_problems(label: str, name: str, recipe: str) -> list[str]:
    """Contacts in the name or recipe, calories in the name, amounts in the recipe."""
    problems: list[str] = []
    if CONTACTS.search(name) or CONTACTS.search(recipe):
        problems.append(f"{label}: no links, @accounts, e-mails or phone numbers")
    if CALORIE_WORDS.search(name):
        problems.append(f"{label}: the name must not mention calories")
    amount = AMOUNTS.search(recipe)
    if amount:
        problems.append(
            f"{label}: recipe must not give amounts like «{amount.group(0)}», "
            "the program sets the portions"
        )
    return problems


def _family(catalog: Catalog, food_id: int) -> int | None:
    """Raw and cooked versions of a food are one family: "отварите гречку" is fine for cooked
    buckwheat in the items."""
    try:
        food = catalog.get_food(food_id)
    except UnknownFoodError:
        return None
    return food.raw_food_id or food.id


def recipe_food_problems(
    label: str,
    recipe: str,
    item_food_ids: Collection[int],
    catalog: Catalog,
    finder: MentionFinder,
    forbidden_food_ids: Collection[int] = (),
    min_kcal_100g: float = 100.0,
) -> list[str]:
    """Foods the recipe names but the items do not contain, and amounts next to food names."""
    in_dish = {f for i in item_food_ids if (f := _family(catalog, i)) is not None}
    forbidden = set(forbidden_food_ids)
    problems: list[str] = []
    for mention in finder.find(recipe):
        known = [i for i in mention.food_ids if _family(catalog, i) is not None]
        families = {_family(catalog, i) for i in known}
        if not known:
            continue
        if families & in_dish:
            if mention.after_number:
                problem = (
                    f"{label}: recipe must not give amounts like «{mention.words}», "
                    "the program sets the portions"
                )
            else:
                continue
        elif set(known) <= forbidden:
            problem = (
                f"{label}: recipe mentions «{mention.words}», which this person does not eat; "
                "remove it from the recipe"
            )
        elif max(catalog.get_food(i).per_100g.kcal for i in known) >= min_kcal_100g:
            problem = (
                f"{label}: recipe mentions «{mention.words}», but it is not in items; "
                "add it to items or remove it from the recipe"
            )
        else:
            continue
        if problem not in problems:
            problems.append(problem)
    return problems
