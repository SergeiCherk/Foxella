"""Finding the foods a recipe text names, by the same aliases the food parser uses.

"Полейте сметаной" -> sour cream; "2 яйца" -> eggs, right after a number. Word forms are reduced
to their dictionary form, and the longest alias wins ("сливочное масло" before "масло"). Only
whole aliases count: no fuzzy matching here, a recipe is not a typed shopping list.
"""

import re
from collections.abc import Mapping, Sequence

from nutrition_bot.core.recipe_check import Mention
from nutrition_bot.services.food_parser import lemma

_TOKEN = re.compile(r"[a-zа-яё]+|\d+(?:[.,]\d+)?")
_WORD = re.compile(r"[a-zа-яё]+")
# Dictionary forms of number words that make the next food an amount ("две ложки", "пол-яблока").
NUMBER_WORDS = frozenset(
    {
        "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять", "десять",
        "пол", "половина", "половинка", "полтора", "пара", "несколько",
    }
)  # fmt: skip


class AliasMentionFinder:
    """Implements ``core.recipe_check.MentionFinder``. Build it once; ``find`` is cheap."""

    def __init__(self, aliases: Mapping[str, Sequence[int]]) -> None:
        self._index: dict[tuple[str, ...], frozenset[int]] = {}
        for alias, food_ids in aliases.items():
            key = tuple(lemma(w) for w in _WORD.findall(alias.lower()))
            if key:
                self._index[key] = self._index.get(key, frozenset()) | frozenset(food_ids)
        self._max_len = max((len(k) for k in self._index), default=0)

    def _longest_at(self, lemmas: list[str], i: int) -> int:
        """Length of the longest alias that starts at word ``i`` (0 if none)."""
        for n in range(min(self._max_len, len(lemmas) - i), 0, -1):
            key = tuple(lemmas[i : i + n])
            if "" not in key and key in self._index:
                return n
        return 0

    def find(self, text: str) -> Sequence[Mention]:
        """Every alias found in ``text``, left to right, without overlaps.

        A match gives way to one that starts inside it and reaches further: in "запеките грудку
        индейки" the food is "грудка индейки", not "запечённая грудка".
        """
        tokens = _TOKEN.findall(text.lower())
        lemmas = [lemma(t) if t[0].isalpha() else "" for t in tokens]
        mentions: list[Mention] = []
        i = 0
        while i < len(tokens):
            n = self._longest_at(lemmas, i)
            if n == 0 or any(j + self._longest_at(lemmas, j) > i + n for j in range(i + 1, i + n)):
                i += 1
                continue
            previous = tokens[i - 1] if i else ""
            after_number = bool(previous) and (
                previous[0].isdigit() or lemmas[i - 1] in NUMBER_WORDS
            )
            key = tuple(lemmas[i : i + n])
            mentions.append(Mention(" ".join(tokens[i : i + n]), self._index[key], after_number))
            i += n
        return mentions
