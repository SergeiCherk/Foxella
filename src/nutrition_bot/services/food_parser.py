"""Free-text food list -> food ids. Understands word forms, simple quantities and typos.

"2 варёных яйца, творог, греча" becomes two resolved items and one ambiguous one (several
kinds of cottage cheese). The parser only knows aliases and ids; it never invents a food.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from functools import lru_cache

import pymorphy3
from rapidfuzz import fuzz, process

from nutrition_bot.config import ParserConfig
from nutrition_bot.core.models import Measure

_TOKEN = re.compile(r"\d+\s*/\s*\d+|\d+(?:[.,]\d+)?|[½¼¾]|[a-zа-я]+")
# A comma between two digits is a decimal comma ("2,5"), not a separator.
_SPLIT = re.compile(r"(?<!\d),|,(?!\d)|[;\n]+|\s+и\s+|\s+\+\s+")
_VULGAR = {"½": 0.5, "¼": 0.25, "¾": 0.75}
_WORD_NUMBERS = {
    "пара": 2.0,
    "два": 2.0,
    "две": 2.0,
    "три": 3.0,
    "четыре": 4.0,
    "пять": 5.0,
    "шесть": 6.0,
    "полтора": 1.5,
    "полторы": 1.5,
    "пол": 0.5,
    "половина": 0.5,
    "половинка": 0.5,
}
# Words that carry no meaning for matching (units written after a number, small joiners).
_NOISE = {"шт", "штука", "x", "х", "с", "со", "из", "на", "в"}


@lru_cache(maxsize=1)
def _morph() -> pymorphy3.MorphAnalyzer:
    return pymorphy3.MorphAnalyzer()


def _norm(text: str) -> str:
    return text.lower().replace("ё", "е")


@lru_cache(maxsize=8192)
def lemma(word: str) -> str:
    """Dictionary form of a Russian word (``яйца`` -> ``яйцо``); ё and е are not told apart."""
    return _norm(_morph().parse(_norm(word))[0].normal_form)


def _lemmas(text: str) -> tuple[str, ...]:
    return tuple(lemma(w) for w in re.findall(r"[a-zа-я]+", _norm(text)))


@dataclass(frozen=True, slots=True)
class ParsedItem:
    """One recognised product. ``words`` are the other lemmas of the phrase (a measure hint)."""

    food_id: int
    quantity: float
    words: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class Ambiguity:
    """A phrase that may mean several foods; the user is asked to choose."""

    text: str
    food_ids: tuple[int, ...]
    quantity: float
    words: frozenset[str] = frozenset()


@dataclass(slots=True)
class ParseResult:
    """What was understood: ``items`` are sure, ``ambiguous`` need a choice, ``unknown`` failed."""

    items: list[ParsedItem] = field(default_factory=list)
    ambiguous: list[Ambiguity] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)


def _number(token: str) -> float | None:
    if token in _VULGAR:
        return _VULGAR[token]
    if "/" in token:
        top, _, bottom = token.partition("/")
        return float(Fraction(int(top), int(bottom))) if int(bottom) else None
    if token[0].isdigit():
        return float(token.replace(",", "."))
    return _WORD_NUMBERS.get(token)


class FoodParser:
    """Matches phrases to foods by aliases. Build it once; ``parse`` is cheap and pure."""

    def __init__(self, aliases: Mapping[str, Sequence[int]], cfg: ParserConfig) -> None:
        self._cfg = cfg
        self._index: dict[tuple[str, ...], list[int]] = {}
        self._written: dict[str, tuple[str, ...]] = {}  # alias as written -> its lemma key
        for alias, food_ids in aliases.items():
            key = _lemmas(alias)
            if key:
                bucket = self._index.setdefault(key, [])
                bucket.extend(i for i in food_ids if i not in bucket)
                self._written[" ".join(re.findall(r"[a-zа-я]+", _norm(alias)))] = key
        self._max_len = max((len(k) for k in self._index), default=0)
        self._joined = {" ".join(k): k for k in self._index}

    def parse(self, text: str) -> ParseResult:
        """Read a list of products separated by commas, line breaks or "и"."""
        result = ParseResult()
        chunks = [c.strip() for c in _SPLIT.split(text[: self._cfg.max_text_length])]
        for chunk in [c for c in chunks if c][: self._cfg.max_chunks]:
            self._parse_chunk(chunk, result)
        return result

    def _parse_chunk(self, chunk: str, result: ParseResult) -> None:
        quantity = self._cfg.default_quantity
        found_quantity = False
        lemmas: list[str] = []
        written: list[str] = []
        for token in _TOKEN.findall(_norm(chunk)):
            number = _number(token)
            if number is not None and not found_quantity:
                quantity, found_quantity = number, True
            elif number is None and token[0].isalpha() and token not in _NOISE:
                lemmas.append(lemma(token))
                written.append(token)
        key = self._match(lemmas, written)
        if key is None:
            result.unknown.append(chunk[:60])
            return
        food_ids = self._index[key]
        words = frozenset(lemmas) - set(key)
        if len(food_ids) == 1:
            if all(item.food_id != food_ids[0] for item in result.items):
                result.items.append(ParsedItem(food_ids[0], quantity, words))
        else:
            result.ambiguous.append(Ambiguity(chunk[:60], tuple(food_ids), quantity, words))

    def _match(self, lemmas: list[str], written: list[str]) -> tuple[str, ...] | None:
        """The longest alias that appears in the phrase as consecutive words, else a fuzzy one.

        The fuzzy step compares both the dictionary forms and the words as typed: the
        lemmatizer guesses badly on misspelled words, the typed form does not.
        """
        for size in range(min(len(lemmas), self._max_len), 0, -1):
            for start in range(len(lemmas) - size + 1):
                window = tuple(lemmas[start : start + size])
                if window in self._index:
                    return window
        candidates = (
            (" ".join(lemmas), self._joined),
            (" ".join(written), self._written),
        )
        top_score, top_key = 0.0, None
        for phrase, choices in candidates:
            if len(phrase) < 3 or not choices:
                continue
            best = process.extractOne(
                phrase, choices.keys(), scorer=fuzz.ratio, score_cutoff=self._cfg.fuzzy_cutoff
            )
            if best is not None and best[1] > top_score:
                top_score, top_key = best[1], choices[best[0]]
        return top_key


def choose_measure(measures: Sequence[Measure], words: frozenset[str]) -> Measure | None:
    """The measure the user named ("2 куска пиццы" -> кусок), else the first (smallest id)."""
    if not measures:
        return None
    ordered = sorted(measures, key=lambda m: m.id)
    for measure in ordered:
        if any(w in words for w in _lemmas(measure.name_ru)):
            return measure
    return ordered[0]
